use std::{
    ffi::OsString,
    fs,
    io::{self, BufRead, BufReader, Read, Write},
    path::Path,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicU8, Ordering},
        mpsc,
    },
    thread,
    time::{Duration, Instant},
};

use base64::{Engine as _, engine::general_purpose::STANDARD as BASE64};
use serde::de::{MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager, State};
use uuid::Uuid;

const MAX_ENGINE_REQUEST_BYTES: usize = 216_384;
const MAX_ENGINE_RESPONSE_BYTES: usize = 2_900_000;
const MAX_ENGINE_STDERR_BYTES: usize = 65_536;
const MAX_PROSPECT_BYTES: usize = 200_000;
const MAX_HTML_BYTES: usize = 2 * 1024 * 1024;
const ENGINE_IDLE: u8 = 0;
const ENGINE_ACTIVE: u8 = 1;
const ENGINE_CANCELLED: u8 = 2;
const MAX_LIFECYCLE_OUTPUT_BYTES: usize = 16 * 1024;
const CONNECT_COMMAND_TIMEOUT: Duration = Duration::from_secs(15);
const CONNECT_STARTUP_TIMEOUT: Duration = Duration::from_secs(60);
const CONNECT_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(5);
const DESKTOP_REGISTRATION_TOKEN_ENV: &str = "WEBSITE_GENERATOR_DESKTOP_REGISTRATION_TOKEN";

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

struct ManagedProvider {
    attempt: u64,
    child: Child,
    stdin: Option<ChildStdin>,
    registration_cleanup: Option<Command>,
    ready: bool,
}

#[derive(Default)]
struct ProviderLifecycle {
    managed: Option<ManagedProvider>,
    pending_registration_cleanup: Option<Command>,
    active_start: Option<u64>,
    next_attempt: u64,
}

#[derive(Default)]
struct DesktopState {
    running: Mutex<Option<Child>>,
    engine_phase: AtomicU8,
    artifact: Mutex<Option<CachedArtifact>>,
    provider: Mutex<ProviderLifecycle>,
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

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
struct EntitlementStatus {
    state: String,
    active: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
struct ConnectStatus {
    entitlement_state: String,
    entitlement_active: bool,
    provider_running: bool,
    provider_managed: bool,
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

fn read_bounded_file(path: &Path, maximum: usize) -> io::Result<Vec<u8>> {
    let file = fs::File::open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > maximum as u64 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "selected file exceeded its boundary",
        ));
    }
    read_bounded(file, maximum)
}

fn write_atomic(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let parent = path
        .parent()
        .filter(|value| !value.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let mut temporary = tempfile::NamedTempFile::new_in(parent)?;
    temporary.write_all(bytes)?;
    temporary.as_file_mut().sync_all()?;
    temporary.persist(path).map_err(|error| error.error)?;
    Ok(())
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

fn base_engine_command(_app: &AppHandle) -> Result<Command, String> {
    #[cfg(debug_assertions)]
    {
        let repository = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let script = repository.join("connect_provider.py");
        if !script.is_file() {
            return Err("The development Website Generator engine is unavailable.".to_owned());
        }
        let mut command = Command::new("python");
        command.arg(script).current_dir(repository);
        Ok(command)
    }

    #[cfg(not(debug_assertions))]
    {
        let executable = packaged_engine_path(_app)?;
        if !executable.is_file() {
            return Err("The packaged Website Generator engine is unavailable.".to_owned());
        }
        let command = Command::new(executable);
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

fn parse_single_json_object(output: &[u8]) -> Result<Value, String> {
    let lines: Vec<&[u8]> = output
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
        .collect();
    if lines.len() != 1 {
        return Err("The Local Connect command returned an invalid response.".to_owned());
    }
    let value: Value = serde_json::from_slice(lines[0])
        .map_err(|_| "The Local Connect command returned invalid JSON.".to_owned())?;
    if !value.is_object() {
        return Err("The Local Connect command returned an invalid response.".to_owned());
    }
    Ok(value)
}

fn parse_cli_error(stderr: &[u8]) -> String {
    let Ok(value) = parse_single_json_object(stderr) else {
        return "The Local Connect command failed.".to_owned();
    };
    value
        .get("error")
        .and_then(Value::as_object)
        .and_then(|error| error.get("message"))
        .and_then(Value::as_str)
        .filter(|message| !message.is_empty() && message.len() <= 512)
        .unwrap_or("The Local Connect command failed.")
        .to_owned()
}

fn force_reap(child: &mut Child) -> io::Result<()> {
    terminate_process_tree(child)?;
    child.wait().map(|_| ())
}

fn wait_for_connect_command(
    child: &mut Child,
    timeout: Duration,
) -> Result<std::process::ExitStatus, String> {
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Ok(status),
            Ok(None) if Instant::now() < deadline => {
                thread::sleep(Duration::from_millis(25));
            }
            Ok(None) => {
                force_reap(child).map_err(|_| {
                    "The Local Connect command could not be stopped after timing out.".to_owned()
                })?;
                return Err("The Local Connect command did not finish in time.".to_owned());
            }
            Err(_) => {
                force_reap(child).map_err(|_| {
                    "The Local Connect command could not be stopped after a status failure."
                        .to_owned()
                })?;
                return Err("The Local Connect command status is unavailable.".to_owned());
            }
        }
    }
}

fn cleanup_provider_registration(command: &mut Command) -> Result<(), String> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_console_window(command);
    let mut child = command
        .spawn()
        .map_err(|_| "The Local Connect registration could not be reconciled.".to_owned())?;
    let status = wait_for_connect_command(&mut child, CONNECT_COMMAND_TIMEOUT)?;
    if !status.success() {
        return Err("The Local Connect registration could not be reconciled.".to_owned());
    }
    Ok(())
}

fn new_desktop_registration_token() -> String {
    format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple())
}

