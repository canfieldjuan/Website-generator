use std::{
    fs,
    io::{self, Read, Write},
    process::{Child, Command, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicU8, Ordering},
    },
    thread,
    time::Duration,
};

use base64::{Engine as _, engine::general_purpose::STANDARD as BASE64};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager, State};

#[cfg(debug_assertions)]
use std::path::Path;

const MAX_ENGINE_REQUEST_BYTES: usize = 216_384;
const MAX_ENGINE_RESPONSE_BYTES: usize = 2_900_000;
const MAX_ENGINE_STDERR_BYTES: usize = 65_536;
const MAX_PROSPECT_BYTES: usize = 200_000;
const MAX_HTML_BYTES: usize = 2 * 1024 * 1024;
const JS_MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;
const ENGINE_IDLE: u8 = 0;
const ENGINE_ACTIVE: u8 = 1;
const ENGINE_CANCELLED: u8 = 2;

#[derive(Clone, Debug, Deserialize, Serialize)]
struct EngineArtifact {
    media_type: String,
    display_name: String,
    byte_size: usize,
    sha256: String,
    payload_base64: String,
}

#[derive(Clone, Debug)]
struct CachedArtifact {
    display_name: String,
    bytes: Vec<u8>,
}

#[derive(Default)]
struct DesktopState {
    running: Mutex<Option<Child>>,
    engine_phase: AtomicU8,
    artifact: Mutex<Option<CachedArtifact>>,
}

#[derive(Serialize)]
struct ImportedProspect {
    file_name: String,
    document: Value,
}

fn lock_error() -> String {
    "Website Generator process state is unavailable.".to_owned()
}

fn kill_running(state: &DesktopState) {
    let Ok(mut running) = state.running.lock() else {
        return;
    };
    if let Some(child) = running.as_mut() {
        let _ = child.kill();
    }
}

fn begin_engine_operation(state: &DesktopState) -> Result<(), String> {
    state
        .engine_phase
        .compare_exchange(
            ENGINE_IDLE,
            ENGINE_ACTIVE,
            Ordering::SeqCst,
            Ordering::SeqCst,
        )
        .map(|_| ())
        .map_err(|_| "A Website Generator operation is already running.".to_owned())
}

fn finish_engine_operation(state: &DesktopState) {
    state.engine_phase.store(ENGINE_IDLE, Ordering::SeqCst);
}

fn request_engine_cancellation(state: &DesktopState) -> Result<bool, String> {
    loop {
        match state.engine_phase.load(Ordering::SeqCst) {
            ENGINE_IDLE => return Ok(false),
            ENGINE_CANCELLED => break,
            ENGINE_ACTIVE => {
                if state
                    .engine_phase
                    .compare_exchange(
                        ENGINE_ACTIVE,
                        ENGINE_CANCELLED,
                        Ordering::SeqCst,
                        Ordering::SeqCst,
                    )
                    .is_ok()
                {
                    break;
                }
            }
            _ => return Err("The Website Generator process state is invalid.".to_owned()),
        }
    }

    let mut running = state.running.lock().map_err(|_| lock_error())?;
    if let Some(child) = running.as_mut() {
        let exited = child
            .try_wait()
            .map_err(|_| "The Website Generator process status is unavailable.".to_owned())?
            .is_some();
        if !exited {
            child
                .kill()
                .map_err(|_| "The Website Generator process could not be cancelled.".to_owned())?;
        }
    }
    Ok(true)
}

fn read_bounded(reader: impl Read, maximum: usize) -> io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    reader.take((maximum + 1) as u64).read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "engine output exceeded its boundary",
        ));
    }
    Ok(bytes)
}

#[cfg(not(debug_assertions))]
fn packaged_engine_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    let file_name = if cfg!(windows) {
        "website-redesign-connect.exe"
    } else {
        "website-redesign-connect"
    };
    app.path()
        .resource_dir()
        .map(|root| root.join("resources").join(file_name))
        .map_err(|_| "The packaged Website Generator engine is unavailable.".to_owned())
}

