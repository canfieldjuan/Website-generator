"""Environment-backed third-party configuration.

This module deliberately performs no network I/O and creates no API clients at
import time.  Callers opt in to each external service through the matching
factory so a local-only build remains local-only.
"""
import os
import json
from functools import lru_cache

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
EXTRACTION_MODEL = "anthropic/claude-haiku-4.5"
# Hero / background image generation. OpenRouter's image model catalog
# shifts over time; update this constant when the provider deprecates an
# entry. Bypass at runtime with --skip-image-gen.
IMAGE_MODEL = "black-forest-labs/flux.2-max"


class MissingServiceConfiguration(RuntimeError):
    """Raised when an explicitly requested service is not configured."""


@lru_cache(maxsize=1)
def get_openrouter_client():
    """Return the shared OpenRouter client, creating it only when requested."""
    if not OPENROUTER_API_KEY:
        raise MissingServiceConfiguration(
            "OPENROUTER_API_KEY is required for this OpenRouter operation."
        )
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY)

def extract_json_object(text):
    """Pull a single JSON object out of an LLM response, tolerating the
    markdown fences or leading preamble Claude sometimes emits even when
    asked for raw JSON. Raises json.JSONDecodeError if no valid object is
    recoverable."""
    if not isinstance(text, str):
        raise ValueError("LLM response was not a string")
    stripped = text.strip()
    # Strip an opening ```json or ``` fence if the whole payload is fenced.
    if stripped.startswith("```"):
        newline_idx = stripped.find("\n")
        if newline_idx != -1:
            stripped = stripped[newline_idx + 1:]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()
    # If there's preamble before the first '{' or trailing chatter after
    # the last '}', slice the JSON object out by brace position.
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = stripped[first_brace:last_brace + 1]
        return json.loads(candidate)
    return json.loads(stripped)
