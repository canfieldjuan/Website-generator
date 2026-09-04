#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' \
    'scripts/start_llama_server.sh is retired; Website Generator now requires operator-managed Ollama.' \
    'Install and start Ollama, make qwen3-30b-a3b:latest available, then rerun the application.' >&2
exit 2
