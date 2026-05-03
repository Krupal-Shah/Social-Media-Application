"""Adapter used for payloads that already match our spec."""
from __future__ import annotations

from typing import Any

from .base import InboxAdapter, deep_copy_payload


class LocalAdapter(InboxAdapter):
    slug = "local"

    def matches(self, *, node, request, payload: Any) -> bool:
        """Execute matches."""
        # Fallback adapter: always matches last.
        return True

    def normalize(self, *, node, request, payload: Any):
        """Execute normalize."""
        return deep_copy_payload(payload)
