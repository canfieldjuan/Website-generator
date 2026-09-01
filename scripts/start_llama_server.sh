#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Start the Website Generator's standalone llama.cpp runtime.

Required:
  LLAMA_CPP_MODEL_PATH      Absolute path to the Qwen GGUF file.

Optional:
  LLAMA_CPP_SERVER_BIN      llama-server executable (default: llama-server on PATH)
  LLAMA_CPP_HOST            Loopback bind host (default: 127.0.0.1)
  LLAMA_CPP_PORT            Port (default: 8080)
  LLAMA_CPP_CONTEXT_SIZE    Context tokens (default: 49152)
  LLAMA_CPP_GPU_LAYERS      GPU layers: auto, all, or a non-negative integer (default: all)
  LLAMA_CPP_CACHE_TYPE_K    Key-cache type (default: q8_0)
  LLAMA_CPP_CACHE_TYPE_V    Value-cache type (default: q8_0)
  LLAMA_CPP_SERVER_TIMEOUT  Server timeout seconds (default: 7200)
  LOCAL_GENERATION_MODEL    Served model alias (default: qwen/qwen3.8-27b)
  LOCAL_GENERATION_API_KEY  Optional bearer key; also used by the generator
  LLAMA_CPP_API_KEY         Alias for LOCAL_GENERATION_API_KEY

This script binds only to loopback, disables the Web UI and model reasoning,
and never downloads a model or falls back to a cloud provider.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi
if (( $# != 0 )); then
    usage >&2
    exit 2
fi

server_bin="${LLAMA_CPP_SERVER_BIN:-llama-server}"
model_path="${LLAMA_CPP_MODEL_PATH:-}"
host="${LLAMA_CPP_HOST:-127.0.0.1}"
port="${LLAMA_CPP_PORT:-8080}"
context_size="${LLAMA_CPP_CONTEXT_SIZE:-49152}"
gpu_layers="${LLAMA_CPP_GPU_LAYERS:-all}"
cache_type_k="${LLAMA_CPP_CACHE_TYPE_K:-q8_0}"
cache_type_v="${LLAMA_CPP_CACHE_TYPE_V:-q8_0}"
server_timeout="${LLAMA_CPP_SERVER_TIMEOUT:-7200}"
model_alias="${LOCAL_GENERATION_MODEL:-qwen/qwen3.8-27b}"
api_key="${LOCAL_GENERATION_API_KEY:-${LLAMA_CPP_API_KEY:-}}"

if [[ "$server_bin" == */* ]]; then
    if [[ ! -x "$server_bin" ]]; then
        printf 'LLAMA_CPP_SERVER_BIN is not executable: %s\n' "$server_bin" >&2
        exit 2
    fi
elif ! command -v "$server_bin" >/dev/null 2>&1; then
    printf 'llama-server was not found. Set LLAMA_CPP_SERVER_BIN.\n' >&2
    exit 2
fi

if [[ -z "$model_path" || ! -f "$model_path" ]]; then
    printf 'Set LLAMA_CPP_MODEL_PATH to an existing GGUF file.\n' >&2
    exit 2
fi
if [[ "$host" != "127.0.0.1" && "$host" != "localhost" && "$host" != "::1" ]]; then
    printf 'LLAMA_CPP_HOST must be a loopback host.\n' >&2
    exit 2
fi
if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    printf 'LLAMA_CPP_PORT must be an integer from 1 through 65535.\n' >&2
    exit 2
fi
if [[ ! "$context_size" =~ ^[0-9]+$ ]] || (( context_size < 1 )); then
    printf 'LLAMA_CPP_CONTEXT_SIZE must be a positive integer.\n' >&2
    exit 2
fi
if [[ ! "$gpu_layers" =~ ^(auto|all|[0-9]+)$ ]]; then
    printf 'LLAMA_CPP_GPU_LAYERS must be auto, all, or a non-negative integer.\n' >&2
    exit 2
fi
if [[ ! "$server_timeout" =~ ^[0-9]+$ ]] || (( server_timeout < 1 )); then
    printf 'LLAMA_CPP_SERVER_TIMEOUT must be a positive integer.\n' >&2
    exit 2
fi

args=(
    "$server_bin"
    --model "$model_path"
    --alias "$model_alias"
    --host "$host"
    --port "$port"
    --ctx-size "$context_size"
    --n-gpu-layers "$gpu_layers"
    --cache-type-k "$cache_type_k"
    --cache-type-v "$cache_type_v"
    --timeout "$server_timeout"
    --no-webui
    --reasoning off
    --reasoning-format deepseek
    --reasoning-budget 0
)
if [[ -n "$api_key" ]]; then
    args+=(--api-key "$api_key")
fi

exec "${args[@]}"