fn engine_command(_app: &AppHandle) -> Result<Command, String> {
    #[cfg(debug_assertions)]
    {
        let repository = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let script = repository.join("connect_provider.py");
        if !script.is_file() {
            return Err("The development Website Generator engine is unavailable.".to_owned());
        }
        let mut command = Command::new("python");
        command.arg(script).arg("desktop").current_dir(repository);
        Ok(command)
    }

    #[cfg(not(debug_assertions))]
    {
        let executable = packaged_engine_path(_app)?;
        if !executable.is_file() {
            return Err("The packaged Website Generator engine is unavailable.".to_owned());
        }
        let mut command = Command::new(executable);
        command.arg("desktop");
        Ok(command)
    }
}

#[cfg(windows)]
fn hide_console_window(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(0x0800_0000);
}

#[cfg(not(windows))]
fn hide_console_window(_command: &mut Command) {}

fn parse_engine_success(output: &[u8], status_success: bool) -> Result<Value, String> {
    let lines: Vec<&[u8]> = output
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
        .collect();
    if lines.len() != 1 {
        return Err("The Website Generator engine returned an invalid response.".to_owned());
    }
    let document: Value = serde_json::from_slice(lines[0])
        .map_err(|_| "The Website Generator engine returned invalid JSON.".to_owned())?;
    let object = document
        .as_object()
        .ok_or_else(|| "The Website Generator engine returned an invalid response.".to_owned())?;
    match object.get("ok").and_then(Value::as_bool) {
        Some(true) if status_success => object
            .get("data")
            .cloned()
            .filter(Value::is_object)
            .ok_or_else(|| "The Website Generator engine returned no result.".to_owned()),
        Some(false) => {
            let message = object
                .get("error")
                .and_then(Value::as_object)
                .and_then(|error| error.get("message"))
                .and_then(Value::as_str)
                .filter(|message| !message.is_empty())
                .unwrap_or("Website generation failed.");
            Err(message.to_owned())
        }
        _ => Err("The Website Generator engine did not complete normally.".to_owned()),
    }
}

fn run_engine(
    app: &AppHandle,
    state: &Arc<DesktopState>,
    operation: &str,
    payload: Value,
) -> Result<Value, String> {
    let request = serde_json::to_vec(&json!({
        "protocol": 1,
        "operation": operation,
        "payload": payload,
    }))
    .map_err(|_| "The Website Generator request could not be encoded.".to_owned())?;
    if request.len() > MAX_ENGINE_REQUEST_BYTES {
        return Err("The prospect document is too large.".to_owned());
    }

    let mut command = engine_command(app)?;
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    hide_console_window(&mut command);

    let (mut stdin, stdout, stderr) = {
        let mut running = state.running.lock().map_err(|_| lock_error())?;
        if running.is_some() {
            return Err("A Website Generator operation is already running.".to_owned());
        }
        if state.engine_phase.load(Ordering::SeqCst) == ENGINE_CANCELLED {
            return Err("Website generation was cancelled.".to_owned());
        }
        let mut child = command
            .spawn()
            .map_err(|_| "The Website Generator engine could not start.".to_owned())?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "The Website Generator engine input is unavailable.".to_owned())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "The Website Generator engine output is unavailable.".to_owned())?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| "The Website Generator engine output is unavailable.".to_owned())?;
        *running = Some(child);
        (stdin, stdout, stderr)
    };

    let output_reader = thread::spawn(move || read_bounded(stdout, MAX_ENGINE_RESPONSE_BYTES));
    let error_reader = thread::spawn(move || read_bounded(stderr, MAX_ENGINE_STDERR_BYTES));

    let write_result = stdin
        .write_all(&request)
        .and_then(|_| stdin.write_all(b"\n"));
    drop(stdin);
    if write_result.is_err() {
        kill_running(state);
    }

    let exit_status = loop {
        let status = {
            let mut running = state.running.lock().map_err(|_| lock_error())?;
            let child = running
                .as_mut()
                .ok_or_else(|| "The Website Generator process ended unexpectedly.".to_owned())?;
            child
                .try_wait()
                .map_err(|_| "The Website Generator process status is unavailable.".to_owned())?
        };
        if let Some(status) = status {
            break status;
        }
        thread::sleep(Duration::from_millis(50));
    };

    {
        let mut running = state.running.lock().map_err(|_| lock_error())?;
        running.take();
    }
    let output = output_reader
        .join()
        .map_err(|_| "The Website Generator output reader stopped.".to_owned())?
        .map_err(|_| "The Website Generator output was too large.".to_owned())?;
    let _stderr = error_reader
        .join()
        .map_err(|_| "The Website Generator error reader stopped.".to_owned())?
        .map_err(|_| "The Website Generator error output was too large.".to_owned())?;

    if state.engine_phase.load(Ordering::SeqCst) == ENGINE_CANCELLED {
        return Err("Website generation was cancelled.".to_owned());
    }
    if write_result.is_err() {
        return Err("The Website Generator request could not be sent.".to_owned());
    }
    parse_engine_success(&output, exit_status.success())
}

