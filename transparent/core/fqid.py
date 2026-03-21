"""
Utilities for working with Fully Qualified IDs (FQIDs) and serials.

FQID  – the complete URL of an object (globally unique).
Serial – the last path segment of that URL (not globally unique).
"""

from urllib.parse import urlparse, unquote as _unquote


# ---------------------------------------------------------------------------
# Serial ↔ FQID helpers
# ---------------------------------------------------------------------------

def serial_from_fqid(fqid: str) -> str:
    """Return the serial (last path component) from a FQID URL."""
    path = urlparse(fqid).path
    return path.rstrip("/").rsplit("/", 1)[-1]


def decode_fqid(encoded: str) -> str:
    """URL-decode an FQID that was percent-encoded inside a URL path."""
    return _unquote(encoded)


# ---------------------------------------------------------------------------
# FQID constructors
# ---------------------------------------------------------------------------

def make_author_fqid(host: str, author_serial: str) -> str:
    """Build an author FQID.  host must already end with '/api/'."""
    return f"{host.rstrip('/')}authors/{author_serial}"


def make_entry_fqid(host: str, author_serial: str, entry_serial: str) -> str:
    """Build an entry FQID.  host must already end with '/api/'."""
    return f"{host.rstrip('/')}authors/{author_serial}/entries/{entry_serial}"


# ---------------------------------------------------------------------------
# API URL ↔ web (HTML frontend) URL
# ---------------------------------------------------------------------------

def api_to_web_url(api_url: str) -> str:
    """
    Convert an API URL to its corresponding HTML frontend URL by removing
    the '/api' segment from the path.

    Example::

        api_to_web_url("http://node/api/authors/222/entries/249")
        # → "http://node/authors/222/entries/249"
    """
    parsed = urlparse(api_url)
    new_path = parsed.path.replace("/api/", "/", 1)
    return parsed._replace(path=new_path).geturl()
