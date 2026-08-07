use std::net::TcpListener;
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

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
        // Graceful first: ask the backend to shut down so its lifespan
        // handler runs — stops the scheduler, disposes DB connections, and
        // checkpoints the SQLite WAL. Then hard-kill only if it lingers.
        #[cfg(not(target_os = "windows"))]
        {
            let _ = std::process::Command::new("kill")
                .args(["-TERM", &pid.to_string()])
                .output();
            std::thread::sleep(Duration::from_millis(1500));
        }
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/T"])
                .creation_flags(0x08000000)
                .output();
            std::thread::sleep(Duration::from_millis(1500));
        }
        let _ = child.kill(); // SIGKILL / force fallback if still alive
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
            let _ = window.eval(
                "document.documentElement.innerHTML = '<head><style>body{margin:0;font-family:system-ui;background:#09090b;color:#fafafa;display:flex;align-items:center;justify-content:center;height:100vh}.sp{width:40px;height:40px;border:3px solid #333;border-top-color:#6366f1;border-radius:50%;animation:r 1s linear infinite;margin:0 auto 16px}@keyframes r{to{transform:rotate(360deg)}}p{color:#888;font-size:14px}</style></head><body><div style=\"text-align:center\"><div class=\"sp\"></div><h2 style=\"margin:0 0 8px\">FinanceTracker</h2><p>Starting local server\\u2026<br>First launch can take a minute or two.</p></div></body>';"
            );

            // If the sidecar failed to spawn there is no backend to reach, so
            // polling /health would spin forever behind the loading screen.
            // Surface a clear, actionable error instead. (The detailed cause is
            // already logged to stderr above.)
            if spawn_error.is_some() {
                let _ = window.eval(
                    "document.body.innerHTML = '<div style=\"display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui;color:#888;background:#09090b\"><div style=\"text-align:center;max-width:460px;padding:24px\"><h2 style=\"color:#fafafa;margin:0 0 12px\">Could not start the local server</h2><p>The FinanceTracker backend failed to launch on this machine. Please reinstall or reopen the app; if it keeps happening, check the application logs.</p></div></div>';"
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
                    let url = format!("http://localhost:{}/#ftport={}", port, port);
                    println!("Backend ready -- navigating window to {}", url);
                    let _ = window.eval(&format!("window.location.replace('{}');", url));
                } else {
                    eprintln!("WARNING: Backend did not respond within 120 seconds");
                    // Self-healing error page: keeps polling /health in the
                    // webview and navigates as soon as the backend comes up —
                    // a plain reload would return to the static shell with no
                    // monitor thread left to navigate, stranding the user.
                    // Baked with the LATEST known port (the backend may have
                    // announced a move while we were waiting).
                    let port = nav_port.load(Ordering::SeqCst);
                    let recovery = format!(
                        "document.body.innerHTML = '<div style=\"display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui;color:#888;background:#09090b\"><div style=\"text-align:center\"><h2 style=\"color:#fafafa\">Backend is taking longer than expected</h2><p id=\"ft-status\">Still trying to reach the local server\\u2026</p><button onclick=\"window.__ftCheck&&window.__ftCheck()\" style=\"margin-top:16px;padding:8px 24px;background:#6366f1;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:14px\">Retry now</button></div></div>';\
                        window.__ftCheck = function() {{\
                            fetch('http://localhost:{port}/health').then(function(r) {{\
                                if (r.ok) {{ window.location.replace('http://localhost:{port}/#ftport={port}'); }}\
                            }}).catch(function() {{\
                                var el = document.getElementById('ft-status');\
                                if (el) {{ el.textContent = 'Server not reachable yet \\u2014 retrying\\u2026 (' + new Date().toLocaleTimeString() + ')'; }}\
                            }});\
                        }};\
                        window.__ftTimer = setInterval(window.__ftCheck, 2000);",
                        port = port
                    );
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
        }
    });
}
