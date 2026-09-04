use std::net::TcpListener;
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct AppState {
    /// The port the backend is ACTUALLY serving on. Starts as the pre-found
    /// free port, but the stdout line pump updates it if the backend announces
    /// it had to move (see the "serving on free port" parsing in `run()`), so
    /// every reader must load it fresh rather than capture it once.
    api_port: Arc<AtomicU16>,
    sidecar_child: Mutex<Option<CommandChild>>,
}

/// Try to bind to preferred ports in order.
///
/// FinanceTracker uses a dedicated 84xx range (NOT 8000, which commonly
/// collides with other local dev servers) so it starts on 8420 every time
/// and only drifts if that exact port is already taken.
fn find_port() -> u16 {
    for port in [8420, 8421, 8422, 8423, 8424, 8425] {
        if TcpListener::bind(format!("127.0.0.1:{}", port)).is_ok() {
            return port;
        }
    }
    TcpListener::bind("127.0.0.1:0")
        .expect("failed to bind to any port")
        .local_addr()
        .expect("failed to get local addr")
        .port()
}

/// Wait for the backend health endpoint to respond.
///
/// Re-reads the CURRENT port on every iteration: `find_port()` runs before the
/// onefile sidecar spends 40-120s extracting, so another process can take the
/// pre-found port in that window. The backend self-heals onto the next free
/// port (announcing it on stdout, which updates `port`), and this poll follows
/// it there instead of spinning forever on the stolen port.
fn wait_for_backend(port: &Arc<AtomicU16>, timeout_secs: u64) -> bool {
    let start = Instant::now();
    let timeout = Duration::from_secs(timeout_secs);
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .expect("failed to build HTTP client");

    while start.elapsed() < timeout {
        let url = format!("http://127.0.0.1:{}/health", port.load(Ordering::SeqCst));
        if let Ok(resp) = client.get(&url).send() {
            if resp.status().is_success() {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

#[tauri::command]
fn get_api_port(state: tauri::State<'_, AppState>) -> u16 {
    state.api_port.load(Ordering::SeqCst)
}

/// Collect every live descendant PID of `pid` (children, grandchildren, ...).
///
/// Used to reap the PyInstaller *onefile* layout: the tracked process is the
/// bootloader, which extracts and spawns a SEPARATE child that actually binds
/// the port. SIGTERM is forwarded by the bootloader, but SIGKILL is not — so
/// killing only the tracked PID leaves that child orphaned, still holding the
/// port. Walking `pgrep -P` keeps the blast radius provably inside our own
/// process tree (never a name/port sweep that could hit another app).
#[cfg(not(target_os = "windows"))]
fn descendants_of(pid: u32) -> Vec<u32> {
    let mut found = Vec::new();
    let mut frontier = vec![pid];
    // Bounded walk: a sidecar tree is tiny; the cap prevents pathological loops.
    for _ in 0..16 {
        let mut next = Vec::new();
        for parent in frontier.drain(..) {
            if let Ok(out) = std::process::Command::new("pgrep")
                .args(["-P", &parent.to_string()])
                .output()
            {
                for line in String::from_utf8_lossy(&out.stdout).lines() {
                    if let Ok(child) = line.trim().parse::<u32>() {
                        if child != 0 && !found.contains(&child) {
                            found.push(child);
                            next.push(child);
                        }
                    }
                }
            }
        }
        if next.is_empty() {
            break;
        }
        frontier = next;
    }
    found
}

/// Path of the file recording the PID of the sidecar THIS instance spawned.
///
/// The name carries our own app PID (`backend-<app_pid>.pid`) so that a second,
/// concurrently running instance can tell our record apart from its own. With a
/// single shared `backend.pid` it could not: every launch read the one record
/// and killed the process named in it, so starting a second instance SIGKILLed
/// the first instance's live backend mid-flight.
fn sidecar_pid_file(app_data_dir: &std::path::Path) -> std::path::PathBuf {
    app_data_dir.join(format!("backend-{}.pid", std::process::id()))
}

/// Which app instance wrote a pid file, as encoded in its file name.
#[derive(Debug, PartialEq, Eq)]
enum PidFileOwner {
    /// `backend.pid` — written by an older build that recorded no owner.
    Legacy,
    /// `backend-<app_pid>.pid` — written by the app process with that PID.
    Instance(u32),
}

/// Classify a file name inside the app-data dir. `None` = not one of ours.
fn pid_file_owner(file_name: &str) -> Option<PidFileOwner> {
    if file_name == "backend.pid" {
        return Some(PidFileOwner::Legacy);
    }
    let rest = file_name.strip_prefix("backend-")?.strip_suffix(".pid")?;
    rest.parse::<u32>().ok().map(PidFileOwner::Instance)
}

/// File name of the running executable — the needle that identifies another
/// instance of THIS app when checking whether a recorded owner is still alive.
fn own_process_name() -> Option<String> {
    std::env::current_exe()
        .ok()?
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
}

/// Does `tasklist /FO CSV /NH` output describe a process matching `needle`?
///
/// Split out from the Windows branch of `process_matches` so it is testable on
/// any host. Windows process names are case-insensitive, and the "no such PID"
/// banner must never be mistaken for a match.
// Only the Windows branch of `process_matches` calls it at runtime; the unit
// tests below exercise it on every platform.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
fn tasklist_matches(stdout: &str, needle: &str) -> bool {
    let lower = stdout.to_ascii_lowercase();
    if lower.contains("no tasks are running") {
        return false;
    }
    lower.contains(&needle.to_ascii_lowercase())
}

/// Is `pid` a LIVE process whose image / command line contains `needle`?
///
/// `Some(true)`/`Some(false)` are definite answers; `None` means the query tool
/// itself did not run, so the answer is unknown. Callers must treat `None` as
/// "leave it alone" — we never signal a process we cannot positively identify.
#[cfg(not(target_os = "windows"))]
fn process_matches(pid: u32, needle: &str) -> Option<bool> {
    // `ps` exits non-zero with empty stdout when the PID is gone; that is a
    // definite "no", not a failure, so only a spawn error yields `None`.
    let out = std::process::Command::new("ps")
        .args(["-o", "command=", "-p", &pid.to_string()])
        .output()
        .ok()?;
    Some(String::from_utf8_lossy(&out.stdout).contains(needle))
}

#[cfg(target_os = "windows")]
fn process_matches(pid: u32, needle: &str) -> Option<bool> {
    use std::os::windows::process::CommandExt;
    let out = std::process::Command::new("tasklist")
        .args(["/FI", &format!("PID eq {}", pid), "/FO", "CSV", "/NH"])
        .creation_flags(0x08000000) // CREATE_NO_WINDOW
        .output()
        .ok()?;
    Some(tasklist_matches(
        &String::from_utf8_lossy(&out.stdout),
        needle,
    ))
}

/// Reap sidecars left behind by a PRIOR crash — and only those.
///
/// Two independent checks must BOTH pass before anything is signalled:
///
/// 1. **The owning app instance is gone.** The app PID in the file name must no
///    longer be a live process running this same executable. If it is, another
///    FinanceTracker window is using that backend right now, so both the
///    process and its record are left untouched. (Without this, launching a
///    second instance killed the first one's backend: the "is it still our
///    binary" check below is just as true for a LIVE sidecar as for an orphan.)
/// 2. **The recorded PID is still our backend binary**, so a PID recycled by
///    the OS — guaranteed after a reboot, routine on Windows — is never
///    touched. This check previously existed only on Unix; the Windows path
///    went straight to `taskkill /T /F` on whatever happened to own the PID.
///
/// Anything that cannot be positively determined is left alone. A `backend.pid`
/// from an older build carries no owner, so it can only be identity-checked;
/// that is a one-off at upgrade time and still never touches a foreign process.
fn reap_stale_sidecars(app_data_dir: &std::path::Path) {
    let me = std::process::id();
    let own_name = own_process_name();
    let Ok(entries) = std::fs::read_dir(app_data_dir) else {
        return;
    };
    for entry in entries.flatten() {
        let file_name = entry.file_name().to_string_lossy().into_owned();
        let Some(owner) = pid_file_owner(&file_name) else {
            continue;
        };
        if let PidFileOwner::Instance(owner_pid) = owner {
            // Only a DEFINITE "that app process is gone" lets us proceed; an
            // unknown answer (`None`) keeps our hands off.
            let owner_gone = owner_pid == me
                || match own_name.as_deref() {
                    Some(name) => process_matches(owner_pid, name) == Some(false),
                    None => false,
                };
            if !owner_gone {
                continue;
            }
        }
        let path = entry.path();
        let text = std::fs::read_to_string(&path).unwrap_or_default();
        let _ = std::fs::remove_file(&path);
        let Ok(pid) = text.trim().parse::<u32>() else {
            continue;
        };
        if process_matches(pid, "financetracker-backend") != Some(true) {
            continue;
        }
        eprintln!(
            "[sidecar] reaping orphaned backend from a previous run (pid {})",
            pid
        );
        terminate_tree(pid);
    }
}

/// Terminate `pid` AND its descendants: graceful first, then forced.
///
/// The descendant list is snapshotted BEFORE the parent dies — once it exits,
/// orphans reparent to init and `pgrep -P` can no longer find them.
fn terminate_tree(pid: u32) {
    #[cfg(not(target_os = "windows"))]
    {
        let mut tree = vec![pid];
        tree.extend(descendants_of(pid));

        for p in &tree {
            let _ = std::process::Command::new("kill")
                .args(["-TERM", &p.to_string()])
                .output();
        }
        // Give the backend's lifespan handler time to stop the scheduler,
        // dispose DB connections and checkpoint the SQLite WAL.
        std::thread::sleep(Duration::from_millis(1500));
        for p in &tree {
            let _ = std::process::Command::new("kill")
                .args(["-KILL", &p.to_string()])
                .output();
        }
    }
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        // /T kills the whole tree rooted at this PID; /F forces it.
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T"])
            .creation_flags(0x08000000)
            .output();
        std::thread::sleep(Duration::from_millis(1500));
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(0x08000000)
            .output();
    }
}

fn kill_sidecar(state: &AppState) {
    // A poisoned mutex must NOT skip the kill — that would leak the sidecar
    // process (and its port) past app exit. Recover the inner value instead:
    // the Option<CommandChild> is valid regardless of where the poisoning
    // panic happened.
    let mut guard = state
        .sidecar_child
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    if let Some(child) = guard.take() {
        let pid = child.pid();
        // Terminate the whole tree, not just the tracked PID. The sidecar is a
        // PyInstaller onefile binary: the tracked process is the bootloader and
        // the process that actually BINDS THE PORT is its child. SIGTERM is
        // forwarded by the bootloader, but the SIGKILL fallback is not — so
        // killing only the parent orphaned the child and leaked the port
        // (reproduced: parent killed, child kept serving on 8420).
        terminate_tree(pid);
        let _ = child.kill(); // reap the handle itself if anything remains
    }

    // Co-running safety (HARD REQUIREMENT): we deliberately do NOT perform any
    // name-based sweep here (no `taskkill /IM financetracker-backend.exe`, no
    // `pkill -f financetracker-backend`). Killing by image name or argv
    // substring would reap EVERY matching process — a second running instance
    // of this app, or an unrelated process whose command line merely contains
    // the string (e.g. `tail -f financetracker-backend.log`). The
    // graceful-then-forced `child.kill()` above already reaps THIS instance's
    // own sidecar, which is the only process we are entitled to stop.
    //
    // Safely reaping a truly-orphaned sidecar left by a PRIOR crash would
    // require spawning it in its own process group / Windows Job Object and
    // killing by that group id (so the scope is provably this instance only).
    // Until that tracking exists we accept a rare orphan rather than ever risk
    // terminating another process.
}

/// Build the self-healing "still starting up" page injected when the backend
/// misses its 120s deadline.
///
/// It polls `/health` and, when the backend answers, RELOADS the bundled origin
/// so the real UI comes back.
///
/// It must NOT navigate to `http://<host>:{port}/`. That is exactly the
/// blank-window trap documented in `run()` (WebKit loads that page's assets but
/// never runs its JavaScript inside the Tauri webview), and CI-built releases do
/// not bundle `backend/static` at all, so the same URL renders a raw
/// `{"detail":"Not Found"}`. Reloading keeps us on the bundled origin, where the
/// app re-discovers the port over IPC (`get_api_port`) — which is also why the
/// poll asks IPC for the CURRENT port each time instead of trusting the baked-in
/// one.
///
/// The poll uses 127.0.0.1, not "localhost": the backend binds IPv4 only, so on
/// a host that resolves localhost to ::1 first the retry would never succeed
/// (the same reason `wait_for_backend` uses the literal address).
fn recovery_script(port: u16) -> String {
    format!(
            "document.body.innerHTML = '<div style=\"display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui;color:#888;background:#09090b\"><div style=\"text-align:center\"><h2 style=\"color:#fafafa\">Still starting up\\u2026</h2><p id=\"ft-status\">This is taking longer than usual. On the first launch, security software often scans the app before it can start \\u2014 that is normal and only happens once.</p><button onclick=\"window.__ftCheck&&window.__ftCheck()\" style=\"margin-top:16px;padding:8px 24px;background:#6366f1;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:14px\">Retry now</button></div></div>';\
            window.__ftPort = {port};\
            window.__ftCheck = function() {{\
                var internals = window.__TAURI_INTERNALS__;\
                var ask = (internals && internals.invoke)\
                    ? Promise.resolve(internals.invoke('get_api_port')).catch(function() {{ return window.__ftPort; }})\
                    : Promise.resolve(window.__ftPort);\
                ask.then(function(p) {{\
                    if (p) {{ window.__ftPort = p; }}\
                    return fetch('http://127.0.0.1:' + window.__ftPort + '/health');\
                }}).then(function(r) {{\
                    if (!r.ok) {{ throw new Error('backend not ready'); }}\
                    clearInterval(window.__ftTimer);\
                    window.location.reload();\
                }}).catch(function() {{\
                    var el = document.getElementById('ft-status');\
                    if (el) {{ el.textContent = 'Server not reachable yet \\u2014 retrying\\u2026 (' + new Date().toLocaleTimeString() + ')'; }}\
                }});\
            }};\
            window.__ftTimer = setInterval(window.__ftCheck, 2000);",
            port = port
    )
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            let app_data_dir = app
                .path()
                .app_data_dir()
                .expect("failed to resolve app data dir");
            std::fs::create_dir_all(&app_data_dir).ok();

            // A crash or force-quit can leave last run's backend alive, still
            // holding its port. Reap it now — strictly by a PID we recorded
            // ourselves, only after confirming it is still our binary, and only
            // when the instance that recorded it is no longer running (so a
            // second window never kills the first one's backend).
            reap_stale_sidecars(&app_data_dir);
            let db_path = app_data_dir.join("finance.db");

            let port = find_port();
            println!("Backend port: {}, DB: {:?}", port, db_path);

            // TOCTOU guard: find_port() releases the port immediately, and the
            // onefile sidecar takes 40-120s to extract before uvicorn binds —
            // another process can grab the port in that window. The backend
            // self-heals (auto-advances to the next free port and prints
            // "[startup] Port {req} is in use — serving on free port {port}
            // instead."), so the ACTUAL port lives in this shared cell: the
            // stdout pump updates it, and the health poll / navigation /
            // get_api_port all read it fresh instead of trusting `port`.
            let api_port = Arc::new(AtomicU16::new(port));

            let is_first_launch = !db_path.exists();
            println!("DB path: {:?}, exists: {}, first_launch: {}", db_path, db_path.exists(), is_first_launch);

            // Always pass --seed. The seed function checks if demo user exists
            // and skips if already present. This ensures the demo user is always
            // available even if the DB was created without seeding.
            let mut sidecar_args = vec![
                "--port".to_string(),
                port.to_string(),
                "--host".to_string(),
                "127.0.0.1".to_string(),
                "--db-path".to_string(),
                db_path.to_string_lossy().to_string(),
            ];
            sidecar_args.push("--seed".to_string());

            let sidecar_result = app
                .shell()
                .sidecar("financetracker-backend")
                .map(|cmd| cmd.args(&sidecar_args))
                .and_then(|cmd| cmd.spawn().map_err(|e| e.into()));

            // On spawn failure we keep the error so we can surface a clear
            // message in the webview instead of spinning on /health forever
            // (there is no backend to reach, so the poll would never succeed).
            let (child, spawn_error): (Option<CommandChild>, Option<String>) = match sidecar_result {
                Ok((mut rx, child)) => {
                    // Record the PID so a future launch can reap this process
                    // if we never get to run kill_sidecar (crash / force-quit).
                    let _ =
                        std::fs::write(sidecar_pid_file(&app_data_dir), child.pid().to_string());
                    let pump_port = Arc::clone(&api_port);
                    tauri::async_runtime::spawn(async move {
                        use tauri_plugin_shell::process::CommandEvent;
                        while let Some(event) = rx.recv().await {
                            match event {
                                CommandEvent::Stdout(line) => {
                                    let text = String::from_utf8_lossy(&line);
                                    println!("[backend] {}", text);
                                    // The backend announces a port move as:
                                    //   "[startup] Port {req} is in use — serving
                                    //    on free port {port} instead."
                                    // Follow it: publish the real port so the
                                    // health poll and navigation catch up.
                                    if let Some(rest) =
                                        text.split("serving on free port ").nth(1)
                                    {
                                        let digits: String = rest
                                            .chars()
                                            .take_while(|c| c.is_ascii_digit())
                                            .collect();
                                        if let Ok(new_port) = digits.parse::<u16>() {
                                            let old =
                                                pump_port.swap(new_port, Ordering::SeqCst);
                                            if old != new_port {
                                                println!(
                                                    "[desktop] port {} was taken during startup; following backend to port {}",
                                                    old, new_port
                                                );
                                            }
                                        }
                                    }
                                }
                                CommandEvent::Stderr(line) => {
                                    eprintln!("[backend] {}", String::from_utf8_lossy(&line));
                                }
                                CommandEvent::Terminated(payload) => {
                                    eprintln!("[backend] terminated: {:?}", payload.code);
                                    break;
                                }
                                _ => {}
                            }
                        }
                    });
                    (Some(child), None)
                }
                Err(e) => {
                    eprintln!("ERROR: Failed to spawn backend sidecar: {}", e);
                    (None, Some(e.to_string()))
                }
            };

            app.manage(AppState {
                api_port: Arc::clone(&api_port),
                sidecar_child: Mutex::new(child),
            });

            // Wait for backend to be ready, then navigate the window to it.
            // This makes the frontend load from http://localhost:{port} (same origin
            // as the API), which avoids the mixed-content blocking issue on Windows
            // where Tauri serves from https://tauri.localhost but API is HTTP.
            // The #ftport= hash tells the frontend which port the API is on
            // (after navigation the Tauri IPC bridge is no longer available).
            let window = app.get_webview_window("main").expect("no main window");

            // Closing the window must fully quit the app so the backend sidecar
            // is shut down and its port released. On macOS the default is to keep
            // the app alive when the window closes, which would leave the local
            // server running — so exit explicitly on close.
            let exit_handle = app.handle().clone();
            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { .. } = event {
                    exit_handle.exit(0);
                }
            });

            // The window starts at about:blank — inject a loading screen
            // IMMEDIATELY. The onefile sidecar can take 40-120s to boot
            // (PyInstaller extraction + Gatekeeper/AV scan on first run);
            // without feedback users see a blank window and assume the app
            // is broken.
            // NO loading-screen injection here. It used to do
            // `document.documentElement.innerHTML = ...`, which DESTROYS the
            // document: on `about:blank` WebKit rendered nothing at all, and
            // once the real UI was bundled it wiped the app's own DOM — either
            // way the window stayed blank. The bundled frontend renders its own
            // UI immediately, which is better than a fake splash anyway.

            // If the sidecar failed to spawn there is no backend to reach, so
            // polling /health would spin forever behind the loading screen.
            // Surface a clear, actionable error instead. (The detailed cause is
            // already logged to stderr above.)
            if spawn_error.is_some() {
                let _ = window.eval(
                    "document.body.innerHTML = '<div style=\"display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui;color:#888;background:#09090b\"><div style=\"text-align:center;max-width:460px;padding:24px\"><h2 style=\"color:#fafafa;margin:0 0 12px\">Could not start the local server</h2><p>FinanceTracker\\u2019s built-in server could not start on this computer. Try reopening the app first. If it keeps happening, allow FinanceTracker through your antivirus or firewall, then reinstall. The application logs have the details.</p></div></div>';"
                );
            } else {
            let nav_port = Arc::clone(&api_port);
            std::thread::spawn(move || {
                // Onefile PyInstaller extracts the whole bundle on every launch;
                // a cold start (or an antivirus scan on Windows) can take well
                // over 30s, so wait generously before declaring failure.
                //
                // The URL (including the #ftport= hash) is built AFTER the wait
                // from the CURRENT port value: if the backend had to move ports
                // during extraction, we navigate to where it actually is.
                if wait_for_backend(&nav_port, 120) {
                    let port = nav_port.load(Ordering::SeqCst);
                    // 127.0.0.1, not "localhost": the backend binds IPv4 only,
                    // and the literal address avoids any resolver/ATS detour.
                    let url = format!("http://127.0.0.1:{}/#ftport={}", port, port);
                    println!("Backend ready -- navigating window to {}", url);
                    // Use the NATIVE navigation API rather than injecting
                    // `location.replace` via eval(). On an `about:blank` page the
                    // injected script silently did nothing — the webview issued
                    // no request at all and the window stayed blank — so errors
                    // here are logged instead of being discarded.
                    // The UI is served from the BUNDLED frontend
                    // (tauri://localhost) — see frontendDist. We do NOT
                    // navigate the window to the backend's http origin:
                    // WebKit loads that page's assets but never executes its
                    // JavaScript inside the Tauri webview (verified — the same
                    // URL runs fine in Safari), leaving a blank window. The
                    // frontend discovers the API port over IPC (get_api_port)
                    // instead.
                    println!("Backend ready on port {} -- UI served from bundle", port);
                } else {
                    eprintln!("WARNING: Backend did not respond within 120 seconds");
                    let port = nav_port.load(Ordering::SeqCst);
                    let recovery = recovery_script(port);
                    let _ = window.eval(&recovery);
                }
            });
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_api_port])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<AppState>() {
                kill_sidecar(&state);
            }
            // Clean shutdown: drop the PID record so the next launch has
            // nothing stale to reap.
            if let Ok(dir) = app_handle.path().app_data_dir() {
                // Our own per-instance record only — a co-running instance's
                // record must survive our exit.
                let _ = std::fs::remove_file(sidecar_pid_file(&dir));
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recovery_page_never_navigates_to_the_backend_origin() {
        let js = recovery_script(8423);
        // Navigating the webview to the backend's http origin is the documented
        // blank-window trap, and in CI-built releases that URL is a bare
        // {"detail":"Not Found"} because backend/static is not bundled.
        assert!(
            !js.contains("location.replace"),
            "must not navigate away: {}",
            js
        );
        assert!(
            !js.contains("ftport="),
            "the #ftport hash only makes sense on the backend origin"
        );
        // Coming back to the bundled origin is the only safe recovery.
        assert!(js.contains("window.location.reload()"));
        assert!(js.contains("clearInterval(window.__ftTimer)"));
    }

    #[test]
    fn recovery_page_polls_ipv4_loopback_on_the_live_port() {
        let js = recovery_script(8423);
        // The backend binds IPv4 only — "localhost" can resolve to ::1 first.
        assert!(js.contains("http://127.0.0.1:"), "{}", js);
        assert!(!js.contains("localhost"), "{}", js);
        // The baked port seeds the poll...
        assert!(js.contains("window.__ftPort = 8423;"));
        // ...but each attempt re-asks the shell, so a port move during the slow
        // startup we are recovering from is followed rather than missed.
        assert!(js.contains("invoke('get_api_port')"));
    }

    #[test]
    fn pid_file_owner_recognises_per_instance_records() {
        assert_eq!(
            pid_file_owner("backend-1234.pid"),
            Some(PidFileOwner::Instance(1234))
        );
        assert_eq!(pid_file_owner("backend.pid"), Some(PidFileOwner::Legacy));
    }

    #[test]
    fn pid_file_owner_ignores_unrelated_files() {
        // Anything that is not one of our records must be skipped outright —
        // the reaper never opens, deletes or signals on a foreign file.
        for name in [
            "finance.db",
            "backend.pid.bak",
            "backend-.pid",
            "backend-abc.pid",
            "backend-12x.pid",
            "other-1234.pid",
        ] {
            assert_eq!(
                pid_file_owner(name),
                None,
                "{} should not be a pid record",
                name
            );
        }
    }

    #[test]
    fn sidecar_pid_file_is_scoped_to_this_process() {
        let path = sidecar_pid_file(std::path::Path::new("/tmp/appdata"));
        let name = path.file_name().unwrap().to_string_lossy().into_owned();
        assert_eq!(name, format!("backend-{}.pid", std::process::id()));
        // ...and it round-trips through the classifier as OUR record, which is
        // what keeps a second instance from reaping the first one's backend.
        assert_eq!(
            pid_file_owner(&name),
            Some(PidFileOwner::Instance(std::process::id()))
        );
    }

    #[test]
    fn tasklist_matches_reads_a_live_process() {
        let out = "\"financetracker-backend.exe\",\"7412\",\"Console\",\"1\",\"120,004 K\"\r\n";
        assert!(tasklist_matches(out, "financetracker-backend"));
        // Case-insensitive: Windows image names are.
        assert!(tasklist_matches(out, "FinanceTracker-Backend.exe"));
        // A different image on that PID must NOT be treated as ours.
        assert!(!tasklist_matches(out, "FinanceTracker.exe"));
    }

    #[test]
    fn tasklist_matches_rejects_the_no_such_pid_banner() {
        // The banner names the filter, so a naive `contains` on a needle that
        // appears in it would force-kill an unrelated recycled PID.
        let out = "INFO: No tasks are running which match the specified criteria.\r\n";
        assert!(!tasklist_matches(out, "financetracker-backend"));
        assert!(!tasklist_matches(out, "criteria"));
    }

    #[test]
    fn process_matches_is_definite_about_this_process_and_a_dead_pid() {
        // Our own PID is alive; a PID that is certainly not a process is not.
        assert_eq!(
            process_matches(std::process::id(), "definitely-not-this-binary"),
            Some(false)
        );
        // PID 0 is never a normal user process on any platform we ship.
        assert_eq!(process_matches(0, "financetracker-backend"), Some(false));
        // ...and the positive direction: our own executable name DOES match our
        // own PID. This is the exact check that decides whether a recorded
        // owner instance is still running.
        let name = own_process_name().expect("current_exe should resolve in tests");
        assert_eq!(process_matches(std::process::id(), &name), Some(true));
    }
}
