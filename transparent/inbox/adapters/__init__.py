"""Registry for inbox payload adapters."""
from __future__ import annotations

from typing import Any, Tuple

from django.http import HttpRequest

from .base import InboxAdapter, Payload
from .local import LocalAdapter
from .mintcream import MintcreamAdapter
from .papayawhip import PapayaWhipAdapter
from .steelblue import SteelBlueAdapter

# Order matters: first match wins with LocalAdapter as fallback.
REGISTERED_ADAPTERS = [
    PapayaWhipAdapter(),
    MintcreamAdapter(),
    SteelBlueAdapter(),
    LocalAdapter(),
]


def normalize_payload(node, request: HttpRequest, payload: Any) -> Tuple[Payload, str]:
    """Return normalized payload and adapter slug used."""
    adapter: InboxAdapter = REGISTERED_ADAPTERS[-1]
    for candidate in REGISTERED_ADAPTERS:
        if candidate.matches(node=node, request=request, payload=payload):
            adapter = candidate
            break
    normalized = adapter.normalize(node=node, request=request, payload=payload)
    return normalized, adapter.slug