fn validate_artifact(value: Value) -> Result<(EngineArtifact, CachedArtifact), String> {
    let artifact: EngineArtifact = serde_json::from_value(value)
        .map_err(|_| "The Website Generator returned an invalid artifact.".to_owned())?;
    if artifact.media_type != "text/html"
        || artifact.display_name.is_empty()
        || artifact.display_name.len() > 240
        || !artifact.display_name.ends_with(".html")
        || artifact.display_name.contains(['/', '\\'])
        || artifact.byte_size > MAX_HTML_BYTES
        || artifact.sha256.len() != 64
        || !artifact.sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        return Err("The Website Generator returned an invalid artifact.".to_owned());
    }
    let bytes = BASE64
        .decode(&artifact.payload_base64)
        .map_err(|_| "The Website Generator returned unreadable website data.".to_owned())?;
    let digest = format!("{:x}", Sha256::digest(&bytes));
    if bytes.len() != artifact.byte_size || digest != artifact.sha256 {
        return Err("The generated website did not match its receipt.".to_owned());
    }
    let cached = CachedArtifact {
        display_name: artifact.display_name.clone(),
        bytes,
    };
    Ok((artifact, cached))
}

fn require_js_safe_integers(value: &Value) -> Result<(), String> {
    match value {
        Value::Number(number) => {
            let unsafe_integer = if let Some(value) = number.as_i64() {
                !(-JS_MAX_SAFE_INTEGER..=JS_MAX_SAFE_INTEGER).contains(&value)
            } else if let Some(value) = number.as_u64() {
                value > JS_MAX_SAFE_INTEGER as u64
            } else if let Some(value) = number.as_f64() {
                value.fract() == 0.0 && value.abs() > JS_MAX_SAFE_INTEGER as f64
            } else {
                true
            };
            if unsafe_integer {
                return Err(
                    "Prospect JSON contains an integer this app cannot preserve exactly."
                        .to_owned(),
                );
            }
        }
        Value::Array(values) => {
            for value in values {
                require_js_safe_integers(value)?;
            }
        }
        Value::Object(values) => {
            for value in values.values() {
                require_js_safe_integers(value)?;
            }
        }
        _ => {}
    }
    Ok(())
}

#[tauri::command]
async fn engine_status(
    app: AppHandle,
    state: State<'_, Arc<DesktopState>>,
    generation: Value,
) -> Result<Value, String> {
    let state = state.inner().clone();
    begin_engine_operation(&state)?;
    let worker_state = state.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        run_engine(
            &app,
            &worker_state,
            "generation.status",
            json!({ "generation": generation }),
        )
    })
    .await;
    finish_engine_operation(&state);
    result.map_err(|_| "The model check stopped unexpectedly.".to_owned())?
}