fn reconcile_pending_registration(slot: &mut ProviderLifecycle) -> Result<(), String> {
    let Some(cleanup) = slot.pending_registration_cleanup.as_mut() else {
        return Ok(());
    };
    cleanup_provider_registration(cleanup)?;
    slot.pending_registration_cleanup = None;
    Ok(())
}

fn reconcile_managed_provider_termination(slot: &mut ProviderLifecycle) -> Result<(), String> {
    if slot.pending_registration_cleanup.is_some() {
        return Err("The Local Connect registration could not be reconciled.".to_owned());
    }
    let Some(mut provider) = slot.managed.take() else {
        return Ok(());
    };
    slot.pending_registration_cleanup = provider.registration_cleanup.take();
    reconcile_pending_registration(slot)
}

fn run_cli_json(app: &AppHandle, arguments: &[OsString]) -> Result<Value, String> {
    let mut command = base_engine_command(app)?;
    command
        .args(arguments)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    hide_console_window(&mut command);
    let mut child = command
        .spawn()
        .map_err(|_| "The Local Connect command could not start.".to_owned())?;
    let Some(stdout) = child.stdout.take() else {
        let _ = force_reap(&mut child);
        return Err("The Local Connect command output is unavailable.".to_owned());
    };
    let Some(stderr) = child.stderr.take() else {
        let _ = force_reap(&mut child);
        return Err("The Local Connect command output is unavailable.".to_owned());
    };
    let output_reader = thread::spawn(move || read_bounded(stdout, MAX_LIFECYCLE_OUTPUT_BYTES));
    let error_reader = thread::spawn(move || read_bounded(stderr, MAX_LIFECYCLE_OUTPUT_BYTES));
    let status = wait_for_connect_command(&mut child, CONNECT_COMMAND_TIMEOUT);
    let output = output_reader
        .join()
        .map_err(|_| "The Local Connect output reader stopped.".to_owned())?
        .map_err(|_| "The Local Connect command output was too large.".to_owned())?;
    let error = error_reader
        .join()
        .map_err(|_| "The Local Connect error reader stopped.".to_owned())?
        .map_err(|_| "The Local Connect command error output was too large.".to_owned())?;
    let status = status?;
    if !status.success() {
        return Err(parse_cli_error(&error));
    }
    parse_single_json_object(&output)
}

fn parse_entitlement_status(value: Value) -> Result<EntitlementStatus, String> {
    let object = value
        .as_object()
        .ok_or_else(|| "The Local Connect entitlement status is invalid.".to_owned())?;
    if object.len() != 2 || !object.contains_key("state") || !object.contains_key("active") {
        return Err("The Local Connect entitlement status is invalid.".to_owned());
    }
    let status: EntitlementStatus = serde_json::from_value(value)
        .map_err(|_| "The Local Connect entitlement status is invalid.".to_owned())?;
    let known = matches!(
        status.state.as_str(),
        "active"
            | "authority_unavailable"
            | "missing"
            | "invalid"
            | "not_yet_valid"
            | "expired"
            | "feature_missing"
    );
    if !known || status.active != (status.state == "active") {
        return Err("The Local Connect entitlement status is invalid.".to_owned());
    }
    Ok(status)
}

fn read_entitlement_status(app: &AppHandle) -> Result<EntitlementStatus, String> {
    parse_entitlement_status(run_cli_json(
        app,
        &[OsString::from("entitlement"), OsString::from("status")],
    )?)
}

