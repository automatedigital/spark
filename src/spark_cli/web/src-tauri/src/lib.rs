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
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{
    webview::WebviewBuilder, LogicalPosition, LogicalSize, Manager, RunEvent, State, WebviewUrl,
};

/// Label of the embedded native preview webview (overlaid on the React panel).
const PREVIEW_LABEL: &str = "spark-preview";

/// Derive a stable 16-byte WKWebView data-store id from the workspace slug, so
/// each workspace gets its own partitioned persistent cookie/storage jar (no
/// cross-project credential leakage).
fn data_store_id(slug: &str) -> [u8; 16] {
    use std::hash::{Hash, Hasher};
    let mut out = [0u8; 16];
    for (i, salt) in [0x9e3779b97f4a7c15u64, 0xc2b2ae3d27d4eb4fu64].iter().enumerate() {
        let mut h = std::collections::hash_map::DefaultHasher::new();
        salt.hash(&mut h);
        slug.hash(&mut h);
        out[i * 8..i * 8 + 8].copy_from_slice(&h.finish().to_le_bytes());
    }
    out
}

/// JS injected into the native preview webview to forward console + network
/// activity to the backend log stream (the external webview has no Tauri IPC,
/// so it POSTs straight to the local server, which re-emits over the preview SSE).
fn preview_log_script(slug: &str) -> String {
    format!(
        r#"(function(){{
  var EP = 'http://127.0.0.1:{port}/api/workspace/projects/{slug}/preview/stream/log';
  function send(text, stream){{
    try {{ fetch(EP, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{text:String(text).slice(0,2000), stream:stream}})}}); }} catch(e){{}}
  }}
  ['log','info','warn','error'].forEach(function(k){{
    var orig = console[k];
    console[k] = function(){{ try{{ send(Array.prototype.join.call(arguments,' '), k==='error'?'error':'console'); }}catch(e){{}} return orig.apply(console, arguments); }};
  }});
  window.addEventListener('error', function(e){{ send(e.message, 'error'); }});
  try {{
    new PerformanceObserver(function(list){{
      list.getEntries().forEach(function(en){{ send((en.responseStatus||'') + ' ' + en.name, 'network'); }});
    }}).observe({{type:'resource', buffered:true}});
  }} catch(e){{}}
}})();"#,
        port = SIDECAR_PORT,
        slug = slug,
    )
}

