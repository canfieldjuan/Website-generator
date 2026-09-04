"""Shared preparation and generation for one admitted website artifact."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import unquote_to_bytes, urlsplit

import build
from lib.generation import GeneratedHtmlError, GenerationConfig, MAX_HTML_BYTES


MAX_PROSPECT_BYTES = 200_000


@dataclass(frozen=True)
class SiteArtifact:
    html: bytes
    display_name: str
    prospect: dict[str, Any]


def _is_accessible_image_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False
    if parsed.scheme.lower() in {"http", "https"}:
        try:
            hostname = parsed.hostname
            parsed.port
        except ValueError:
            return False
        if not hostname or any(character.isspace() for character in hostname):
            return False
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii").rstrip(".")
        except UnicodeError:
            return False
        if not ascii_hostname or len(ascii_hostname) > 253:
            return False
        try:
            ipaddress.ip_address(ascii_hostname)
        except ValueError:
            labels = ascii_hostname.split(".")
            if any(
                not re.fullmatch(
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
                    label,
                )
                for label in labels
            ):
                return False
        return True
    if parsed.scheme.lower() == "data":
        header, separator, payload = candidate.partition(",")
        metadata = header[5:].split(";")
        if (
            not separator
            or not metadata[0].lower().startswith("image/")
            or len(metadata[0]) == len("image/")
            or not payload
            or re.search(r"%(?![0-9A-Fa-f]{2})", payload)
        ):
            return False
        decoded_payload = unquote_to_bytes(payload)
        if any(parameter.lower() == "base64" for parameter in metadata[1:]):
            try:
                decoded_payload = base64.b64decode(decoded_payload, validate=True)
            except (binascii.Error, ValueError):
                return False
        return bool(decoded_payload)
    return False


def _select_self_contained_hero_shape(prospect: dict[str, Any]) -> None:
    photos = prospect.get("photos")
    has_hero = isinstance(photos, list) and any(
        isinstance(photo, dict)
        and photo.get("context") == "hero"
        and _is_accessible_image_url(photo.get("url"))
        for photo in photos
    )
    if prospect.get("_computed_hero_shape") in {"fullbleed", "split"} and not has_hero:
        prospect["_computed_hero_shape"] = "gradient"


def prepare_site_prospect(
    prospect_document: Any,
    *,
    build_date: date | None = None,
) -> dict[str, Any]:
    """Normalize a prospect and apply the deterministic single-artifact design."""
    prospect = build.prepare_prospect(prospect_document, build_date=build_date)
    build.apply_design_selections(prospect, announce=False)
    _select_self_contained_hero_shape(prospect)
    build.resolve_build_document_colors(prospect)
    if len(build.format_prospect_prompt_block(prospect)) > build.BUILD_USER_TRUNCATE:
        raise ValueError("The prospect document exceeds the generation prompt limit.")
    return prospect


def generate_site_artifact(
    prospect_document: Any,
    generation_config: GenerationConfig,
    *,
    client: Any | None = None,
) -> SiteArtifact:
    """Generate one admitted HTML artifact through the canonical build path."""
    prospect = prepare_site_prospect(prospect_document)
    return generate_prepared_site_artifact(
        prospect,
        generation_config,
        client=client,
    )


def generate_prepared_site_artifact(
    prospect: dict[str, Any],
    generation_config: GenerationConfig,
    *,
    client: Any | None = None,
) -> SiteArtifact:
    """Generate an artifact from a prospect prepared by this module."""
    if client is None:
        html = build.generate_build_html(prospect, generation_config)
    else:
        html = build.generate_build_html(prospect, generation_config, client=client)
    encoded = html.encode("utf-8")
    if len(encoded) > MAX_HTML_BYTES:
        raise GeneratedHtmlError("Generated HTML exceeds the artifact size limit.")
    return SiteArtifact(
        html=encoded,
        display_name=f"{build.slugify(prospect['business_name'])}-homepage.html",
        prospect=prospect,
    )