fn parse_provider_readiness(line: &[u8]) -> Result<(), String> {
    match line {
        b"{\"ready\":true}\n" | b"{\"ready\":true}\r\n" => Ok(()),
        _ => Err("The Local Connect provider did not become ready.".to_owned()),
    }
}

fn read_provider_readiness(reader: impl Read) -> io::Result<Vec<u8>> {
    let mut output = Vec::new();
    BufReader::new(reader)
        .take((MAX_LIFECYCLE_OUTPUT_BYTES + 1) as u64)
        .read_until(b'\n', &mut output)?;
    if output.len() > MAX_LIFECYCLE_OUTPUT_BYTES || !output.ends_with(b"\n") {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "provider readiness exceeded its boundary",
        ));
    }
    Ok(output)
}

fn provider_is_running(state: &DesktopState) -> Result<bool, String> {
    let mut slot = state.provider.lock().map_err(|_| lock_error())?;
    reconcile_pending_registration(&mut slot)?;
    let Some(provider) = slot.managed.as_mut() else {
        return Ok(false);
    };
    if provider
        .child
        .try_wait()
        .map_err(|_| "The Local Connect provider status is unavailable.".to_owned())?
        .is_some()
    {
        reconcile_managed_provider_termination(&mut slot)?;
        return Ok(false);
    }
    Ok(provider.ready)
}

fn connect_status_from(
    entitlement: Result<EntitlementStatus, String>,
    running: bool,
) -> ConnectStatus {
    let entitlement = entitlement.unwrap_or_else(|_| EntitlementStatus {
        state: "unavailable".to_owned(),
        active: false,
    });
    ConnectStatus {
        entitlement_state: entitlement.state,
        entitlement_active: entitlement.active,
        provider_running: running,
        provider_managed: running,
    }
}

fn connect_status_value(app: &AppHandle, state: &DesktopState) -> Result<ConnectStatus, String> {
    let entitlement = read_entitlement_status(app);
    let running = provider_is_running(state)?;
    Ok(connect_status_from(entitlement, running))
}

fn require_active_entitlement(entitlement: &EntitlementStatus) -> Result<(), String> {
    if !entitlement.active {
        return Err("Install an active Local Connect entitlement before starting.".to_owned());
    }
    Ok(())
}

fn begin_provider_start(state: &DesktopState) -> Result<u64, String> {
    let mut lifecycle = state.provider.lock().map_err(|_| lock_error())?;
    if lifecycle.active_start.is_some() {
        return Err("The Local Connect provider is already starting.".to_owned());
    }
    lifecycle.next_attempt = lifecycle.next_attempt.wrapping_add(1);
    if lifecycle.next_attempt == 0 {
        lifecycle.next_attempt = 1;
    }
    let attempt = lifecycle.next_attempt;
    lifecycle.active_start = Some(attempt);
    Ok(attempt)
}

fn finish_provider_start(state: &DesktopState, attempt: u64) -> Result<(), String> {
    let mut lifecycle = state.provider.lock().map_err(|_| lock_error())?;
    if lifecycle.active_start == Some(attempt) {
        lifecycle.active_start = None;
    }
    Ok(())
}

fn require_current_provider_start(state: &DesktopState, attempt: u64) -> Result<(), String> {
    let lifecycle = state.provider.lock().map_err(|_| lock_error())?;
    if lifecycle.active_start != Some(attempt) {
        return Err("The Local Connect provider start was cancelled.".to_owned());
    }
    Ok(())
}

