#!/usr/bin/env python3
"""Run the owner-private Website Redesign Local Connect v2 provider."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
from pathlib import Path
from typing import BinaryIO, TextIO

import uvicorn

from lib.connect_entitlement import (
    EntitlementActivationError,
    entitlement_status,
    install_entitlement,
)
from lib.connect_store import ConnectStore
from lib.connect_windows import ensure_private_directory, local_app_data_root
from lib.desktop_protocol import run_desktop_stdio
from lib.connect_v2 import (
    ProviderLock,
    ProviderRuntime,
    acquire_registration_ownership,
    create_app,
    default_runtime_dir,
    default_state_dir,
    new_bearer_token,
    registration_document,
    remove_registration_for_token,
    remove_registration_if_owned,
    resolve_connect_generation_config,
    write_registration,
)
from lib.generation import (
    GenerationConfigurationError,
    GenerationProviderUnavailable,
    preflight_generation_provider,
)

DESKTOP_REGISTRATION_TOKEN_ENV = "WEBSITE_GENERATOR_DESKTOP_REGISTRATION_TOKEN"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Expose local JSON-to-HTML generation through Local Connect v2. "
            "Ollama must already serve the configured model on loopback."
        )
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        help="Override the Local Connect v2 providers directory.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        help="Override the provider's durable state directory.",
    )
    commands = parser.add_subparsers(dest="command")
    entitlement = commands.add_parser(
        "entitlement",
        help="Inspect or install the shared Local Connect entitlement.",
    )
    entitlement_commands = entitlement.add_subparsers(
        dest="entitlement_command", required=True
    )
    entitlement_commands.add_parser(
        "status",
        help="Report whether Local Connect capability exchange is active.",
    )
    install = entitlement_commands.add_parser(
        "install",
        help="Install an acquired signed entitlement from a selected file.",
    )
    install.add_argument("source", type=Path)
    commands.add_parser(
        "desktop",
        help="Handle one private desktop JSON request on stdin.",
    )
    serve = commands.add_parser(
        "serve",
        help="Run the Local Connect provider.",
    )
    serve.add_argument(
        "--desktop-managed",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    commands.add_parser("cleanup-registration", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def bind_loopback_listener(backlog: int) -> socket.socket:
    """Return a loopback socket that accepts connections before discovery."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(backlog)
        listener.setblocking(False)
        return listener
    except Exception:
        listener.close()
        raise