#[tauri::command]
async fn generate_site(
    app: AppHandle,
    state: State<'_, Arc<DesktopState>>,
    prospect: Value,
    generation: Value,
) -> Result<EngineArtifact, String> {
    if !prospect.is_object() {
        return Err("Prospect data must be a JSON object.".to_owned());
    }
    let state = state.inner().clone();
    begin_engine_operation(&state)?;
    {
        let mut cached = match state.artifact.lock() {
            Ok(cached) => cached,
            Err(_) => {
                finish_engine_operation(&state);
                return Err(lock_error());
            }
        };
        cached.take();
    }
    let worker_state = state.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        let data = run_engine(
            &app,
            &worker_state,
            "site.generate",
            json!({ "prospect": prospect, "generation": generation }),
        )?;
        let value = data
            .get("artifact")
            .cloned()
            .ok_or_else(|| "The Website Generator returned no artifact.".to_owned())?;
        let (artifact, cached) = validate_artifact(value)?;
        *worker_state.artifact.lock().map_err(|_| lock_error())? = Some(cached);
        Ok(artifact)
    })
    .await;
    finish_engine_operation(&state);
    result.map_err(|_| "Website generation stopped unexpectedly.".to_owned())?
}

#[tauri::command]
fn cancel_generation(state: State<'_, Arc<DesktopState>>) -> Result<bool, String> {
    request_engine_cancellation(&state)
}

#[tauri::command]
fn import_prospect() -> Result<Option<ImportedProspect>, String> {
    let Some(path) = rfd::FileDialog::new()
        .add_filter("Prospect JSON", &["json"])
        .pick_file()
    else {
        return Ok(None);
    };
    let metadata = fs::metadata(&path)
        .map_err(|_| "The selected prospect file could not be read.".to_owned())?;
    if !metadata.is_file() || metadata.len() > MAX_PROSPECT_BYTES as u64 {
        return Err("The selected prospect file is too large or invalid.".to_owned());
    }
    let bytes =
        fs::read(&path).map_err(|_| "The selected prospect file could not be read.".to_owned())?;
    let document: Value = serde_json::from_slice(&bytes)
        .map_err(|_| "The selected prospect file is not valid JSON.".to_owned())?;
    if !document.is_object() {
        return Err("The selected prospect JSON must contain one object.".to_owned());
    }
    require_js_safe_integers(&document)?;
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("prospect.json")
        .to_owned();
    Ok(Some(ImportedProspect {
        file_name,
        document,
    }))
}

#[tauri::command]
fn export_prospect(prospect: Value) -> Result<Option<String>, String> {
    if !prospect.is_object() {
        return Err("Prospect data must be a JSON object.".to_owned());
    }
    let mut bytes = serde_json::to_vec_pretty(&prospect)
        .map_err(|_| "Prospect JSON could not be encoded.".to_owned())?;
    bytes.push(b'\n');
    if bytes.len() > MAX_PROSPECT_BYTES {
        return Err("The prospect document is too large to export.".to_owned());
    }
    let Some(path) = rfd::FileDialog::new()
        .add_filter("Prospect JSON", &["json"])
        .set_file_name("prospect.json")
        .save_file()
    else {
        return Ok(None);
    };
    fs::write(&path, bytes).map_err(|_| "Prospect JSON could not be saved.".to_owned())?;
    Ok(Some(path.to_string_lossy().into_owned()))
}

#[tauri::command]
fn save_artifact(state: State<'_, Arc<DesktopState>>) -> Result<Option<String>, String> {
    let cached = state
        .artifact
        .lock()
        .map_err(|_| lock_error())?
        .clone()
        .ok_or_else(|| "Generate a website before saving.".to_owned())?;
    let Some(path) = rfd::FileDialog::new()
        .add_filter("HTML website", &["html"])
        .set_file_name(&cached.display_name)
        .save_file()
    else {
        return Ok(None);
    };
    fs::write(&path, cached.bytes)
        .map_err(|_| "The generated website could not be saved.".to_owned())?;
    Ok(Some(path.to_string_lossy().into_owned()))
}