fn launch_managed_provider(
    mut command: Command,
    registration_cleanup: Option<Command>,
    state: &DesktopState,
    startup_timeout: Duration,
    attempt: u64,
) -> Result<bool, String> {
    let mut slot = state.provider.lock().map_err(|_| lock_error())?;
    reconcile_pending_registration(&mut slot)?;
    if slot.active_start != Some(attempt) {
        return Err("The Local Connect provider start was cancelled.".to_owned());
    }
    if let Some(provider) = slot.managed.as_mut() {
        if provider
            .child
            .try_wait()
            .map_err(|_| "The Local Connect provider status is unavailable.".to_owned())?
            .is_none()
        {
            return if provider.ready {
                Ok(false)
            } else {
                Err("The Local Connect provider is already starting.".to_owned())
            };
        }
        reconcile_managed_provider_termination(&mut slot)?;
    }

    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    hide_console_window(&mut command);
    let mut child = command
        .spawn()
        .map_err(|_| "The Local Connect provider could not start.".to_owned())?;
    let Some(stdin) = child.stdin.take() else {
        let _ = force_reap(&mut child);
        return Err("The Local Connect provider control pipe is unavailable.".to_owned());
    };
    let Some(stdout) = child.stdout.take() else {
        let _ = force_reap(&mut child);
        return Err("The Local Connect provider readiness pipe is unavailable.".to_owned());
    };
    let (sender, receiver) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let _ = sender.send(read_provider_readiness(stdout));
    });
    slot.managed = Some(ManagedProvider {
        attempt,
        child,
        stdin: Some(stdin),
        registration_cleanup,
        ready: false,
    });
    drop(slot);

    let readiness = match receiver.recv_timeout(startup_timeout) {
        Ok(Ok(line)) => parse_provider_readiness(&line),
        Ok(Err(_)) => Err("The Local Connect provider readiness was invalid.".to_owned()),
        Err(mpsc::RecvTimeoutError::Timeout) => {
            Err("The Local Connect provider did not become ready in time.".to_owned())
        }
        Err(mpsc::RecvTimeoutError::Disconnected) => {
            Err("The Local Connect provider stopped during startup.".to_owned())
        }
    };
    if let Err(error) = readiness {
        stop_provider_attempt_with_timeout(state, attempt, Duration::ZERO).map_err(|_| {
            "The Local Connect provider could not be stopped after failed startup.".to_owned()
        })?;
        return Err(error);
    }
    thread::sleep(Duration::from_millis(50));
    let mut slot = state.provider.lock().map_err(|_| lock_error())?;
    if slot.active_start != Some(attempt) {
        drop(slot);
        stop_provider_attempt_with_timeout(state, attempt, Duration::ZERO).map_err(|_| {
            "The Local Connect provider could not be stopped after cancellation.".to_owned()
        })?;
        return Err("The Local Connect provider start was cancelled.".to_owned());
    }
    let Some(provider) = slot.managed.as_mut() else {
        return Err("The Local Connect provider stopped during startup.".to_owned());
    };
    if provider.attempt != attempt {
        return Err("The Local Connect provider start was superseded.".to_owned());
    }
    match provider.child.try_wait() {
        Ok(Some(_)) => {
            reconcile_managed_provider_termination(&mut slot)?;
            return Err("The Local Connect provider stopped during startup.".to_owned());
        }
        Ok(None) => provider.ready = true,
        Err(_) => {
            force_reap(&mut provider.child).map_err(|_| {
                "The Local Connect provider could not be stopped after a status failure.".to_owned()
            })?;
            reconcile_managed_provider_termination(&mut slot)?;
            return Err("The Local Connect provider status is unavailable.".to_owned());
        }
    }
    Ok(true)
}

fn start_connect_provider(
    app: &AppHandle,
    state: &DesktopState,
    attempt: u64,
) -> Result<ConnectStatus, String> {
    let result = (|| {
        let entitlement = read_entitlement_status(app)?;
        require_active_entitlement(&entitlement)?;
        require_current_provider_start(state, attempt)?;
        let mut command = base_engine_command(app)?;
        let mut cleanup = base_engine_command(app)?;
        let registration_token = new_desktop_registration_token();
        command.env(DESKTOP_REGISTRATION_TOKEN_ENV, &registration_token);
        cleanup
            .arg("cleanup-registration")
            .env(DESKTOP_REGISTRATION_TOKEN_ENV, registration_token);
        command.args(["serve", "--desktop-managed"]);
        launch_managed_provider(
            command,
            Some(cleanup),
            state,
            CONNECT_STARTUP_TIMEOUT,
            attempt,
        )?;
        connect_status_value(app, state)
    })();
    finish_provider_start(state, attempt)?;
    result
}

fn stop_managed_provider_locked(
    slot: &mut ProviderLifecycle,
    shutdown_timeout: Duration,
) -> Result<bool, String> {
    reconcile_pending_registration(slot)?;
    let Some(provider) = slot.managed.as_mut() else {
        return Ok(false);
    };
    if provider
        .child
        .try_wait()
        .map_err(|_| "The Local Connect provider status is unavailable.".to_owned())?
        .is_some()
    {
        reconcile_managed_provider_termination(slot)?;
        return Ok(false);
    }
    if let Some(mut stdin) = provider.stdin.take() {
        let _ = stdin.write_all(b"stop\n");
        let _ = stdin.flush();
    }
    let deadline = Instant::now() + shutdown_timeout;
    loop {
        if provider
            .child
            .try_wait()
            .map_err(|_| "The Local Connect provider status is unavailable.".to_owned())?
            .is_some()
        {
            reconcile_managed_provider_termination(slot)?;
            return Ok(true);
        }
        if Instant::now() >= deadline {
            force_reap(&mut provider.child)
                .map_err(|_| "The Local Connect provider could not be stopped.".to_owned())?;
            reconcile_managed_provider_termination(slot)?;
            return Ok(true);
        }
        thread::sleep(Duration::from_millis(50));
    }
}

