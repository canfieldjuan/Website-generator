#!/usr/bin/env python3
"""Run the owner-private Website Redesign Local Connect v2 provider."""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

import uvicorn

from lib.connect_store import ConnectStore
from lib.connect_v2 import (
    DEFAULT_LOCAL_MODEL,
    ProviderLock,
    ProviderRuntime,
    create_app,
    default_runtime_dir,
    default_state_dir,
    new_bearer_token,
    registration_document,
    remove_registration_if_owned,
    write_registration,
)
from lib.generation import (
    GenerationConfigurationError,
    GenerationProviderUnavailable,
    preflight_generation_provider,
    resolve_generation_config,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Expose local JSON-to-HTML generation through Local Connect v2. "
            "LM Studio and qwen/qwen3.8-27b must already be running."
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        runtime_dir = args.runtime_dir or default_runtime_dir()
        state_dir = args.state_dir or default_state_dir()
    except RuntimeError as exc:
        print(f"Connect provider configuration failed: {exc}", file=sys.stderr)
        return 2
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)

    try:
        generation_config = resolve_generation_config("local", DEFAULT_LOCAL_MODEL)
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
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
        store = ConnectStore(state_dir / "connect-v2.sqlite3")
        runtime = ProviderRuntime(store)
        app = create_app(runtime, token)
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
        config = uvicorn.Config(
            app,
            log_level="info",
            access_log=False,
            server_header=False,
        )
        uvicorn.Server(config).run(sockets=[listener])
        return 0
    finally:
        if registration_path is not None:
            remove_registration_if_owned(registration_path, token)
        if runtime is not None:
            runtime.close()
        listener.close()
        provider_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
