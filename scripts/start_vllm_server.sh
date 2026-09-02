#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Start the Website Generator's standalone vLLM runtime.

Required:
  VLLM_MODEL_PATH              Local model file or directory.

Optional:
  VLLM_BIN                     vLLM executable (default: vllm on PATH)
  VLLM_TOKENIZER_PATH          Local tokenizer directory (required for GGUF)
  VLLM_GGUF_PLUGIN_PATH        Pinned Qwen adapter checkout (required for a
                               Qwen3.5/3.8 GGUF)
  VLLM_HOST                    Loopback bind host (default: 127.0.0.1)
  VLLM_PORT                    Port (default: 8000)
  VLLM_MAX_MODEL_LEN           Maximum context tokens (default: 49152)
  VLLM_GPU_MEMORY_UTILIZATION  GPU memory fraction, >0 through 1 (default: 0.90)
  VLLM_TENSOR_PARALLEL_SIZE    GPU count used by vLLM (default: 1)
  VLLM_CUDA_VISIBLE_DEVICES    Comma-separated CUDA device indexes (default: 0)
  VLLM_USE_FLASHINFER_SAMPLER  Optional sampler toggle (default: 0)
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
use_flashinfer_sampler="${VLLM_USE_FLASHINFER_SAMPLER:-0}"
model_alias="${LOCAL_GENERATION_MODEL:-qwen/qwen3.8-27b}"
api_key="${LOCAL_GENERATION_API_KEY:-${VLLM_API_KEY:-}}"
qwen_gguf_adapter_commit="d42c0510a1bc96526fd51481ffaf70d58435fd10"

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
if [[ "$use_flashinfer_sampler" != "0" && "$use_flashinfer_sampler" != "1" ]]; then
    printf 'VLLM_USE_FLASHINFER_SAMPLER must be 0 or 1.\n' >&2
    exit 2
fi
IFS=',' read -r -a visible_devices <<< "$cuda_visible_devices"
if (( tensor_parallel_size > ${#visible_devices[@]} )); then
    printf 'VLLM_TENSOR_PARALLEL_SIZE cannot exceed visible CUDA devices.\n' >&2
    exit 2
fi

configured_tokenizer_path="${VLLM_TOKENIZER_PATH:-}"
tokenizer_path=""
hf_config_path=""
chat_template_path=""
qwen_gguf_adapter_path=""
requires_qwen_gguf_adapter=0
if [[ "${model_path,,}" == *.gguf ]]; then
    if [[ -z "$configured_tokenizer_path" || ! -d "$configured_tokenizer_path" ]]; then
        printf 'Set VLLM_TOKENIZER_PATH to a local tokenizer directory for GGUF.\n' >&2
        exit 2
    fi
    tokenizer_path="$configured_tokenizer_path"
    for required_tokenizer_file in \
        config.json tokenizer.json tokenizer_config.json chat_template.jinja
    do
        if [[ ! -f "$tokenizer_path/$required_tokenizer_file" ]]; then
            printf 'VLLM_TOKENIZER_PATH is missing %s.\n' \
                "$required_tokenizer_file" >&2
            exit 2
        fi
    done
    hf_config_path="$(dirname "$model_path")"
    if [[ ! -f "$hf_config_path/config.json" ]]; then
        printf 'The GGUF model directory must contain config.json.\n' >&2
        exit 2
    fi
    shopt -s nullglob nocaseglob
    mmproj_siblings=("$hf_config_path"/*mmproj*.gguf)
    shopt -u nullglob nocaseglob
    if (( ${#mmproj_siblings[@]} != 0 )); then
        printf '%s\n' \
            'The Website Generator requires a text-only GGUF directory without mmproj files.' \
            'Place the model and config.json in a separate local directory.' >&2
        exit 2
    fi
    chat_template_path="$tokenizer_path/chat_template.jinja"

    if [[ "$model_alias" == "qwen/qwen3.8-27b" ]] || \
        LC_ALL=C grep -Eq \
            '"model_type"[[:space:]]*:[[:space:]]*"qwen3_5(_text)?"' \
            "$hf_config_path/config.json"
    then
        requires_qwen_gguf_adapter=1
    fi

    if (( requires_qwen_gguf_adapter )); then
        configured_adapter_path="${VLLM_GGUF_PLUGIN_PATH:-}"
        if [[ -z "$configured_adapter_path" || ! -d "$configured_adapter_path" ]]; then
            printf '%s\n' \
                'Set VLLM_GGUF_PLUGIN_PATH to the pinned Qwen GGUF adapter checkout.' >&2
            exit 2
        fi
        if ! command -v git >/dev/null 2>&1; then
            printf 'git is required to verify VLLM_GGUF_PLUGIN_PATH.\n' >&2
            exit 2
        fi
        qwen_gguf_adapter_path="$(cd "$configured_adapter_path" && pwd -P)"
        if ! adapter_repo_root="$(
            git -C "$qwen_gguf_adapter_path" rev-parse --show-toplevel 2>/dev/null
        )"; then
            printf 'VLLM_GGUF_PLUGIN_PATH must be a Git checkout.\n' >&2
            exit 2
        fi
        if [[ "$adapter_repo_root" != "$qwen_gguf_adapter_path" ]]; then
            printf 'VLLM_GGUF_PLUGIN_PATH must name the checkout root.\n' >&2
            exit 2
        fi
        if ! adapter_commit="$(
            git -C "$qwen_gguf_adapter_path" rev-parse --verify HEAD 2>/dev/null
        )" || [[ "$adapter_commit" != "$qwen_gguf_adapter_commit" ]]; then
            printf 'VLLM_GGUF_PLUGIN_PATH must be pinned to commit %s.\n' \
                "$qwen_gguf_adapter_commit" >&2
            exit 2
        fi
        if ! adapter_status="$(
            git -C "$qwen_gguf_adapter_path" status --porcelain --untracked-files=all \
                2>/dev/null
        )"; then
            printf 'Unable to verify the VLLM_GGUF_PLUGIN_PATH checkout status.\n' >&2
            exit 2
        fi
        if [[ -n "$adapter_status" ]]; then
            printf 'VLLM_GGUF_PLUGIN_PATH must be a clean checkout.\n' >&2
            exit 2
        fi
        if [[ ! -f "$qwen_gguf_adapter_path/vllm_gguf_plugin/weights_adapter/qwen3_5.py" ]]; then
            printf 'VLLM_GGUF_PLUGIN_PATH is missing the Qwen3.5/3.8 adapter.\n' >&2
            exit 2
        fi
    fi
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
    --enforce-eager
    --no-enable-log-requests
    --disable-uvicorn-access-log
)
if [[ -n "$tokenizer_path" ]]; then
    args+=(
        --tokenizer "$tokenizer_path"
        --hf-config-path "$hf_config_path"
        --chat-template "$chat_template_path"
    )
fi
if [[ -n "$api_key" ]]; then
    args+=(--api-key "$api_key")
fi

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="$cuda_visible_devices"
export VLLM_USE_FLASHINFER_SAMPLER="$use_flashinfer_sampler"
if [[ -n "$qwen_gguf_adapter_path" ]]; then
    export PYTHONPATH="$qwen_gguf_adapter_path${PYTHONPATH:+:$PYTHONPATH}"
fi
exec "${args[@]}"