fn stop_provider_attempt_with_timeout(
    state: &DesktopState,
    attempt: u64,
    shutdown_timeout: Duration,
) -> Result<bool, String> {
    let mut slot = state.provider.lock().map_err(|_| lock_error())?;
    if slot.managed.as_ref().map(|provider| provider.attempt) != Some(attempt) {
        return Ok(false);
    }
    stop_managed_provider_locked(&mut slot, shutdown_timeout)
}

fn stop_connect_provider_with_timeout(
    state: &DesktopState,
    shutdown_timeout: Duration,
) -> Result<bool, String> {
    let mut slot = state.provider.lock().map_err(|_| lock_error())?;
    slot.active_start = None;
    stop_managed_provider_locked(&mut slot, shutdown_timeout)
}

fn stop_connect_provider(state: &DesktopState) -> Result<bool, String> {
    stop_connect_provider_with_timeout(state, CONNECT_SHUTDOWN_TIMEOUT)
}

fn prepare_window_close_with_timeout(
    state: &DesktopState,
    shutdown_timeout: Duration,
) -> Result<(), String> {
    let _ = request_engine_cancellation(state);
    stop_connect_provider_with_timeout(state, shutdown_timeout).map(|_| ())
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

    let mut command = base_engine_command(app)?;
    command.arg("desktop");
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
async fn connect_status(
    app: AppHandle,
    state: State<'_, Arc<DesktopState>>,
) -> Result<ConnectStatus, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || connect_status_value(&app, &state))
        .await
        .map_err(|_| "The Local Connect status check stopped unexpectedly.".to_owned())?
}

#[tauri::command]
async fn install_connect_entitlement(
    app: AppHandle,
    state: State<'_, Arc<DesktopState>>,
) -> Result<Option<ConnectStatus>, String> {
    let Some(path) = rfd::FileDialog::new()
        .add_filter("Local Connect entitlement", &["json"])
        .pick_file()
    else {
        return Ok(None);
    };
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let result = run_cli_json(
            &app,
            &[
                OsString::from("entitlement"),
                OsString::from("install"),
                path.into_os_string(),
            ],
        )?;
        let entitlement = parse_entitlement_status(result)?;
        let running = provider_is_running(&state)?;
        Ok(Some(ConnectStatus {
            entitlement_state: entitlement.state,
            entitlement_active: entitlement.active,
            provider_running: running,
            provider_managed: running,
        }))
    })
    .await
    .map_err(|_| "The Local Connect activation stopped unexpectedly.".to_owned())?
}

#[tauri::command]
async fn start_connect(
    app: AppHandle,
    state: State<'_, Arc<DesktopState>>,
) -> Result<ConnectStatus, String> {
    let state = state.inner().clone();
    let attempt = begin_provider_start(&state)?;
    let worker_state = state.clone();
    match tauri::async_runtime::spawn_blocking(move || {
        start_connect_provider(&app, &worker_state, attempt)
    })
    .await
    {
        Ok(result) => result,
        Err(_) => {
            finish_provider_start(&state, attempt)?;
            Err("The Local Connect provider start stopped unexpectedly.".to_owned())
        }
    }
}

