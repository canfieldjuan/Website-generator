#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' \
    'scripts/start_llama_server.sh is retired; use scripts/start_vllm_server.sh.' >&2
exit 2