pub fn run() {
    tauri::Builder::default()
        .manage(Arc::new(DesktopState::default()))
        .invoke_handler(tauri::generate_handler![
            import_prospect,
            export_prospect,
            engine_status,
            generate_site,
            cancel_generation,
            save_artifact,
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state = window.state::<Arc<DesktopState>>();
                kill_running(&state);
            }
        })
        .run(tauri::generate_context!())
        .expect("Website Generator desktop failed to start");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn artifact_for(bytes: &[u8]) -> Value {
        json!({
            "media_type": "text/html",
            "display_name": "example-homepage.html",
            "byte_size": bytes.len(),
            "sha256": format!("{:x}", Sha256::digest(bytes)),
            "payload_base64": BASE64.encode(bytes),
        })
    }

    #[test]
    fn bounded_reader_accepts_max_and_rejects_max_plus_one() {
        assert_eq!(read_bounded(&b"abcd"[..], 4).unwrap(), b"abcd");
        assert_eq!(
            read_bounded(&b"abcde"[..], 4).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
    }

    #[test]
    fn engine_response_requires_one_success_envelope() {
        let data =
            parse_engine_success(b"{\"ok\":true,\"data\":{\"ready\":true}}\n", true).unwrap();
        assert_eq!(data["ready"], true);
        assert!(parse_engine_success(b"{}\n{}\n", true).is_err());
        assert!(parse_engine_success(b"{\"ok\":true,\"data\":{}}\n", false).is_err());
    }

    #[test]
    fn safe_engine_error_is_returned_without_other_fields() {
        let output = br#"{"ok":false,"error":{"code":"GENERATION_FAILED","message":"Provider did not produce an admissible website.","detail":"secret"}}"#;
        let error = parse_engine_success(output, false).unwrap_err();
        assert_eq!(error, "Provider did not produce an admissible website.");
        assert!(!error.contains("secret"));
    }

    #[test]
    fn artifact_receipt_is_verified_before_caching() {
        let html = b"<!doctype html><html><body>Ready</body></html>";
        let (artifact, cached) = validate_artifact(artifact_for(html)).unwrap();
        assert_eq!(artifact.byte_size, html.len());
        assert_eq!(cached.bytes, html);

        let mut wrong_size = artifact_for(html);
        wrong_size["byte_size"] = json!(html.len() + 1);
        assert!(validate_artifact(wrong_size).is_err());

        let mut wrong_hash = artifact_for(html);
        wrong_hash["sha256"] = json!("0".repeat(64));
        assert!(validate_artifact(wrong_hash).is_err());

        let mut wrong_extension = artifact_for(html);
        wrong_extension["display_name"] = json!("preview.exe");
        assert!(validate_artifact(wrong_extension).is_err());
    }

    #[test]
    fn artifact_name_cannot_escape_the_save_dialog_directory() {
        let html = b"<body>Ready</body>";
        let mut artifact = artifact_for(html);
        artifact["display_name"] = json!("../outside.html");
        assert!(validate_artifact(artifact).is_err());
    }

    #[test]
    fn cancellation_is_recorded_before_a_child_is_registered() {
        let state = DesktopState::default();

        begin_engine_operation(&state).unwrap();
        assert!(begin_engine_operation(&state).is_err());
        assert!(request_engine_cancellation(&state).unwrap());
        assert_eq!(state.engine_phase.load(Ordering::SeqCst), ENGINE_CANCELLED);
        assert!(state.running.lock().unwrap().is_none());

        finish_engine_operation(&state);
        assert!(!request_engine_cancellation(&state).unwrap());
    }

    #[test]
    fn imported_numbers_reject_only_unsafe_integers() {
        for accepted in [
            json!(JS_MAX_SAFE_INTEGER),
            json!(-JS_MAX_SAFE_INTEGER),
            json!({"nested": [0, 1.5, JS_MAX_SAFE_INTEGER]}),
        ] {
            assert!(require_js_safe_integers(&accepted).is_ok());
        }

        for rejected in [
            json!(JS_MAX_SAFE_INTEGER + 1),
            json!(-JS_MAX_SAFE_INTEGER - 1),
            json!({"nested": [JS_MAX_SAFE_INTEGER as u64 + 1]}),
        ] {
            assert!(require_js_safe_integers(&rejected).is_err());
        }
    }
}
