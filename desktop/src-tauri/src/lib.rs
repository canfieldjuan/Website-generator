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
use serde::de::{MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager, State};

#[cfg(debug_assertions)]
use std::path::Path;

const MAX_ENGINE_REQUEST_BYTES: usize = 216_384;
const MAX_ENGINE_RESPONSE_BYTES: usize = 2_900_000;
const MAX_ENGINE_STDERR_BYTES: usize = 65_536;
const MAX_PROSPECT_BYTES: usize = 200_000;
const MAX_HTML_BYTES: usize = 2 * 1024 * 1024;
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

struct UniqueJson(Value);

impl<'de> Deserialize<'de> for UniqueJson {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        struct UniqueJsonVisitor;

        impl<'de> Visitor<'de> for UniqueJsonVisitor {
            type Value = UniqueJson;

            fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str("a JSON value without duplicate object keys")
            }

            fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Bool(value)))
            }

            fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Number(value.into())))
            }

            fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Number(value.into())))
            }

            fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
            where
                E: serde::de::Error,
            {
                serde_json::Number::from_f64(value)
                    .map(Value::Number)
                    .map(UniqueJson)
                    .ok_or_else(|| E::custom("JSON number is not finite"))
            }

            fn visit_str<E>(self, value: &str) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::String(value.to_owned())))
            }

            fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::String(value)))
            }

            fn visit_none<E>(self) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Null))
            }

            fn visit_unit<E>(self) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Null))
            }

            fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
            where
                D: serde::Deserializer<'de>,
            {
                UniqueJson::deserialize(deserializer)
            }

            fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
            where
                A: SeqAccess<'de>,
            {
                let mut values = Vec::new();
                while let Some(UniqueJson(value)) = sequence.next_element()? {
                    values.push(value);
                }
                Ok(UniqueJson(Value::Array(values)))
            }

            fn visit_map<A>(self, mut object: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut values = Map::new();
                while let Some(key) = object.next_key::<String>()? {
                    if values.contains_key(&key) {
                        return Err(serde::de::Error::custom("duplicate JSON object key"));
                    }
                    let UniqueJson(value) = object.next_value()?;
                    values.insert(key, value);
                }
                Ok(UniqueJson(Value::Object(values)))
            }
        }

        deserializer.deserialize_any(UniqueJsonVisitor)
    }
}

fn decode_unique_json(source: &[u8]) -> Result<Value, serde_json::Error> {
    serde_json::from_slice::<UniqueJson>(source).map(|value| value.0)
}

fn lock_error() -> String {
    "Website Generator process state is unavailable.".to_owned()
}

fn kill_running(state: &DesktopState) {
    let Ok(mut running) = state.running.lock() else {
        return;
    };
    if let Some(child) = running.as_mut() {
        let _ = terminate_process_tree(child);
    }
}

