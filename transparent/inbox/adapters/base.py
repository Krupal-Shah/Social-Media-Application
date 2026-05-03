"""Shared helpers for normalizing remote inbox payloads."""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional
from urllib.parse import urlparse


Payload = Dict[str, Any]


def deep_copy_payload(payload: Any) -> Payload:
    """Return a mutable copy regardless of DRF's internal representation."""
    if isinstance(payload, dict):
        return copy.deepcopy(payload)
    return {}


def ensure_string(value: Any) -> str:
    """Execute ensure string."""
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (int, float)):
        return str(value).strip()

    if isinstance(value, dict):
        for key in ("id", "url", "uri", "href"):
            candidate = value.get(key)
            if candidate:
                return ensure_string(candidate)
    return ""


def infer_host_from_url(url: str) -> str:
    """Execute infer host from url."""
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return ""
    # Include trailing slash to stay consistent with SERVICE_URL usage.
    return f"{parsed.scheme}://{parsed.netloc}/"


def normalize_author_payload(raw_author: Any) -> Dict[str, Any]:
    """Execute normalize author payload."""
    if isinstance(raw_author, str):
        raw_author = {"id": raw_author}

    author = raw_author if isinstance(raw_author, dict) else {}
    fqid = ensure_string(author.get("id") or author.get("url"))
    host = ensure_string(author.get("host")) or infer_host_from_url(fqid)
    display_name = (
        author.get("displayName")
        or author.get("display_name")
        or author.get("username")
        or author.get("preferredUsername")
        or fqid.rsplit("/", 1)[-1]
    )

    normalized = {
        "id": fqid,
        "host": host,
        "displayName": display_name,
        "github": author.get("github") or "",
        "profileImage": author.get("profileImage") or author.get("profile_image") or "",
        "type": author.get("type") or "author",
    }

    web = author.get("web") or author.get("url")
    if not web and fqid:
        web = fqid.replace("/api/", "/")
    if web:
        normalized["web"] = web

    return {key: value for key, value in normalized.items() if value}


class InboxAdapter:
    """Base adapter used to normalize remote payloads per team."""

    slug: str = "base"

    def matches(self, *, node, request, payload: Any) -> bool:
        """Return True when this adapter should handle the payload."""
        return False

    def normalize(self, *, node, request, payload: Any) -> Payload:
        """Return transformed payload expected by local inbox processing."""
        return deep_copy_payload(payload)
