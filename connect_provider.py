#!/usr/bin/env python3
"""Run the owner-private Website Redesign Local Connect v2 provider."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn

from lib.connect_entitlement import (
    EntitlementActivationError,
    entitlement_status,
    install_entitlement,
)
from lib.connect_store import ConnectStore
from lib.connect_windows import ensure_private_directory, local_app_data_root
from lib.connect_v2 import (
    ProviderLock,
    ProviderRuntime,
    create_app,
    default_runtime_dir,
    default_state_dir,
    new_bearer_token,
    registration_document,
    remove_registration_if_owned,
    resolve_connect_generation_config,
    write_registration,
)
from lib.generation import (
    GenerationConfigurationError,
    GenerationProviderUnavailable,
    preflight_generation_provider,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Expose local JSON-to-HTML generation through Local Connect v2. "
            "Standalone vLLM must already serve qwen/qwen3.8-27b."
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if getattr(args, "command", None) == "entitlement":
        return _run_entitlement_command(args)
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

    runtime: ProviderRuntime | None = None
    registration_path: Path | None = None
    token = new_bearer_token()
    listener: socket.socket | None = None
    try:
        store = ConnectStore(state_dir / "connect-v2.sqlite3")
        runtime = ProviderRuntime(store)
        app = create_app(runtime, token)
        config = uvicorn.Config(
            app,
            log_level="info",
            access_log=False,
            server_header=False,
        )
        listener = bind_loopback_listener(config.backlog)
        port = int(listener.getsockname()[1])
        registration = registration_document(
            instance_id=runtime.instance_id,
            port=port,
            token=token,
        )
        registration_path = write_registration(runtime_dir, registration)
        print(
            f"Website Redesign Connect v2 is available at "
            f"http://127.0.0.1:{port}/"
        )
        uvicorn.Server(config).run(sockets=[listener])
        return 0
    finally:
        if registration_path is not None:
            remove_registration_if_owned(registration_path, token)
        if runtime is not None:
            runtime.close()
        if listener is not None:
            listener.close()
        provider_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
