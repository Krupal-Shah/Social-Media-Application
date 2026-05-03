"""Adapter for the Steel Blue node payloads."""
from __future__ import annotations

from typing import Any, Dict, List

from .base import (
    InboxAdapter,
    deep_copy_payload,
    ensure_string,
    normalize_author_payload,
)


class SteelBlueAdapter(InboxAdapter):
    slug = "steelblue"
    HOST_KEYWORDS = ("steelblue-avg-user-app",)

    def matches(self, *, node, request, payload: Any) -> bool:
        """Execute matches."""
        base = str(getattr(node, "base_url", "")).lower()
        return any(keyword in base for keyword in self.HOST_KEYWORDS)

    def normalize(self, *, node, request, payload: Any):
        """Execute normalize."""
        data = deep_copy_payload(payload)
        item_type = str(data.get("type", "")).strip().lower()
        if not item_type:
            return data

        if item_type == "author":
            return normalize_author_payload(data)
        if item_type == "entry":
            return self._normalize_entry_payload(data)
        if item_type == "comment":
            return self._normalize_comment_payload(data)
        if item_type == "like":
            return self._normalize_like_payload(data)
        if item_type == "follow":
            return self._normalize_follow_payload(data)
        return data

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------
    def _normalize_entry_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize entry payload."""
        entry_id = ensure_string(payload.get(
            "id") or payload.get("url") or payload.get("web"))
        payload["id"] = entry_id
        payload["author"] = normalize_author_payload(payload.get("author"))
        payload["contentType"] = payload.get(
            "contentType") or payload.get("content_type") or "text/plain"
        payload["visibility"] = self._normalize_visibility(
            payload.get("visibility"))

        comments_obj = payload.get("comments")
        payload["comments"] = self._normalize_comments_object(
            comments_obj, entry_id)

        likes_obj = payload.get("likes")
        payload["likes"] = self._normalize_likes_object(likes_obj, entry_id)
        return payload

    def _normalize_comment_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize comment payload."""
        payload["author"] = normalize_author_payload(payload.get("author"))
        payload["contentType"] = payload.get(
            "contentType") or payload.get("content_type") or "text/plain"
        payload["entry"] = self._extract_entry_fqid(payload)
        payload["comment"] = ensure_string(
            payload.get("comment") or payload.get("content"))
        payload["id"] = ensure_string(payload.get("id") or payload.get("url"))
        return payload

    def _normalize_like_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize like payload."""
        payload["author"] = normalize_author_payload(payload.get("author"))
        payload["object"] = self._extract_object_fqid(payload)
        payload["summary"] = payload.get(
            "summary") or f"{payload['author'].get('displayName', 'Someone')} likes this"
        payload["id"] = ensure_string(payload.get("id") or payload.get("url"))
        return payload

    def _normalize_follow_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute normalize follow payload."""
        raw_status = str(payload.get("status", "")).strip().upper()
        payload["actor"] = normalize_author_payload(payload.get("actor"))
        payload["object"] = normalize_author_payload(payload.get("object"))
        payload["summary"] = payload.get("summary") or ""
        status_map = {
            "REQUESTING": "REQUESTED",
            "ACCEPTED": "ACCEPTED",
            "REJECTED": "REJECTED",
            "UNFOLLOWED": "UNFOLLOW",
        }
        payload["type"] = "follow"
        payload["status"] = status_map.get(
            raw_status, raw_status or "REQUESTED")
        payload["id"] = ensure_string(payload.get("id") or payload.get("url"))
        return payload

    def _normalize_comments_object(self, comments: Any, entry_id: str) -> Dict[str, Any]:
        """Execute normalize comments object."""
        base = {
            "type": "comments",
            "id": f"{entry_id}/comments" if entry_id else "",
            "page_number": 1,
            "size": 5,
            "count": 0,
            "src": [],
        }
        if not isinstance(comments, dict):
            return base

        normalized = {**base, **comments}
        normalized["id"] = ensure_string(normalized.get("id") or base["id"])
        normalized["src"] = self._normalize_comments_src(normalized.get("src"))
        normalized["count"] = normalized.get("count") or len(normalized["src"])
        return normalized

    def _normalize_likes_object(self, likes: Any, entry_id: str) -> Dict[str, Any]:
        """Execute normalize likes object."""
        base = {
            "type": "likes",
            "id": f"{entry_id}/likes" if entry_id else "",
            "page_number": 1,
            "size": 50,
            "count": 0,
            "src": [],
        }
        if not isinstance(likes, dict):
            return base

        normalized = {**base, **likes}
        normalized["id"] = ensure_string(normalized.get("id") or base["id"])
        normalized["src"] = self._normalize_likes_src(normalized.get("src"))
        normalized["count"] = normalized.get("count") or len(normalized["src"])
        return normalized

    def _normalize_comments_src(self, src: Any) -> List[Dict[str, Any]]:
        """Execute normalize comments src."""
        if not isinstance(src, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for item in src:
            if not isinstance(item, dict):
                continue
            comment = self._normalize_comment_payload({**item})
            normalized.append(comment)
        return normalized

    def _normalize_likes_src(self, src: Any) -> List[Dict[str, Any]]:
        """Execute normalize likes src."""
        if not isinstance(src, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for item in src:
            if not isinstance(item, dict):
                continue
            like = self._normalize_like_payload({**item})
            normalized.append(like)
        return normalized

    def _extract_entry_fqid(self, payload: Dict[str, Any]) -> str:
        """Execute extract entry fqid."""
        entry_candidate = payload.get("entry") or payload.get(
            "post") or payload.get("object")
        if isinstance(entry_candidate, dict):
            return ensure_string(entry_candidate.get("id") or entry_candidate.get("url"))
        return ensure_string(entry_candidate)

    def _extract_object_fqid(self, payload: Dict[str, Any]) -> str:
        """Execute extract object fqid."""
        obj_candidate = payload.get("object") or payload.get("entry")
        if isinstance(obj_candidate, dict):
            return ensure_string(obj_candidate.get("id") or obj_candidate.get("url"))
        return ensure_string(obj_candidate)

    def _normalize_visibility(self, visibility: Any) -> str:
        """Execute normalize visibility."""
        raw_visibility = str(visibility or "PUBLIC").strip().upper()
        visibility_map = {
            "FRIENDS ONLY": "FRIENDS",
            "FRIENDS_ONLY": "FRIENDS",
            "FRIENDS": "FRIENDS",
            "PUBLIC": "PUBLIC",
            "UNLISTED": "UNLISTED",
            "DELETED": "DELETED",
        }
        return visibility_map.get(raw_visibility, raw_visibility or "PUBLIC")