def _run_entitlement_command(args: argparse.Namespace) -> int:
    try:
        if args.entitlement_command == "status":
            result = entitlement_status()
        else:
            result = install_entitlement(args.source)
    except EntitlementActivationError as exc:
        print(
            json.dumps(
                {"error": {"code": exc.code, "message": str(exc)}},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def watch_desktop_shutdown(server: uvicorn.Server, source: BinaryIO) -> None:
    """Ask a desktop-managed server to exit when its owner stops or disappears."""
    try:
        signal = source.readline()
    except (OSError, ValueError):
        signal = b""
    if signal in (b"", b"stop\n", b"stop\r\n"):
        server.should_exit = True


def start_desktop_shutdown_watcher(
    server: uvicorn.Server, source: BinaryIO
) -> threading.Thread:
    watcher = threading.Thread(
        target=watch_desktop_shutdown,
        args=(server, source),
        name="desktop-connect-shutdown",
        daemon=True,
    )
    watcher.start()
    return watcher


def emit_desktop_readiness(output: TextIO) -> None:
    """Write and flush the one desktop handshake without closing stdout."""
    output.write('{"ready":true}\n')
    output.flush()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    desktop_registration_token = os.environ.pop(
        DESKTOP_REGISTRATION_TOKEN_ENV, None
    )
    if getattr(args, "command", None) == "entitlement":
        return _run_entitlement_command(args)
    if getattr(args, "command", None) == "desktop":
        return run_desktop_stdio()

    if getattr(args, "command", None) == "cleanup-registration":
        try:
            runtime_dir = args.runtime_dir or default_runtime_dir()
            if not runtime_dir.is_absolute():
                raise RuntimeError("Connect runtime directory must be absolute.")
            if os.name == "nt":
                ensure_private_directory(runtime_dir, root=local_app_data_root())
            if desktop_registration_token is None:
                raise ValueError("Desktop registration ownership is unavailable.")
            removed = remove_registration_for_token(
                runtime_dir, desktop_registration_token
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"Connect registration cleanup failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"removed": removed}, separators=(",", ":")))
        return 0

    try:
        runtime_dir = args.runtime_dir or default_runtime_dir()
        state_dir = args.state_dir or default_state_dir()
        if not runtime_dir.is_absolute() or not state_dir.is_absolute():
            raise RuntimeError("Connect runtime and state directories must be absolute.")
        if os.name == "nt":
            windows_root = local_app_data_root()
            ensure_private_directory(runtime_dir, root=windows_root)
            ensure_private_directory(state_dir, root=windows_root)
    except (OSError, RuntimeError) as exc:
        print(f"Connect provider configuration failed: {exc}", file=sys.stderr)
        return 2
    if os.name != "nt":
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        state_dir.chmod(0o700)

    try:
        generation_config = resolve_connect_generation_config()
        preflight_generation_provider(generation_config)
    except (GenerationConfigurationError, GenerationProviderUnavailable) as exc:
        print(f"Connect provider preflight failed: {exc}", file=sys.stderr)
        return 2

    lock_path = state_dir / "provider.lock"
    try:
        provider_lock = ProviderLock(lock_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    desktop_managed = getattr(args, "desktop_managed", False)
    if desktop_managed and desktop_registration_token is None:
        print(
            "Connect provider configuration failed: desktop registration ownership is unavailable.",
            file=sys.stderr,
        )
        return 2

    runtime: ProviderRuntime | None = None
    registration_path: Path | None = None
    registration_ownership: ProviderLock | None = None
    token = desktop_registration_token if desktop_managed else new_bearer_token()
    listener: socket.socket | None = None
    desktop_stdout: TextIO | None = None
    desktop_output_sink: TextIO | None = None
    try:
        store = ConnectStore(state_dir / "connect-v2.sqlite3")
        try:
            registration_ownership = acquire_registration_ownership(
                runtime_dir, store.instance_id()
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        runtime = ProviderRuntime(store)
        app = create_app(runtime, token)
        config = uvicorn.Config(
            app,
            log_level="info",
            access_log=False,
            server_header=False,
        )
        server = uvicorn.Server(config)
        listener = bind_loopback_listener(config.backlog)
        port = int(listener.getsockname()[1])
        registration = registration_document(
            instance_id=runtime.instance_id,
            port=port,
            token=token,
        )
        registration_path = write_registration(runtime_dir, registration)
        if desktop_managed:
            input_stream = getattr(sys.stdin, "buffer", sys.stdin)
            start_desktop_shutdown_watcher(server, input_stream)
            desktop_stdout = sys.stdout
            desktop_output_sink = open(os.devnull, "w", encoding="utf-8")
            emit_desktop_readiness(desktop_stdout)
            sys.stdout = desktop_output_sink
        else:
            print(
                f"Website Redesign Connect v2 is available at "
                f"http://127.0.0.1:{port}/",
                flush=True,
            )
        server.run(sockets=[listener])
        return 0
    finally:
        if registration_path is not None:
            remove_registration_if_owned(registration_path, token)
        if runtime is not None:
            runtime.close()
        if listener is not None:
            listener.close()
        if registration_ownership is not None:
            registration_ownership.close()
        provider_lock.close()
        if desktop_output_sink is not None:
            if sys.stdout is desktop_output_sink and desktop_stdout is not None:
                sys.stdout = desktop_stdout
            desktop_output_sink.close()


if __name__ == "__main__":
    raise SystemExit(main())
