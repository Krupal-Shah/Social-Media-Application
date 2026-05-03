"""Utilities and logic for utils."""

from django.conf import settings
from django.utils.dateparse import parse_datetime


def is_base64_image_content_type(content_type):
    """Return whether base64 image content type."""
    ct = str(content_type or "").lower().strip()
    return ct in {"image/png;base64", "image/jpeg;base64", "application/base64"}


def data_url_from_entry_content(content_type, content):
    """Execute data url from entry content."""
    ct = str(content_type or "").lower().strip()
    if ct == "image/png;base64":
        mime = "image/png"
    elif ct == "image/jpeg;base64":
        mime = "image/jpeg"
    elif ct == "application/base64":
        mime = "application/octet-stream"
    else:
        return ""
    return f"data:{mime};base64,{content}"


def normalize_api_base(raw_base):
    """Execute normalize api base."""
    base = (raw_base or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/api"):
        return base
    return f"{base}/api"


def is_from_active_node(fqid, active_scopes):
    """Return whether from active node."""
    source = str(fqid or "").strip()
    if not source:
        return False
    return any(source.startswith(scope) for scope in active_scopes)


def is_remote_fqid(fqid):
    """Return whether remote fqid."""
    local_api = normalize_api_base(getattr(settings, "SERVICE_URL", ""))
    local_web = local_api[:-4] if local_api.endswith("/api") else local_api
    value = str(fqid or "")
    return not (value.startswith(local_api) or value.startswith(local_web))


def coerce_datetime(value, fallback):
    """Execute coerce datetime."""
    if hasattr(value, "tzinfo"):
        return value
    parsed = parse_datetime(str(value)) if value else None
    return parsed or fallback


def author_fqid_from_entry_fqid(entry_fqid):
    """Execute author fqid from entry fqid."""
    fqid = str(entry_fqid or "").strip().rstrip("/")
    marker = "/entries/"
    if marker not in fqid:
        return ""
    return fqid.split(marker, 1)[0]


def shareable_entry_web_url(entry_fqid, api_to_web_url=None):
    """Execute shareable entry web url."""
    from core.fqid import api_to_web_url as default_api_to_web_url

    fqid = str(entry_fqid or "").strip()
    if not fqid:
        return ""

    if api_to_web_url is None:
        api_to_web_url = default_api_to_web_url

    web_url = api_to_web_url(fqid)
    if "/entries/" in web_url and not web_url.endswith("/"):
        web_url = f"{web_url}/"
    return web_url


def web_base_for_author(author):
    """Execute web base for author."""
    host = str(author.host or settings.SERVICE_URL)
    return host.replace("/api/", "/").rstrip("/")
