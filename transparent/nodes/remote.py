"""Helpers for authenticated node-to-node requests."""
import base64
import binascii
import copy
import logging
import uuid
from urllib.parse import urlparse

import requests
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.response import Response

from core.fqid import api_to_web_url
from core.utils import is_remote_fqid, normalize_api_base
from authors.models import Author
from .models import Node, RemoteAuthor
from social.models import Follow  # noqa: E402


logger = logging.getLogger(__name__)
TIMEOUT = 5
ENTRY_UPDATE_POST_COMPAT_HOST_KEYWORDS = (
    "steelblue-avg-user-app",
    "papayawhip-socialdistribution-",
)
ENTRY_UPDATE_PUT_FALLBACK_STATUSES = {404, 405, 501}


def _normalize_api_base(raw_base):
    """Execute normalize api base."""
    return normalize_api_base(raw_base)


def _is_remote_fqid(fqid):
    """Execute is remote fqid."""
    return is_remote_fqid(fqid)


def _auth(node):
    """Execute auth."""
    return (node.username, node.password)


def _is_node_send_enabled(node):
    """Execute is node send enabled."""
    if not node:
        return False
    return Node.objects.active().filter(pk=node.pk).exists()


def _prefer_post_for_entry_update(node, payload_type, method_upper):
    """Execute prefer post for entry update."""
    if method_upper != "PUT" or payload_type != "entry":
        return False
    base_url = str(getattr(node, "base_url", "") or "").lower()
    return any(keyword in base_url for keyword in ENTRY_UPDATE_POST_COMPAT_HOST_KEYWORDS)


def get_active_nodes():
    """Return active nodes."""
    return Node.objects.active()


def find_node_for_url(value, include_inactive=False):
    """Execute find node for url."""
    queryset = Node.objects.all() if include_inactive else get_active_nodes()
    candidate = str(value or "").strip()
    if not candidate:
        return None
    for node in queryset:
        if node.matches_url(candidate):
            return node
    return None


def find_node_for_author_fqid(author_fqid, include_inactive=False):
    """Execute find node for author fqid."""
    fqid = str(author_fqid or "").strip()
    if not fqid:
        return None

    node = find_node_for_url(fqid, include_inactive=include_inactive)
    if node:
        logger.info(
            "Federation match: author_fqid=%s node=%s",
            fqid,
            node.base_url,
        )
        return node

    remote_author = (
        RemoteAuthor.objects.filter(fqid=fqid)
        .select_related("node")
        .first()
    )
    if remote_author and remote_author.node:
        if include_inactive or remote_author.node.active:
            logger.info(
                "Federation fallback: using RemoteAuthor.node for %s -> %s",
                fqid,
                remote_author.node.base_url,
            )
            return remote_author.node

    logger.warning("Federation match failed: no node for author_fqid=%s", fqid)
    return None


def node_from_basic_auth(username, password, include_inactive=False):
    """Execute node from basic auth."""
    if not username or not password:
        return None
    queryset = Node.objects.all() if include_inactive else Node.objects.filter(active=True)
    return queryset.filter(username=username, password=password).first()