/// Create (or navigate) a native child webview overlaying the preview panel's
/// bounds. A real WebView renders external sites that an iframe can't (no
/// `X-Frame-Options`/CSP framing limits) and keeps a persistent cookie store.
#[tauri::command]
fn preview_create(
    app: tauri::AppHandle,
    slug: String,
    url: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    persistent: bool,
) -> Result<(), String> {
    let parsed: tauri::Url = url.parse().map_err(|e| format!("bad url: {e}"))?;

    // Already exists → just navigate + reposition.
    if let Some(webview) = app.get_webview(PREVIEW_LABEL) {
        webview.navigate(parsed).map_err(|e| e.to_string())?;
        webview
            .set_position(LogicalPosition::new(x, y))
            .map_err(|e| e.to_string())?;
        webview
            .set_size(LogicalSize::new(width, height))
            .map_err(|e| e.to_string())?;
        return Ok(());
    }

    let window = app
        .get_window("main")
        .ok_or_else(|| "main window missing".to_string())?;
    let mut builder = WebviewBuilder::new(PREVIEW_LABEL, WebviewUrl::External(parsed))
        .initialization_script(&preview_log_script(&slug));
    // Persistent: partitioned per-workspace cookie/storage jar so logins survive
    // restarts. Ephemeral: incognito (nothing written to disk).
    if persistent {
        builder = builder.data_store_identifier(data_store_id(&slug));
    } else {
        builder = builder.incognito(true);
    }
    window
        .add_child(
            builder,
            LogicalPosition::new(x, y),
            LogicalSize::new(width, height),
        )
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Track the panel's DOM rect (scroll/resize/route changes).
#[tauri::command]
fn preview_set_bounds(
    app: tauri::AppHandle,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    let webview = app
        .get_webview(PREVIEW_LABEL)
        .ok_or_else(|| "preview webview not created".to_string())?;
    webview
        .set_position(LogicalPosition::new(x, y))
        .map_err(|e| e.to_string())?;
    webview
        .set_size(LogicalSize::new(width, height))
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn preview_navigate(app: tauri::AppHandle, url: String) -> Result<(), String> {
    let parsed: tauri::Url = url.parse().map_err(|e| format!("bad url: {e}"))?;
    let webview = app
        .get_webview(PREVIEW_LABEL)
        .ok_or_else(|| "preview webview not created".to_string())?;
    webview.navigate(parsed).map_err(|e| e.to_string())
}

/// Hide the preview without destroying it (move it off-screen) — used when the
/// panel is collapsed or the user switches away.
#[tauri::command]
fn preview_set_visible(app: tauri::AppHandle, visible: bool) -> Result<(), String> {
    let webview = app
        .get_webview(PREVIEW_LABEL)
        .ok_or_else(|| "preview webview not created".to_string())?;
    if visible {
        webview.show().map_err(|e| e.to_string())
    } else {
        webview.hide().map_err(|e| e.to_string())
    }
}

/// History navigation. Tauri's Webview exposes no stable goBack/goForward, so we
/// drive the page's own history (WKWebView honours this for same-tab history).
#[tauri::command]
fn preview_back(app: tauri::AppHandle) -> Result<(), String> {
    let webview = app
        .get_webview(PREVIEW_LABEL)
        .ok_or_else(|| "preview webview not created".to_string())?;
    webview.eval("history.back()").map_err(|e| e.to_string())
}

#[tauri::command]
fn preview_forward(app: tauri::AppHandle) -> Result<(), String> {
    let webview = app
        .get_webview(PREVIEW_LABEL)
        .ok_or_else(|| "preview webview not created".to_string())?;
    webview.eval("history.forward()").map_err(|e| e.to_string())
}

#[derive(serde::Serialize)]
struct CookieInfo {
    name: String,
    domain: String,
}

/// List cookies in the native preview webview (name + domain only — no values).
#[tauri::command]
fn preview_cookies(app: tauri::AppHandle) -> Result<Vec<CookieInfo>, String> {
    let webview = app
        .get_webview(PREVIEW_LABEL)
        .ok_or_else(|| "preview webview not created".to_string())?;
    let cookies = webview.cookies().map_err(|e| e.to_string())?;
    Ok(cookies
        .iter()
        .map(|c| CookieInfo {
            name: c.name().to_string(),
            domain: c.domain().unwrap_or("").to_string(),
        })
        .collect())
}

/// Clear all browsing data (cookies/storage/cache) in the native preview webview.
#[tauri::command]
fn preview_clear_data(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(webview) = app.get_webview(PREVIEW_LABEL) {
        webview.clear_all_browsing_data().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Toggle the native preview webview's devtools (dev/devtools builds only).
#[tauri::command]
fn preview_devtools(app: tauri::AppHandle) -> Result<(), String> {
    let _webview = app
        .get_webview(PREVIEW_LABEL)
        .ok_or_else(|| "preview webview not created".to_string())?;
    #[cfg(debug_assertions)]
    {
        if _webview.is_devtools_open() {
            _webview.close_devtools();
        } else {
            _webview.open_devtools();
        }
    }
    Ok(())
}

#[tauri::command]
fn preview_destroy(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(webview) = app.get_webview(PREVIEW_LABEL) {
        webview.close().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Holds the running backend process so we can kill it on exit.
struct Sidecar(Mutex<Option<Child>>);

const SIDECAR_PORT: u16 = 9119;
const READY_TIMEOUT_SECS: u64 = 120;

/// Resolve the enclosing `.app` bundle from the running executable.
fn spark_app_bundle() -> Option<PathBuf> {
    let mut path = std::env::current_exe().ok()?;
    loop {
        if path.file_name().is_some_and(|n| n == "Spark.app") {
            return Some(path);
        }
        if !path.pop() {
            break;
        }
    }
    None
}

/// Clear browser download quarantine on our bundle (best-effort).
///
/// Browsers set `com.apple.quarantine` on downloaded files. Removing it avoids
/// the "damaged" / blocked-open dialogs. This only runs after the process has
/// already launched; first open from a quarantined copy may still require using
/// **Install Spark.app** on the DMG or right-click → Open. Fully frictionless
/// installs require Apple Developer ID signing + notarization.
fn clear_quarantine_on_bundle(bundle: &Path) {
    let Some(path) = bundle.to_str() else {
        return;
    };
    match Command::new("/usr/bin/xattr").args(["-cr", path]).status() {
        Ok(status) if status.success() => {
            eprintln!("[spark] cleared quarantine attributes on {path}");
        }
        Ok(status) => {
            eprintln!("[spark] xattr -cr exited with {status:?} for {path}");
        }
        Err(e) => eprintln!("[spark] xattr -cr failed for {path}: {e}"),
    }
}

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
    if let Some(bundle) = spark_app_bundle() {
        clear_quarantine_on_bundle(&bundle);
    }

    tauri::Builder::default()
        .manage(Sidecar(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            preview_create,
            preview_set_bounds,
            preview_navigate,
            preview_set_visible,
            preview_back,
            preview_forward,
            preview_cookies,
            preview_clear_data,
            preview_devtools,
            preview_destroy,
        ])
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
                    // SPARK_DESKTOP_VERSION lets the backend compare the running
                    // .app shell against the latest GitHub release for self-update.
                    .env("SPARK_DESKTOP_VERSION", env!("CARGO_PKG_VERSION"))
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
