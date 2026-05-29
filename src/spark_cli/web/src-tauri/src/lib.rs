// Spark desktop shell.
//
// The Python backend is frozen with PyInstaller in --onedir mode and shipped
// as a Tauri bundle *resource* at Contents/Resources/spark-server/. We spawn
// the inner `spark-server` executable on launch, wait for it to come online,
// then navigate the window to it. The process is killed on app exit.
//
// --onedir (vs --onefile) is deliberate: no per-launch temp unpack (fast cold
// start) and no bootloader re-exec child, so killing the spawned process
// actually stops the server (no orphaned process serving on port 9119).
//
// Readiness polling + navigation happen *here* (Rust), not in the loading
// page's JS: a `fetch()` from the tauri://localhost secure context to the
// http://127.0.0.1 server is blocked as mixed content. A top-level navigation
// to the http URL is fine, so Rust polls the TCP port and then navigates.

use std::net::TcpStream;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{Manager, RunEvent, State};

/// Holds the running backend process so we can kill it on exit.
struct Sidecar(Mutex<Option<Child>>);

const SIDECAR_PORT: u16 = 9119;
const READY_TIMEOUT_SECS: u64 = 120;

/// Block until the backend is accepting connections, then point the window at
/// it. Runs on a background thread so the UI (loading page) stays responsive.
fn wait_and_navigate(app: tauri::AppHandle) {
    let addr = std::net::SocketAddr::from(([127, 0, 0, 1], SIDECAR_PORT));
    let deadline = std::time::Instant::now() + Duration::from_secs(READY_TIMEOUT_SECS);
    let url: tauri::Url = format!("http://127.0.0.1:{SIDECAR_PORT}/")
        .parse()
        .expect("valid sidecar URL");

    while std::time::Instant::now() < deadline {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(500)).is_ok() {
            if let Some(window) = app.get_webview_window("main") {
                if let Err(e) = window.navigate(url) {
                    eprintln!("[spark] navigate failed: {e}");
                }
            }
            return;
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    eprintln!("[spark] backend did not come online within {READY_TIMEOUT_SECS}s");
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Sidecar(Mutex::new(None)))
        .setup(|app| {
            // Resource layout: Contents/Resources/spark-server/spark-server
            let exe = app
                .path()
                .resource_dir()?
                .join("spark-server")
                .join("spark-server");

            if exe.exists() {
                // SPARK_DESKTOP tells the backend it's running as the local
                // desktop sidecar, so it may open external URLs (OAuth pages)
                // in the user's browser via the OS.
                match Command::new(&exe)
                    .arg(SIDECAR_PORT.to_string())
                    .env("SPARK_DESKTOP", "1")
                    .spawn()
                {
                    Ok(child) => {
                        eprintln!("[spark] sidecar spawned (pid {}) from {:?}", child.id(), exe);
                        let state: State<Sidecar> = app.state();
                        *state.0.lock().unwrap() = Some(child);
                    }
                    Err(e) => eprintln!("[spark] failed to spawn sidecar: {e}"),
                }
            } else {
                // Dev mode: no frozen binary staged. Expect the user to run
                // `spark dashboard --port 9119` manually; we still poll and
                // navigate once that server is up.
                eprintln!(
                    "[spark] sidecar not found at {:?} — assuming dev mode (run `spark dashboard` manually)",
                    exe
                );
            }

            // Poll for readiness + navigate, off the main thread.
            let handle = app.handle().clone();
            std::thread::spawn(move || wait_and_navigate(handle));

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Spark application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<Sidecar>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        eprintln!("[spark] stopping sidecar (pid {})", child.id());
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}