#[tauri::command]
async fn stop_connect(
    app: AppHandle,
    state: State<'_, Arc<DesktopState>>,
) -> Result<ConnectStatus, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        stop_connect_provider(&state)?;
        connect_status_value(&app, &state)
    })
    .await
    .map_err(|_| "The Local Connect provider stop stopped unexpectedly.".to_owned())?
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
    let bytes = read_bounded_file(&path, MAX_PROSPECT_BYTES).map_err(|error| {
        if error.kind() == io::ErrorKind::InvalidData {
            "The selected prospect file is too large or invalid.".to_owned()
        } else {
            "The selected prospect file could not be read.".to_owned()
        }
    })?;
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
    write_atomic(&path, &bytes).map_err(|_| "Prospect JSON could not be saved.".to_owned())?;
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
    write_atomic(&path, &cached.bytes)
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
            connect_status,
            install_connect_entitlement,
            start_connect,
            stop_connect,
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let state = window.state::<Arc<DesktopState>>();
                if prepare_window_close_with_timeout(&state, CONNECT_SHUTDOWN_TIMEOUT).is_err() {
                    api.prevent_close();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("Website Generator desktop failed to start");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_provider(script: &str) -> Command {
        let mut command = Command::new("python");
        command.args(["-u", "-c", script]);
        command
    }

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
    fn bounded_file_reader_rechecks_the_open_handle_and_caps_the_read() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("prospect.json");
        fs::write(&path, b"abcd").unwrap();
        assert_eq!(read_bounded_file(&path, 4).unwrap(), b"abcd");

        fs::write(&path, b"abcde").unwrap();
        assert_eq!(
            read_bounded_file(&path, 4).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
    }

    #[test]
    fn atomic_write_replaces_only_after_the_new_bytes_are_complete() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("prospect.json");
        fs::write(&path, b"original").unwrap();

        write_atomic(&path, b"replacement").unwrap();

        assert_eq!(fs::read(&path).unwrap(), b"replacement");
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
    #[ignore = "launched explicitly by the Windows process-tree test"]
    fn windows_descendant_fixture() {
        let pid_path = std::env::var_os("WEBSITE_GENERATOR_DESCENDANT_PID_PATH")
            .expect("the descendant fixture requires a PID path");
        let mut command = Command::new("cmd.exe");
        command
            .args(["/D", "/S", "/C", "ping -n 30 127.0.0.1 >NUL"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        hide_console_window(&mut command);
        let mut descendant = command.spawn().unwrap();
        fs::write(pid_path, descendant.id().to_string()).unwrap();
        let status = descendant.wait().unwrap();
        assert!(status.success());
    }

    #[cfg(windows)]
    #[test]
    fn windows_cancellation_terminates_descendants() {
        let directory = tempfile::tempdir().unwrap();
        let pid_path = directory.path().join("descendant.pid");
        let test_binary = std::env::current_exe().unwrap();
        let mut command = Command::new(test_binary);
        command
            .args([
                "--ignored",
                "--exact",
                "tests::windows_descendant_fixture",
                "--nocapture",
            ])
            .env("WEBSITE_GENERATOR_DESCENDANT_PID_PATH", &pid_path)
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

    #[test]
    fn entitlement_status_requires_an_exact_consistent_shape() {
        assert_eq!(
            parse_entitlement_status(json!({"state": "active", "active": true})).unwrap(),
            EntitlementStatus {
                state: "active".to_owned(),
                active: true,
            }
        );
        assert!(parse_entitlement_status(json!({"state": "missing", "active": false})).is_ok());
        assert!(parse_entitlement_status(json!({"state": "active", "active": false})).is_err());
        assert!(parse_entitlement_status(json!({"state": "unknown", "active": false})).is_err());
        assert!(
            parse_entitlement_status(
                json!({"state": "missing", "active": false, "detail": "secret"})
            )
            .is_err()
        );
    }

    #[test]
    fn provider_readiness_requires_exactly_ready_true() {
        assert!(parse_provider_readiness(b"{\"ready\":true}\n").is_ok());
        assert!(parse_provider_readiness(b"{\"ready\":false}\n").is_err());
        assert!(parse_provider_readiness(b"{\"ready\":true,\"extra\":1}\n").is_err());
        assert!(parse_provider_readiness(b"{}\n").is_err());
        assert!(parse_provider_readiness(b"{\"ready\":true}\n{}\n").is_err());
    }

    #[test]
    fn desktop_registration_tokens_are_valid_and_rotate() {
        let first = new_desktop_registration_token();
        let second = new_desktop_registration_token();

        assert_eq!(first.len(), 64);
        assert!(first.bytes().all(|byte| byte.is_ascii_hexdigit()));
        assert_ne!(first, second);
    }

    #[test]
    fn provider_readiness_reader_enforces_its_line_boundary() {
        struct ReadyWithoutEof(bool);

        impl Read for ReadyWithoutEof {
            fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
                if self.0 {
                    panic!("readiness must not wait for EOF after the first line");
                }
                self.0 = true;
                let line = b"{\"ready\":true}\n";
                buffer[..line.len()].copy_from_slice(line);
                Ok(line.len())
            }
        }

        assert_eq!(
            read_provider_readiness(ReadyWithoutEof(false)).unwrap(),
            b"{\"ready\":true}\n"
        );
        let maximum_line = format!("{}\n", "x".repeat(MAX_LIFECYCLE_OUTPUT_BYTES - 1));
        assert_eq!(
            read_provider_readiness(maximum_line.as_bytes())
                .unwrap()
                .len(),
            MAX_LIFECYCLE_OUTPUT_BYTES
        );
        let oversized = format!("{}\n", "x".repeat(MAX_LIFECYCLE_OUTPUT_BYTES));
        assert_eq!(
            read_provider_readiness(oversized.as_bytes())
                .unwrap_err()
                .kind(),
            io::ErrorKind::InvalidData
        );
        assert_eq!(
            read_provider_readiness(&b"{\"ready\":true}"[..])
                .unwrap_err()
                .kind(),
            io::ErrorKind::InvalidData
        );
    }

    #[test]
    fn inactive_entitlement_cannot_start_connect() {
        assert!(
            require_active_entitlement(&EntitlementStatus {
                state: "missing".to_owned(),
                active: false,
            })
            .is_err()
        );
        assert!(
            require_active_entitlement(&EntitlementStatus {
                state: "active".to_owned(),
                active: true,
            })
            .is_ok()
        );
    }

    #[test]
    fn entitlement_failure_does_not_hide_a_running_managed_provider() {
        let status = connect_status_from(Err("private detail".to_owned()), true);

        assert_eq!(status.entitlement_state, "unavailable");
        assert!(!status.entitlement_active);
        assert!(status.provider_running);
        assert!(status.provider_managed);

        let expired = connect_status_from(
            Ok(EntitlementStatus {
                state: "expired".to_owned(),
                active: false,
            }),
            true,
        );
        assert_eq!(expired.entitlement_state, "expired");
        assert!(!expired.entitlement_active);
        assert!(expired.provider_running);
        assert!(expired.provider_managed);
    }

    #[test]
    fn managed_provider_start_is_idempotent_and_stop_reaps_the_child() {
        let state = DesktopState::default();
        let provider = fixture_provider(
            "import sys; print('{\"ready\":true}', flush=True); sys.stdin.readline()",
        );
        let attempt = begin_provider_start(&state).unwrap();
        assert!(
            launch_managed_provider(provider, None, &state, Duration::from_secs(2), attempt)
                .unwrap()
        );
        finish_provider_start(&state, attempt).unwrap();
        assert!(provider_is_running(&state).unwrap());

        let duplicate = Command::new("executable-that-must-not-be-started");
        let duplicate_attempt = begin_provider_start(&state).unwrap();
        assert!(
            !launch_managed_provider(
                duplicate,
                None,
                &state,
                Duration::from_millis(1),
                duplicate_attempt,
            )
            .unwrap()
        );
        finish_provider_start(&state, duplicate_attempt).unwrap();

        assert!(stop_connect_provider(&state).unwrap());
        assert!(!provider_is_running(&state).unwrap());
        assert!(!stop_connect_provider(&state).unwrap());
    }

    #[test]
    fn managed_provider_timeout_and_early_exit_leave_no_child() {
        let state = DesktopState::default();
        let timeout = fixture_provider("import time; time.sleep(2)");
        let attempt = begin_provider_start(&state).unwrap();
        let error =
            launch_managed_provider(timeout, None, &state, Duration::from_millis(20), attempt)
                .unwrap_err();
        finish_provider_start(&state, attempt).unwrap();
        assert!(error.contains("ready in time"));
        assert!(!provider_is_running(&state).unwrap());

        let early_exit = fixture_provider("pass");
        let attempt = begin_provider_start(&state).unwrap();
        assert!(
            launch_managed_provider(early_exit, None, &state, Duration::from_secs(2), attempt,)
                .is_err()
        );
        finish_provider_start(&state, attempt).unwrap();
        assert!(!provider_is_running(&state).unwrap());
    }

    #[test]
    fn reserved_attempt_stopped_before_worker_runs_cannot_spawn_a_child() {
        let state = Arc::new(DesktopState::default());
        let attempt = begin_provider_start(&state).unwrap();
        let (release, wait) = mpsc::sync_channel(0);
        let worker_state = state.clone();
        let worker = thread::spawn(move || {
            wait.recv().unwrap();
            let command = Command::new("executable-that-must-not-be-started");
            launch_managed_provider(
                command,
                None,
                &worker_state,
                Duration::from_secs(2),
                attempt,
            )
        });

        assert!(!stop_connect_provider_with_timeout(&state, Duration::ZERO).unwrap());
        release.send(()).unwrap();
        let error = worker.join().unwrap().unwrap_err();

        assert!(error.contains("cancelled"));
        assert!(state.provider.lock().unwrap().managed.is_none());
    }

    #[test]
    fn managed_provider_can_be_stopped_while_starting() {
        let state = Arc::new(DesktopState::default());
        let start_state = state.clone();
        let attempt = begin_provider_start(&state).unwrap();
        let start = thread::spawn(move || {
            let provider = fixture_provider("import time; time.sleep(2)");
            launch_managed_provider(
                provider,
                None,
                &start_state,
                Duration::from_secs(2),
                attempt,
            )
        });

        let registration_deadline = Instant::now() + Duration::from_secs(1);
        while state.provider.lock().unwrap().managed.is_none() {
            assert!(
                Instant::now() < registration_deadline,
                "starting provider was not registered"
            );
            thread::sleep(Duration::from_millis(5));
        }
        assert!(!provider_is_running(&state).unwrap());

        assert!(stop_connect_provider_with_timeout(&state, Duration::from_millis(20)).unwrap());
        assert!(start.join().unwrap().is_err());
        assert!(state.provider.lock().unwrap().managed.is_none());
    }

    #[test]
    fn failed_attempt_cleanup_does_not_stop_a_newer_provider() {
        let state = DesktopState::default();
        let stale_attempt = begin_provider_start(&state).unwrap();
        finish_provider_start(&state, stale_attempt).unwrap();

        let current_attempt = begin_provider_start(&state).unwrap();
        let provider = fixture_provider(
            "import sys; print('{\"ready\":true}', flush=True); sys.stdin.readline()",
        );
        assert!(
            launch_managed_provider(
                provider,
                None,
                &state,
                Duration::from_secs(2),
                current_attempt,
            )
            .unwrap()
        );
        finish_provider_start(&state, current_attempt).unwrap();

        assert!(
            !stop_provider_attempt_with_timeout(&state, stale_attempt, Duration::ZERO).unwrap()
        );
        assert!(provider_is_running(&state).unwrap());
        assert!(stop_connect_provider(&state).unwrap());
    }

    #[test]
    fn managed_provider_forced_stop_reports_the_reconciled_state() {
        let state = DesktopState::default();
        let directory = tempfile::tempdir().unwrap();
        let cleanup_path = directory.path().join("cleaned-token");
        let provider =
            fixture_provider("import time; print('{\"ready\":true}', flush=True); time.sleep(2)");
        let mut cleanup = fixture_provider(
            "import os, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(os.environ[sys.argv[2]])",
        );
        cleanup
            .args([
                cleanup_path.as_os_str(),
                DESKTOP_REGISTRATION_TOKEN_ENV.as_ref(),
            ])
            .env(DESKTOP_REGISTRATION_TOKEN_ENV, "test-registration-token");
        let attempt = begin_provider_start(&state).unwrap();
        assert!(
            launch_managed_provider(
                provider,
                Some(cleanup),
                &state,
                Duration::from_secs(2),
                attempt,
            )
            .unwrap()
        );
        finish_provider_start(&state, attempt).unwrap();
        assert!(stop_connect_provider_with_timeout(&state, Duration::from_millis(20)).unwrap());
        assert!(!provider_is_running(&state).unwrap());
        assert_eq!(
            fs::read_to_string(cleanup_path).unwrap(),
            "test-registration-token"
        );
    }

    #[test]
    fn failed_window_close_cleanup_is_retained_and_retried_before_close() {
        let state = DesktopState::default();
        let directory = tempfile::tempdir().unwrap();
        let cleanup_path = directory.path().join("cleanup-attempt");
        let provider =
            fixture_provider("import time; print('{\"ready\":true}', flush=True); time.sleep(2)");
        let mut cleanup = fixture_provider(
            "import pathlib, sys; path = pathlib.Path(sys.argv[1]); first = not path.exists(); path.write_text('attempted' if first else 'reconciled'); raise SystemExit(1 if first else 0)",
        );
        cleanup.arg(&cleanup_path);
        let attempt = begin_provider_start(&state).unwrap();
        assert!(
            launch_managed_provider(
                provider,
                Some(cleanup),
                &state,
                Duration::from_secs(2),
                attempt,
            )
            .unwrap()
        );
        finish_provider_start(&state, attempt).unwrap();

        assert!(prepare_window_close_with_timeout(&state, Duration::from_millis(20)).is_err());
        {
            let lifecycle = state.provider.lock().unwrap();
            assert!(lifecycle.managed.is_none());
            assert!(lifecycle.pending_registration_cleanup.is_some());
        }
        assert!(prepare_window_close_with_timeout(&state, Duration::ZERO).is_ok());
        assert!(
            state
                .provider
                .lock()
                .unwrap()
                .pending_registration_cleanup
                .is_none()
        );
        assert_eq!(fs::read_to_string(cleanup_path).unwrap(), "reconciled");
    }

    #[test]
    fn connect_command_timeout_kills_and_reaps_the_child() {
        let mut child = fixture_provider("import time; time.sleep(2)")
            .spawn()
            .unwrap();
        let error = wait_for_connect_command(&mut child, Duration::from_millis(20)).unwrap_err();
        assert!(error.contains("finish in time"));
        assert!(child.try_wait().unwrap().is_some());

        let mut completed = fixture_provider("pass").spawn().unwrap();
        assert!(
            wait_for_connect_command(&mut completed, Duration::from_secs(2))
                .unwrap()
                .success()
        );
    }
}
