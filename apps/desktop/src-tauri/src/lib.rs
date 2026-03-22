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

/// Try to bind to preferred ports in order. Use port 8000 by default
/// so the frontend doesn't need dynamic port discovery.
fn find_port() -> u16 {
    for port in [8000, 8001, 8002, 8003, 8004, 8005] {
        if TcpListener::bind(format!("127.0.0.1:{}", port)).is_ok() {
            return port;
        }
    }
    // All preferred ports taken — use random as last resort
    TcpListener::bind("127.0.0.1:0")
        .expect("failed to bind to any port")
        .local_addr()
        .expect("failed to get local addr")
        .port()
}

/// Wait for the backend health endpoint to respond (up to timeout_secs).
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

/// Kill the sidecar backend process
fn kill_sidecar(state: &AppState) {
    if let Ok(mut guard) = state.sidecar_child.lock() {
        if let Some(child) = guard.take() {
            let _ = child.kill();
            println!("Backend sidecar killed");
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            // Determine app data directory for the SQLite database
            let app_data_dir = app
                .path()
                .app_data_dir()
                .expect("failed to resolve app data dir");
            std::fs::create_dir_all(&app_data_dir).ok();
            let db_path = app_data_dir.join("finance.db");

            // Use port 8000 by default (matches frontend fallback)
            let port = find_port();
            println!("Starting backend sidecar on port {} with db: {:?}", port, db_path);

            // Seed demo user on first launch (when no DB exists yet)
            let is_first_launch = !db_path.exists();

            // Spawn the sidecar process
            let mut sidecar_args = vec![
                "--port".to_string(),
                port.to_string(),
                "--host".to_string(),
                "127.0.0.1".to_string(),
                "--db-path".to_string(),
                db_path.to_string_lossy().to_string(),
            ];
            if is_first_launch {
                sidecar_args.push("--seed".to_string());
                println!("First launch detected -- will seed demo user");
            }

            // Try to spawn the sidecar -- don't crash the app if it fails
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
                                    eprintln!(
                                        "[backend] terminated: code={:?} signal={:?}",
                                        payload.code, payload.signal
                                    );
                                    break;
                                }
                                _ => {}
                            }
                        }
                    });
                    Some(child)
                }
                Err(e) => {
                    eprintln!("WARNING: Failed to spawn backend sidecar: {}", e);
                    None
                }
            };

            // Inject the API port into the window via eval
            // Also set it as a global so the frontend can read it immediately
            if let Some(window) = app.get_webview_window("main") {
                let script = format!(
                    "window.__FINANCETRACKER_API_PORT__ = {}; \
                     console.log('[tauri] API port set to {}');",
                    port, port
                );
                let _ = window.eval(&script);
            }

            // Wait for backend in a background thread (don't block UI)
            std::thread::spawn(move || {
                if wait_for_backend(port, 30) {
                    println!("Backend is ready on port {}", port);
                } else {
                    eprintln!("WARNING: Backend did not respond within 30 seconds");
                }
            });

            // Store state
            app.manage(AppState {
                api_port: port,
                sidecar_child: Mutex::new(child),
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_api_port])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // Use run callback to handle app exit — this is more reliable than
    // on_window_event for killing the sidecar on all platforms
    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<AppState>() {
                kill_sidecar(&state);
            }
        }
    });
}
