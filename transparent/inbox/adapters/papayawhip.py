"""Adapter for the Papaya Whip node payloads."""
from __future__ import annotations

from typing import Any, Dict

from .base import InboxAdapter, deep_copy_payload, ensure_string, normalize_author_payload


def _clean_nullable_string(value):
    """Execute clean nullable string."""
    if isinstance(value, str) and value.strip().lower() == "null":
        return ""
    return value


def _clean_author(author: Dict[str, Any]) -> Dict[str, Any]:
    """Execute clean author."""
    cleaned = dict(author)
    for key in ("github", "profileImage", "profile_image", "web", "url"):
        if key in cleaned:
            cleaned[key] = _clean_nullable_string(cleaned[key])
    return cleaned


class PapayaWhipAdapter(InboxAdapter):
    slug = "papayawhip"
    HOST_KEYWORDS = ("papayawhip-socialdistribution-", "papayawhip")

    def matches(self, *, node, request, payload: Any) -> bool:
        """Execute matches."""
        base = str(getattr(node, "base_url", "")).lower()
        return any(keyword in base for keyword in self.HOST_KEYWORDS)

    def normalize(self, *, node, request, payload: Any):
        """Execute normalize."""
        data = deep_copy_payload(payload)
        item_type = str(data.get("type", "")).strip().lower()
        if item_type == "post":
            item_type = "entry"
            data["type"] = "entry"

        if item_type == "author":
            return normalize_author_payload(_clean_author(data))
        if item_type == "entry":
            return self._normalize_entry_payload(data)
        if item_type == "follow":
            return self._normalize_follow_payload(data)
        if item_type == "comment":
            return self._normalize_comment_payload(data)
        if item_type == "like":
            return self._normalize_like_payload(data)
        return data

    def _normalize_entry_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize entry payload."""
        payload["type"] = "entry"
        payload["id"] = ensure_string(payload.get("id") or payload.get("url") or payload.get("web"))
        content_type = (
            payload.get("content_type")
            or payload.get("contentType")
            or payload.get("ContentType")
            or "text/plain"
        )
        payload["content_type"] = content_type
        payload["contentType"] = content_type
        payload["ContentType"] = content_type
        payload["author"] = normalize_author_payload(_clean_author(payload.get("author") or {}))
        payload["description"] = _clean_nullable_string(payload.get("description")) or ""
        return payload

    def _normalize_follow_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize follow payload."""
        payload["type"] = "follow"
        payload["status"] = str(payload.get("status") or "REQUESTED").upper()
        payload["actor"] = normalize_author_payload(_clean_author(payload.get("actor") or {}))
        payload["object"] = normalize_author_payload(_clean_author(payload.get("object") or {}))
        payload["id"] = ensure_string(payload.get("id") or payload.get("url"))
        return payload

    def _normalize_comment_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize comment payload."""
        payload["type"] = "comment"
        payload["author"] = normalize_author_payload(_clean_author(payload.get("author") or {}))
        content_type = (
            payload.get("content_type")
            or payload.get("contentType")
            or payload.get("ContentType")
            or "text/plain"
        )
        payload["content_type"] = content_type
        payload["contentType"] = content_type
        payload["id"] = ensure_string(payload.get("id") or payload.get("url"))
        return payload

    def _normalize_like_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize like payload."""
        payload["type"] = "like"
        payload["author"] = normalize_author_payload(_clean_author(payload.get("author") or {}))
        payload["id"] = ensure_string(payload.get("id") or payload.get("url"))
        return payload