fn terminate_process_tree(child: &mut Child) -> io::Result<()> {
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill.exe");
        command
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        hide_console_window(&mut command);
        let status = command.status()?;
        if status.success() || child.try_wait()?.is_some() {
            return Ok(());
        }
        Err(io::Error::other(
            "Windows could not terminate the process tree",
        ))
    }

    #[cfg(not(windows))]
    {
        child.kill()
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
            terminate_process_tree(child)
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

#[derive(Debug, PartialEq, Eq)]
struct CanonicalDecimal {
    negative: bool,
    digits: String,
    exponent: i64,
}

fn canonical_decimal(token: &str) -> Option<CanonicalDecimal> {
    let (negative, unsigned) = match token.strip_prefix('-') {
        Some(unsigned) => (true, unsigned),
        None => (false, token),
    };
    let (mantissa, exponent) = match unsigned.split_once(['e', 'E']) {
        Some((mantissa, exponent)) => (mantissa, exponent.parse::<i64>().ok()?),
        None => (unsigned, 0),
    };
    let (whole, fraction) = match mantissa.split_once('.') {
        Some(parts) => parts,
        None => (mantissa, ""),
    };
    if whole.is_empty()
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || !fraction.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    let fraction_len = i64::try_from(fraction.len()).ok()?;
    let mut power = exponent.checked_sub(fraction_len)?;
    let combined = format!("{whole}{fraction}");
    let significant = combined.trim_start_matches('0');
    if significant.is_empty() {
        return Some(CanonicalDecimal {
            negative,
            digits: "0".to_owned(),
            exponent: 0,
        });
    }
    let mut digits = significant.to_owned();
    while digits.ends_with('0') {
        digits.pop();
        power = power.checked_add(1)?;
    }
    Some(CanonicalDecimal {
        negative,
        digits,
        exponent: power,
    })
}

fn exceeds_js_safe_integer(number: &CanonicalDecimal) -> bool {
    if number.digits == "0" || number.exponent < 0 {
        return false;
    }
    let Ok(zeroes) = usize::try_from(number.exponent) else {
        return true;
    };
    let Some(length) = number.digits.len().checked_add(zeroes) else {
        return true;
    };
    const MAX_SAFE: &str = "9007199254740991";
    if length != MAX_SAFE.len() {
        return length > MAX_SAFE.len();
    }
    let mut magnitude = number.digits.clone();
    magnitude.extend(std::iter::repeat_n('0', zeroes));
    magnitude.as_str() > MAX_SAFE
}

fn require_js_roundtrip_number_token(token: &str) -> Result<(), String> {
    let original = canonical_decimal(token);
    let parsed = token.parse::<f64>().ok().filter(|value| value.is_finite());
    let roundtrip = parsed.and_then(|value| {
        if value == 0.0 && value.is_sign_negative() {
            Some("0".to_owned())
        } else {
            serde_json::to_string(&value).ok()
        }
    });
    let preserved = original.as_ref().is_some_and(|original| {
        roundtrip
            .as_deref()
            .and_then(canonical_decimal)
            .is_some_and(|roundtrip| roundtrip == *original)
            && !exceeds_js_safe_integer(original)
    });
    if preserved {
        Ok(())
    } else {
        Err("Prospect JSON contains a number this app cannot preserve exactly.".to_owned())
    }
}

fn require_js_roundtrip_number_tokens(source: &[u8]) -> Result<(), String> {
    let mut index = 0;
    let mut in_string = false;
    while index < source.len() {
        let byte = source[index];
        if in_string {
            if byte == b'\\' {
                index = index.saturating_add(2);
                continue;
            }
            if byte == b'"' {
                in_string = false;
            }
            index += 1;
            continue;
        }
        if byte == b'"' {
            in_string = true;
            index += 1;
            continue;
        }
        if byte == b'-' || byte.is_ascii_digit() {
            let start = index;
            index += 1;
            while index < source.len()
                && !matches!(
                    source[index],
                    b' ' | b'\t' | b'\r' | b'\n' | b',' | b']' | b'}'
                )
            {
                index += 1;
            }
            let token = std::str::from_utf8(&source[start..index]).map_err(|_| {
                "Prospect JSON contains a number this app cannot preserve exactly.".to_owned()
            })?;
            require_js_roundtrip_number_token(token)?;
            continue;
        }
        index += 1;
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

fn encode_prospect(prospect: &Value) -> Result<Vec<u8>, String> {
    if !prospect.is_object() {
        return Err("Prospect data must be a JSON object.".to_owned());
    }
    let mut bytes = serde_json::to_vec_pretty(prospect)
        .map_err(|_| "Prospect JSON could not be encoded.".to_owned())?;
    bytes.push(b'\n');
    if bytes.len() > MAX_PROSPECT_BYTES {
        return Err("The prospect document is too large to export.".to_owned());
    }
    Ok(bytes)
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
    let document = decode_unique_json(&bytes).map_err(|_| {
        "The selected prospect file is not valid JSON or contains duplicate keys.".to_owned()
    })?;
    if !document.is_object() {
        return Err("The selected prospect JSON must contain one object.".to_owned());
    }
    require_js_roundtrip_number_tokens(&bytes)?;
    encode_prospect(&document)?;
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
    let bytes = encode_prospect(&prospect)?;
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
                let _ = request_engine_cancellation(&state);
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
    fn imported_numbers_must_survive_the_javascript_roundtrip() {
        for source in [
            r#"{"value":9007199254740991}"#,
            r#"{"value":-9007199254740991}"#,
            r#"{"nested":[0,0.1,1.5,1e3]}"#,
        ] {
            serde_json::from_str::<Value>(source).unwrap();
            assert!(require_js_roundtrip_number_tokens(source.as_bytes()).is_ok());
        }

        for source in [
            r#"{"value":9007199254740992}"#,
            r#"{"value":-9007199254740992}"#,
            r#"{"value":0.10000000000000001}"#,
            r#"{"value":-0}"#,
            r#"{"nested":[1e400]}"#,
        ] {
            assert!(
                require_js_roundtrip_number_tokens(source.as_bytes()).is_err(),
                "unexpectedly admitted {source}"
            );
        }
    }

    #[test]
    fn imported_json_rejects_duplicate_keys_at_every_depth() {
        assert!(decode_unique_json(br#"{"name":"one","name":"two"}"#).is_err());
        assert!(decode_unique_json(br#"{"nested":{"value":1,"value":2}}"#).is_err());
        assert!(decode_unique_json(br#"{"items":[{"value":1,"value":2}]}"#).is_err());
        assert_eq!(
            decode_unique_json(br#"{"name":"one","nested":{"value":1}}"#).unwrap(),
            json!({"name": "one", "nested": {"value": 1}})
        );
    }

    #[test]
    fn imported_prospect_must_fit_its_canonical_export_boundary() {
        let source = format!(r#"{{"a":"{}"}}"#, "x".repeat(MAX_PROSPECT_BYTES - 8));
        assert_eq!(source.len(), MAX_PROSPECT_BYTES);
        let document = decode_unique_json(source.as_bytes()).unwrap();

        assert!(encode_prospect(&document).is_err());
        assert!(encode_prospect(&json!({"a": "short"})).is_ok());
    }

    #[cfg(windows)]
    #[test]
    fn windows_cancellation_terminates_descendants() {
        let directory = tempfile::tempdir().unwrap();
        let pid_path = directory.path().join("descendant.pid");
        let escaped_path = pid_path.to_string_lossy().replace('\'', "''");
        let script = format!(
            "$child = Start-Process -FilePath 'cmd.exe' -ArgumentList '/C','ping -n 30 127.0.0.1 >NUL' -WindowStyle Hidden -PassThru; Set-Content -LiteralPath '{escaped_path}' -Value $child.Id; Start-Sleep -Seconds 30"
        );
        let mut command = Command::new("powershell.exe");
        command
            .args(["-NoProfile", "-NonInteractive", "-Command", &script])
            .stdout(Stdio::null())
            .stderr(Stdio::piped());
        hide_console_window(&mut command);
        let mut parent = command.spawn().unwrap();
        let deadline = std::time::Instant::now() + Duration::from_secs(15);
        while !pid_path.is_file() && std::time::Instant::now() < deadline {
            if parent.try_wait().unwrap().is_some() {
                let mut stderr = Vec::new();
                if let Some(mut stream) = parent.stderr.take() {
                    let _ = stream.read_to_end(&mut stderr);
                }
                panic!(
                    "the descendant fixture exited before publishing its PID: {}",
                    String::from_utf8_lossy(&stderr)
                );
            }
            thread::sleep(Duration::from_millis(25));
        }
        if !pid_path.is_file() {
            let _ = terminate_process_tree(&mut parent);
            let mut stderr = Vec::new();
            if let Some(mut stream) = parent.stderr.take() {
                let _ = stream.read_to_end(&mut stderr);
            }
            let _ = parent.wait();
            panic!(
                "the descendant PID was not published within the cold-start boundary: {}",
                String::from_utf8_lossy(&stderr)
            );
        }
        let descendant_pid = fs::read_to_string(&pid_path).unwrap().trim().to_owned();

        terminate_process_tree(&mut parent).unwrap();
        let _ = parent.wait();
        let output = Command::new("tasklist.exe")
            .args(["/FI", &format!("PID eq {descendant_pid}"), "/NH"])
            .output()
            .unwrap();

        assert!(!String::from_utf8_lossy(&output.stdout).contains(&descendant_pid));
    }
}
