use std::net::TcpListener;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

struct AppState {
    api_port: u16,
    #[allow(dead_code)]
    sidecar_child: Mutex<Option<CommandChild>>,
}

/// Find a free TCP port by binding to port 0.
fn find_free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("failed to bind to a free port")
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
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

            // Find a free port for the backend
            let port = find_free_port();
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
                    // Log sidecar stdout/stderr in a background thread
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
                                        "[backend] process terminated with code: {:?}, signal: {:?}",
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
                    eprintln!("The app will open but API calls will fail.");
                    None
                }
            };

            // Create the main window IMMEDIATELY (don't wait for backend)
            // This ensures the user sees the app window right away.
            let init_script = format!(
                "window.__FINANCETRACKER_API_PORT__ = {};",
                port
            );

            let _window = WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::default(),
            )
            .title("FinanceTracker")
            .inner_size(1280.0, 800.0)
            .min_inner_size(900.0, 600.0)
            .resizable(true)
            .fullscreen(false)
            .decorations(true)
            .initialization_script(&init_script)
            .build()
            .expect("failed to create main window");

            // Wait for backend in a background thread (don't block the UI)
            std::thread::spawn(move || {
                println!("Waiting for backend to start...");
                if wait_for_backend(port, 30) {
                    println!("Backend is ready on port {}", port);
                } else {
                    eprintln!("WARNING: Backend did not respond within 30 seconds");
                    eprintln!("Try running the sidecar binary manually to see errors.");
                }
            });

            // Store state for the get_api_port command
            app.manage(AppState {
                api_port: port,
                sidecar_child: Mutex::new(child),
            });

            #[cfg(debug_assertions)]
            {
                _window.open_devtools();
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Kill the sidecar when the window is destroyed
                if let Some(state) = window.try_state::<AppState>() {
                    if let Ok(mut guard) = state.sidecar_child.lock() {
                        if let Some(child) = guard.take() {
                            let _ = child.kill();
                            println!("Backend sidecar killed on window close");
                        }
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![get_api_port])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
