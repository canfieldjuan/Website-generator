#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Start the Website Generator's standalone vLLM runtime.

Required:
  VLLM_MODEL_PATH              Local model file or directory.

Optional:
  VLLM_BIN                     vLLM executable (default: vllm on PATH)
  VLLM_HOST                    Loopback bind host (default: 127.0.0.1)
  VLLM_PORT                    Port (default: 8000)
  VLLM_MAX_MODEL_LEN           Maximum context tokens (default: 49152)
  VLLM_GPU_MEMORY_UTILIZATION  GPU memory fraction, >0 through 1 (default: 0.90)
  VLLM_TENSOR_PARALLEL_SIZE    GPU count used by vLLM (default: 1)
  VLLM_CUDA_VISIBLE_DEVICES    Comma-separated CUDA device indexes (default: 0)
  LOCAL_GENERATION_MODEL       Served model alias (default: qwen/qwen3.8-27b)
  LOCAL_GENERATION_API_KEY     Optional bearer key; also used by the generator
  VLLM_API_KEY                 Alias for LOCAL_GENERATION_API_KEY

This script binds only to loopback, disables request logging and model thinking,
uses zero CPU offload, and never downloads a model or falls back to a cloud
provider. The application never starts this process automatically.
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

vllm_bin="${VLLM_BIN:-vllm}"
model_path="${VLLM_MODEL_PATH:-}"
host="${VLLM_HOST:-127.0.0.1}"
port="${VLLM_PORT:-8000}"
max_model_len="${VLLM_MAX_MODEL_LEN:-49152}"
gpu_memory_utilization="${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
tensor_parallel_size="${VLLM_TENSOR_PARALLEL_SIZE:-1}"
cuda_visible_devices="${VLLM_CUDA_VISIBLE_DEVICES:-0}"
model_alias="${LOCAL_GENERATION_MODEL:-qwen/qwen3.8-27b}"
api_key="${LOCAL_GENERATION_API_KEY:-${VLLM_API_KEY:-}}"

if [[ "$vllm_bin" == */* ]]; then
    if [[ ! -x "$vllm_bin" ]]; then
        printf 'VLLM_BIN is not executable: %s\n' "$vllm_bin" >&2
        exit 2
    fi
elif ! command -v "$vllm_bin" >/dev/null 2>&1; then
    printf 'vLLM was not found. Set VLLM_BIN.\n' >&2
    exit 2
fi

if [[ -z "$model_path" || ! -e "$model_path" ]]; then
    printf 'Set VLLM_MODEL_PATH to an existing local model file or directory.\n' >&2
    exit 2
fi
if [[ "$host" != "127.0.0.1" && "$host" != "localhost" && "$host" != "::1" ]]; then
    printf 'VLLM_HOST must be a loopback host.\n' >&2
    exit 2
fi
if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    printf 'VLLM_PORT must be an integer from 1 through 65535.\n' >&2
    exit 2
fi
if [[ ! "$max_model_len" =~ ^[0-9]+$ ]] || (( max_model_len < 1 )); then
    printf 'VLLM_MAX_MODEL_LEN must be a positive integer.\n' >&2
    exit 2
fi
if [[ ! "$gpu_memory_utilization" =~ ^(0\.[0-9]*[1-9][0-9]*|1(\.0+)?)$ ]]; then
    printf 'VLLM_GPU_MEMORY_UTILIZATION must be greater than 0 and at most 1.\n' >&2
    exit 2
fi
if [[ ! "$tensor_parallel_size" =~ ^[0-9]+$ ]] || (( tensor_parallel_size < 1 )); then
    printf 'VLLM_TENSOR_PARALLEL_SIZE must be a positive integer.\n' >&2
    exit 2
fi
if [[ ! "$cuda_visible_devices" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
    printf 'VLLM_CUDA_VISIBLE_DEVICES must be comma-separated CUDA device indexes.\n' >&2
    exit 2
fi
IFS=',' read -r -a visible_devices <<< "$cuda_visible_devices"
if (( tensor_parallel_size > ${#visible_devices[@]} )); then
    printf 'VLLM_TENSOR_PARALLEL_SIZE cannot exceed visible CUDA devices.\n' >&2
    exit 2
fi

args=(
    "$vllm_bin"
    serve "$model_path"
    --served-model-name "$model_alias"
    --host "$host"
    --port "$port"
    --max-model-len "$max_model_len"
    --gpu-memory-utilization "$gpu_memory_utilization"
    --tensor-parallel-size "$tensor_parallel_size"
    --cpu-offload-gb 0
    --generation-config vllm
    --default-chat-template-kwargs '{"enable_thinking":false}'
    --enable-prefix-caching
    --disable-log-requests
)
if [[ -n "$api_key" ]]; then
    args+=(--api-key "$api_key")
fi

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="$cuda_visible_devices"
exec "${args[@]}"