def parse_basic_auth_header(request):
    """Execute parse basic auth header."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Basic "):
        return None, None
    encoded = header.split(" ", 1)[1].strip()
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
        return username, password
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None, None


def authenticate_remote_api_request(request, *, payload=None, realm="node-api"):
    """Execute authenticate remote api request."""
    username, password = parse_basic_auth_header(request)
    if not username or not password:
        logger.warning(
            "Remote API auth failed: missing/invalid basic auth header")
        return None, Response(
            {"detail": "Valid remote node basic auth required."},
            status=drf_status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": f'Basic realm="{realm}"'},
        )

    node = node_from_basic_auth(username, password)
    if not node:
        logger.warning(
            "Remote API auth failed: username/password not found on active node (%s)",
            username,
        )
        return None, Response(
            {"detail": "Valid remote node basic auth required."},
            status=drf_status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": f'Basic realm="{realm}"'},
        )

    logger.info("Remote API auth success: node=%s", node.base_url)
    return node, None


def remote_api_auth_succeeds(request, *, payload=None):
    """Execute remote api auth succeeds."""
    _, error = authenticate_remote_api_request(request, payload=payload)
    return error is None


def _fqid_host(value):
    """Execute fqid host."""
    parsed = urlparse(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/"


def _drop_blank_values(data):
    """Execute drop blank values."""
    return {
        key: value
        for key, value in (data or {}).items()
        if value is not None and value != ""
    }


def _normalize_outbound_author(author_data):
    """Execute normalize outbound author."""
    author = copy.deepcopy(author_data or {})
    author_id = str(author.get("id", "")).strip()
    if author_id:
        author.setdefault("host", _fqid_host(author_id))
        author.setdefault("web", api_to_web_url(author_id))
        author.setdefault("display_name", author.get("displayName", ""))
        author.setdefault("profile_image", author.get("profileImage", ""))
    return _drop_blank_values(author)


def _author_payload(author_or_fqid):
    """Execute author payload."""
    if isinstance(author_or_fqid, Author):
        return _drop_blank_values(
            {
                "type": "author",
                "id": author_or_fqid.fqid,
                "host": author_or_fqid.host,
                "displayName": author_or_fqid.display_name,
                "web": author_or_fqid.web,
                "username": author_or_fqid.username,
                "github": author_or_fqid.github or "",
                "profileImage": author_or_fqid.profile_image or "",
                "description": author_or_fqid.description or "",
            }
        )

    fqid = str(author_or_fqid or "").strip()
    if not fqid:
        return {"type": "author"}

    local_author = Author.objects.filter(fqid=fqid).first()
    if local_author:
        return _author_payload(local_author)

    remote_author = RemoteAuthor.objects.filter(fqid=fqid).first()
    if remote_author:
        return _drop_blank_values(
            {
                "type": "author",
                "id": remote_author.fqid,
                "host": remote_author.host or remote_author.node.web_base_url,
                "displayName": remote_author.display_name or fqid.rstrip("/").split("/")[-1],
                "web": api_to_web_url(remote_author.fqid),
                "username": remote_author.username or "",
                "github": remote_author.github or "",
                "profileImage": remote_author.profile_image or "",
            }
        )

    return _drop_blank_values(
        {
            "type": "author",
            "id": fqid,
            "host": _fqid_host(fqid),
            "web": api_to_web_url(fqid),
            "displayName": fqid.rstrip("/").split("/")[-1],
        }
    )


def _follow_author_host(author_id, fallback=""):
    """Execute follow author host."""
    author_id = str(author_id or "").strip()
    if "/authors/" in author_id:
        return f"{normalize_api_base(author_id.split('/authors/', 1)[0]).rstrip('/')}/"

    fallback = str(fallback or "").strip()
    if fallback:
        return f"{normalize_api_base(fallback).rstrip('/')}/"

    root_host = _fqid_host(author_id)
    if root_host:
        return f"{normalize_api_base(root_host).rstrip('/')}/"
    return ""


def _follow_author_payload(author_or_fqid):
    """Execute follow author payload."""
    author = _author_payload(author_or_fqid)
    author_id = str(author.get("id") or "").strip()
    return {
        "id": author_id,
        "web": str(author.get("web") or api_to_web_url(author_id) or ""),
        "host": _follow_author_host(author_id, author.get("host") or ""),
        "type": "author",
        "github": str(author.get("github") or ""),
        "displayName": str(author.get("displayName") or ""),
    }


def _default_collection_payload(entry_id, collection_type, size):
    """Execute default collection payload."""
    web_id = api_to_web_url(entry_id) if entry_id else ""
    suffix = "comments" if collection_type == "comments" else "likes"
    base_id = f"{entry_id.rstrip('/')}/{suffix}" if entry_id else ""
    data = {
        "type": collection_type,
        "id": base_id,
        "web": web_id,
        "page_number": 1,
        "size": size,
        "count": 0,
        "src": [],
    }
    return _drop_blank_values(data)


def prepare_outbound_payload_for_node(node, payload):
    """Execute prepare outbound payload for node."""
    data = copy.deepcopy(payload or {})
    item_type = str(data.get("type", "")).strip().lower()

    if item_type == "author":
        return _normalize_outbound_author(data)

    if item_type == "follow":
        data["actor"] = _normalize_outbound_author(data.get("actor"))
        data["object"] = _normalize_outbound_author(data.get("object"))
        return data

    if item_type == "entry":
        entry_id = str(data.get("id", "")).strip()
        if entry_id:
            data.setdefault("web", api_to_web_url(entry_id))
            data.setdefault("url", api_to_web_url(entry_id))
        data["author"] = _normalize_outbound_author(data.get("author"))
        content_type = str(data.get("contentType")
                           or data.get("content_type") or "").strip()
        if content_type:
            data.setdefault("contentType", content_type)
            data.setdefault("content_type", content_type)
            data.setdefault("ContentType", content_type)
        data.setdefault("comments", _default_collection_payload(
            entry_id, "comments", 5))
        data.setdefault("likes", _default_collection_payload(
            entry_id, "likes", 50))
        return _drop_blank_values(data)

    if item_type == "comment":
        data["author"] = _normalize_outbound_author(data.get("author"))
        return _drop_blank_values(data)

    if item_type == "like":
        data["author"] = _normalize_outbound_author(data.get("author"))
        return _drop_blank_values(data)

    return data


def payload_origin_fqid(item_type, payload):
    """Execute payload origin fqid."""
    data = payload or {}
    item_type = str(item_type or "").strip().lower()

    if item_type == "author":
        return str(data.get("id", "")).strip()

    if item_type == "follow":
        actor = data.get("actor", {}) if isinstance(data, dict) else {}
        return str(actor.get("id", "")).strip()

    if item_type in {"entry", "comment", "like"}:
        author = data.get("author", {}) if isinstance(data, dict) else {}
        return str(author.get("id", "")).strip()

    return ""


def remote_author_payload_defaults(author, node):
    """Execute remote author payload defaults."""
    fqid = str(author.get("id", "")).strip()
    display_name = str(author.get("displayName") or fqid.rsplit("/", 1)[-1])
    username = str(author.get("username")
                   or author.get("preferredUsername") or "")
    host = str(author.get("host") or "")
    github = str(author.get("github") or "")
    profile_image = str(author.get("profileImage") or "")

    return {
        "node": node,
        "display_name": display_name,
        "username": username,
        "host": host,
        "github": github,
        "profile_image": profile_image,
        "raw": author,
    }


def upsert_remote_author(author, node=None):
    """Execute upsert remote author."""
    fqid = str((author or {}).get("id", "")).strip()
    if not fqid:
        return None

    node = node or find_node_for_author_fqid(fqid)
    if not node:
        return None

    remote_author, _ = RemoteAuthor.objects.update_or_create(
        fqid=fqid,
        defaults=remote_author_payload_defaults(author, node),
    )
    return remote_author


def sync_remote_authors_for_node(node):
    """Execute sync remote authors for node."""
    report = fetch_remote_authors(node)
    authors = report["authors"]
    seen_fqids = set()
    upserted = 0

    for author in authors:
        remote_author = upsert_remote_author(author, node=node)
        if not remote_author:
            continue
        seen_fqids.add(remote_author.fqid)
        upserted += 1

    if report["ok"] and seen_fqids:
        RemoteAuthor.objects.filter(node=node).exclude(
            fqid__in=seen_fqids).delete()
    elif report["ok"]:
        RemoteAuthor.objects.filter(node=node).delete()

    now = timezone.now()
    node.last_sync_attempt_at = now
    node.last_sync_count = upserted
    if report["ok"]:
        node.last_sync_success_at = now
        node.last_sync_error = ""
    else:
        node.last_sync_error = report["error"]
    node.save(
        update_fields=[
            "last_sync_attempt_at",
            "last_sync_success_at",
            "last_sync_error",
            "last_sync_count",
        ]
    )

    logger.info(
        "Remote author sync complete: node=%s ok=%s upserted=%s error=%s",
        node.base_url,
        report["ok"],
        upserted,
        report["error"],
    )
    return {
        "ok": report["ok"],
        "authors": authors,
        "upserted": upserted,
        "error": report["error"],
        "status_code": report["status_code"],
        "url": report["url"],
    }


def sync_remote_authors():
    """Execute sync remote authors."""
    total = 0
    failed = []
    for node in get_active_nodes():
        result = sync_remote_authors_for_node(node)
        total += result["upserted"]
        if not result["ok"]:
            failed.append(
                {
                    "node": node.base_url,
                    "error": result["error"],
                    "status_code": result["status_code"],
                }
            )
    return {"upserted": total, "failed": failed}


def _request_to_inbox(node, recipient_author_fqid, payload, method="POST"):
    """Execute request to inbox."""
    if not _is_node_send_enabled(node):
        logger.info(
            "Federation send skipped: node disabled recipient=%s node=%s",
            recipient_author_fqid,
            getattr(node, "base_url", "<unknown>"),
        )
        return None

    inbox_url = f"{str(recipient_author_fqid).rstrip('/')}/inbox/"
    requested_method_upper = str(method or "POST").upper()
    prepared_payload = prepare_outbound_payload_for_node(node, payload)
    payload_type = str((prepared_payload or {}).get("type", "")).lower()

    method_upper = requested_method_upper
    if _prefer_post_for_entry_update(node, payload_type, method_upper):
        logger.info(
            "Federation compatibility: using POST for entry update to node=%s",
            node.base_url,
        )
        method_upper = "POST"

    def _send(http_method):
        """Execute send."""
        request_fn = requests.put if http_method == "PUT" else requests.post
        return request_fn(
            inbox_url,
            json=prepared_payload,
            auth=_auth(node),
            timeout=TIMEOUT,
        )

    logger.info(
        "Federation send start: recipient=%s type=%s via_node=%s method=%s",
        recipient_author_fqid,
        payload_type,
        node.base_url,
        method_upper,
    )

    try:
        response = _send(method_upper)
        response.raise_for_status()
        logger.info(
            "Federation send success: recipient=%s type=%s status=%s",
            recipient_author_fqid,
            payload_type,
            response.status_code,
        )
        return response
    except Exception as exc:
        status_code = getattr(
            getattr(exc, "response", None), "status_code", None)
        if (
            requested_method_upper == "PUT"
            and method_upper == "PUT"
            and payload_type == "entry"
            and status_code in ENTRY_UPDATE_PUT_FALLBACK_STATUSES
        ):
            logger.info(
                "Federation send retry: PUT rejected (status=%s), retrying POST for recipient=%s",
                status_code,
                recipient_author_fqid,
            )
            try:
                response = _send("POST")
                response.raise_for_status()
                logger.info(
                    "Federation send success after POST retry: recipient=%s type=%s status=%s",
                    recipient_author_fqid,
                    payload_type,
                    response.status_code,
                )
                return response
            except Exception as retry_exc:
                exc = retry_exc

        response = getattr(exc, "response", None)
        response_body = ""
        if response is not None:
            try:
                response_body = response.text[:500]
            except Exception:
                response_body = ""
        logger.warning(
            "Federation send failed: url=%s type=%s method=%s err=%s body=%s",
            inbox_url,
            payload_type,
            method_upper,
            exc,
            response_body,
        )
        return None


def _get_json(node, url, *, allow_public_fallback=False):
    """Execute get json."""
    attempts = [("basic-auth", _auth(node))]
    if allow_public_fallback:
        attempts.append(("public", None))

    last_error = None
    for label, auth in attempts:
        try:
            response = requests.get(
                url,
                auth=auth,
                timeout=TIMEOUT,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            if label == "public":
                logger.info(
                    "Federation GET fallback succeeded without basic auth: node=%s url=%s",
                    node.base_url,
                    url,
                )
            return response, data
        except Exception as exc:
            last_error = exc
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None)
            if label == "basic-auth" and allow_public_fallback and status_code in {401, 403}:
                logger.info(
                    "Federation GET with basic auth rejected; retrying public GET: node=%s url=%s status=%s",
                    node.base_url,
                    url,
                    status_code,
                )
                continue
            break

    raise last_error


def send_inbox_item_to_author(author_fqid, payload, method="POST"):
    """Execute send inbox item to author."""
    node = find_node_for_author_fqid(author_fqid)
    if not node:
        logger.warning(
            "Federation send skipped: no node found for recipient=%s",
            author_fqid,
        )
        return False
    return _request_to_inbox(node, author_fqid, payload, method=method) is not None


def remote_recipients_for_author(author_fqid, visibility="PUBLIC"):
    """Execute remote recipients for author."""
    normalized_author = str(author_fqid or "").strip().rstrip("/")
    if not normalized_author:
        return []

    normalized_visibility = str(visibility or "").upper()

    follower_fqids = {
        str(fqid).strip().rstrip("/")
        for fqid in (
            Follow.objects.filter(
                following_fqid=normalized_author, accepted=True)
            .values_list("follower_fqid", flat=True)
        )
        if _is_remote_fqid(fqid)
    }

    if normalized_visibility in ["PUBLIC", "UNLISTED"]:
        recipients = follower_fqids | {
            str(fqid).strip().rstrip("/")
            for fqid in (
                RemoteAuthor.objects.filter(node__active=True)
                .exclude(fqid="")
                .values_list("fqid", flat=True)
            )
            if _is_remote_fqid(fqid)
        }
    elif normalized_visibility == "FRIENDS":
        following_fqids = {
            str(fqid).strip().rstrip("/")
            for fqid in (
                Follow.objects.filter(
                    follower_fqid=normalized_author, accepted=True)
                .values_list("following_fqid", flat=True)
            )
            if _is_remote_fqid(fqid)
        }
        recipients = follower_fqids & following_fqids
    else:
        recipients = follower_fqids

    recipients.discard(normalized_author)
    logger.info(
        "Federation recipients: author=%s visibility=%s count=%s",
        normalized_author,
        normalized_visibility,
        len(recipients),
    )
    return sorted(recipients)


def fetch_remote_authors(node):
    """Execute fetch remote authors."""
    base = _normalize_api_base(node.base_url)
    url = f"{base}/authors/"
    logger.info("Federation fetch remote authors: node=%s url=%s",
                node.base_url, url)
    try:
        response, data = _get_json(node, url, allow_public_fallback=True)
        if isinstance(data, list):
            authors = data
        elif isinstance(data, dict):
            authors = data.get("authors") or data.get(
                "items") or data.get("src") or []
        else:
            authors = []
        logger.info(
            "Federation fetch remote authors success: node=%s count=%s",
            node.base_url,
            len(authors),
        )
        return {
            "ok": True,
            "authors": authors,
            "error": "",
            "status_code": response.status_code,
            "url": url,
        }
    except Exception as exc:
        logger.warning("Could not fetch authors from %s: %s",
                       node.base_url, exc)
        return {
            "ok": False,
            "authors": [],
            "error": str(exc),
            "status_code": getattr(getattr(exc, "response", None), "status_code", None),
            "url": url,
        }


def send_follow_to_inbox(node, actor_author, object_author_id, follow_status="REQUESTED"):
    """Execute send follow to inbox."""
    normalized_status = str(follow_status or "REQUESTED").upper()
    if normalized_status not in {"REQUESTED", "ACCEPTED", "REJECTED", "UNFOLLOW"}:
        raise ValueError("Unsupported follow status.")

    actor_payload = _follow_author_payload(actor_author)
    object_payload = _follow_author_payload(object_author_id)
    actor_display_name = actor_payload.get("displayName") or str(
        actor_payload.get("id", "")).rstrip("/").split("/")[-1]
    object_display_name = object_payload.get("displayName") or str(
        object_payload.get("id", "")).rstrip("/").split("/")[-1]
    summaries = {
        "REQUESTED": f"{actor_display_name} wants to follow {object_display_name}",
        "ACCEPTED": f"{object_display_name} accepted {actor_display_name}'s follow request",
        "REJECTED": f"{object_display_name} rejected {actor_display_name}'s follow request",
        "UNFOLLOW": f"{actor_display_name} no longer follows {object_display_name}",
    }
    payload = {
        "id": str(uuid.uuid4()),
        "type": "follow",
        "status": normalized_status,
        "summary": summaries[normalized_status],
        "actor": actor_payload,
        "object": object_payload,
    }
    recipient_author_fqid = str(actor_payload.get("id", "")).strip()
    if normalized_status in {"REQUESTED", "UNFOLLOW"}:
        recipient_author_fqid = str(object_payload.get("id", "")).strip()

    if not recipient_author_fqid:
        return False

    return _request_to_inbox(node, recipient_author_fqid, payload, method="POST") is not None


def publish_local_author_to_nodes(author):
    """Execute publish local author to nodes."""
    author_fqid = str(getattr(author, "fqid", "")).strip()
    if not author_fqid:
        return 0

    payload = {
        "type": "author",
        "id": author_fqid,
        "displayName": getattr(author, "display_name", ""),
        "username": getattr(author, "username", ""),
        "host": getattr(author, "host", ""),
        "github": getattr(author, "github", "") or "",
        "profileImage": getattr(author, "profile_image", "") or "",
    }

    delivered = 0
    seen_node_ids = set()
    remote_authors = (
        RemoteAuthor.objects.select_related("node")
        .filter(node__active=True)
        .exclude(fqid="")
        .order_by("node_id", "fqid")
    )
    for remote_author in remote_authors:
        if remote_author.node_id in seen_node_ids:
            continue
        seen_node_ids.add(remote_author.node_id)
        response = _request_to_inbox(
            remote_author.node,
            remote_author.fqid,
            payload,
            method="POST",
        )
        if response is not None:
            delivered += 1

    logger.info(
        "Author publish complete: author=%s node_deliveries=%s",
        author_fqid,
        delivered,
    )
    return delivered
