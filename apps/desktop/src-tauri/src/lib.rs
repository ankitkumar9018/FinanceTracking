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
fn find_port() -> u16 {
    for port in [8000, 8001, 8002, 8003, 8004, 8005] {
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
            let _ = child.kill();
        }
    }

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
            }

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
            let window = app.get_webview_window("main").expect("no main window");
            std::thread::spawn(move || {
                if wait_for_backend(port, 30) {
                    println!("Backend ready -- navigating window to http://localhost:{}", port);
                    let url = format!("http://localhost:{}", port);
                    let _ = window.eval(&format!(
                        "window.location.replace('{}');",
                        url
                    ));
                } else {
                    eprintln!("WARNING: Backend did not respond within 30 seconds");
                    let _ = window.eval(
                        "document.body.innerHTML = '<div style=\"display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui;color:#888\"><div style=\"text-align:center\"><h2>Backend failed to start</h2><p>Try running financetracker-backend.exe manually</p></div></div>';"
                    );
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
