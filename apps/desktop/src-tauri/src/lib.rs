use std::net::TcpListener;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

struct AppState {
    api_port: u16,
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
fn wait_for_backend(port: u16, timeout_secs: u64) -> bool {
    let url = format!("http://127.0.0.1:{}/health", port);
    let start = Instant::now();
    let timeout = Duration::from_secs(timeout_secs);
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .expect("failed to build HTTP client");

    while start.elapsed() < timeout {
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
    state.api_port
}

fn kill_sidecar(state: &AppState) {
    if let Ok(mut guard) = state.sidecar_child.lock() {
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
    }

    // Belt-and-suspenders: sweep any orphaned sidecar the CommandChild lost
    // track of (e.g. after a prior crash), so no backend is left holding a port.
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/T", "/IM", "financetracker-backend.exe"])
            .creation_flags(0x08000000)
            .output();
    }

    #[cfg(not(target_os = "windows"))]
    {
        let _ = std::process::Command::new("pkill")
            .args(["-f", "financetracker-backend"])
            .output();
    }
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

            let child = match sidecar_result {
                Ok((mut rx, child)) => {
                    tauri::async_runtime::spawn(async move {
                        use tauri_plugin_shell::process::CommandEvent;
                        while let Some(event) = rx.recv().await {
                            match event {
                                CommandEvent::Stdout(line) => {
                                    println!("[backend] {}", String::from_utf8_lossy(&line));
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
                    Some(child)
                }
                Err(e) => {
                    eprintln!("WARNING: Failed to spawn sidecar: {}", e);
                    None
                }
            };

            app.manage(AppState {
                api_port: port,
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

            std::thread::spawn(move || {
                let url = format!("http://localhost:{}/#ftport={}", port, port);
                // Onefile PyInstaller extracts the whole bundle on every launch;
                // a cold start (or an antivirus scan on Windows) can take well
                // over 30s, so wait generously before declaring failure.
                if wait_for_backend(port, 120) {
                    println!("Backend ready -- navigating window to {}", url);
                    let _ = window.eval(&format!("window.location.replace('{}');", url));
                } else {
                    eprintln!("WARNING: Backend did not respond within 120 seconds");
                    // Self-healing error page: keeps polling /health in the
                    // webview and navigates as soon as the backend comes up —
                    // a plain reload would return to the static shell with no
                    // monitor thread left to navigate, stranding the user.
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
