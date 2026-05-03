"""Adapter for the Mintcream node payloads."""
from __future__ import annotations

from typing import Any, Dict

from .base import InboxAdapter, deep_copy_payload, ensure_string, normalize_author_payload


class MintcreamAdapter(InboxAdapter):
    slug = "mintcream"
    HOST_KEYWORDS = ("socialdistribution-darius-", "mintcream")

    def matches(self, *, node, request, payload: Any) -> bool:
        """Execute matches."""
        base = str(getattr(node, "base_url", "")).lower()
        return any(keyword in base for keyword in self.HOST_KEYWORDS)

    def normalize(self, *, node, request, payload: Any):
        """Execute normalize."""
        data = deep_copy_payload(payload)
        item_type = str(data.get("type", "")).strip().lower()

        if item_type == "author":
            return normalize_author_payload(data)
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
        payload["id"] = ensure_string(payload.get("id") or payload.get("url") or payload.get("web"))
        payload["author"] = normalize_author_payload(payload.get("author"))
        content_type = payload.get("contentType") or payload.get("content_type") or payload.get("ContentType")
        if content_type:
            payload["contentType"] = content_type
            payload["content_type"] = content_type
        return payload

    def _normalize_follow_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize follow payload."""
        payload["type"] = "follow"
        payload["status"] = str(payload.get("status") or "REQUESTED").upper()
        payload["actor"] = normalize_author_payload(payload.get("actor"))
        payload["object"] = normalize_author_payload(payload.get("object"))
        payload["id"] = ensure_string(payload.get("id") or payload.get("url"))
        return payload

    def _normalize_comment_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize comment payload."""
        payload["author"] = normalize_author_payload(payload.get("author"))
        content_type = payload.get("contentType") or payload.get("content_type") or payload.get("ContentType")
        if content_type:
            payload["contentType"] = content_type
        payload["id"] = ensure_string(payload.get("id") or payload.get("url"))
        return payload

    def _normalize_like_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize like payload."""
        payload["author"] = normalize_author_payload(payload.get("author"))
        payload["id"] = ensure_string(payload.get("id") or payload.get("url"))
        return payload
