"""Utilities and logic for utils."""

import base64
import json
import uuid
from types import SimpleNamespace
from urllib.parse import unquote

from django.http import HttpResponse, Http404
from django.shortcuts import redirect
from authors.models import Author
from core.utils import (
    author_fqid_from_entry_fqid,
    coerce_datetime,
    data_url_from_entry_content,
    is_base64_image_content_type,
    is_remote_fqid,
)
from interactions.models import Comment, Like
from nodes.remote import find_node_for_author_fqid, remote_recipients_for_author, send_inbox_item_to_author
from social.models import Follow
from .models import Entry, EntryDelivery

logging = __import__("logging")


def annotate_entry(entry):
    """Execute annotate entry."""
    entry.display_has_gallery = False
    entry.display_has_image = is_base64_image_content_type(entry.content_type)
    entry.display_is_markdown = "text/markdown" in (entry.content_type or "")
    entry.display_image_src = data_url_from_entry_content(
        entry.content_type, entry.content)
    entry.display_gallery_json = "[]"
    entry.display_text = str(entry.content or "").lstrip()
    entry.description = str(entry.description or "").lstrip()
    entry.is_remote = False

    if entry.display_has_image:
        entry.display_text = ""

    return entry


def attach_entry_interaction_state(entry, user):
    """Execute attach entry interaction state."""
    entry.likes_count = Like.objects.filter(object_fqid=entry.fqid).count()
    entry.comments_count = Comment.objects.filter(
        entry_fqid=entry.fqid).count()
    entry.liked_by_me = bool(
        user.is_authenticated
        and Like.objects.filter(author_fqid=user.fqid, object_fqid=entry.fqid).exists()
    )
    return entry


# Serialization payload helpers

def base64_image_type_for_upload(upload):
    """Execute base64 image type for upload."""
    raw = str(getattr(upload, "content_type", "") or "").lower()
    if raw == "image/png":
        return "image/png;base64"
    if raw in {"image/jpeg", "image/jpg"}:
        return "image/jpeg;base64"
    return "application/base64"


def encode_upload_to_base64(upload):
    """Execute encode upload to base64."""
    return base64.b64encode(upload.read()).decode("ascii")


def author_payload(author):
    """Execute author payload."""
    return {
        "type": "author",
        "id": author.fqid,
        "displayName": author.display_name,
        "username": author.username,
        "host": author.host,
        "github": author.github or "",
        "profileImage": author.profile_image or "",
    }


def _author_payload_from_fqid(author_fqid):
    """Execute author payload from fqid."""
    author = Author.objects.filter(fqid=author_fqid).first()
    if author:
        return author_payload(author)
    return {"type": "author", "id": author_fqid}


def entry_payload(entry):
    """Execute entry payload."""
    return {
        "type": "entry",
        "id": entry.fqid,
        "title": entry.title,
        "description": entry.description,
        "contentType": entry.content_type,
        "content": entry.content,
        "visibility": entry.visibility,
        "published": entry.published.isoformat(),
        "updated": entry.updated_at.isoformat(),
        "author": author_payload(entry.author),
    }


def comment_payload(comment):
    """Execute comment payload."""
    return {
        "type": "comment",
        "id": comment.fqid,
        "author": _author_payload_from_fqid(comment.author_fqid),
        "entry": comment.entry_fqid,
        "entry_url": comment.entry_fqid,
        "comment": comment.comment,
        "contentType": comment.content_type,
        "content_type": comment.content_type,
        "published": comment.published.isoformat(),
    }


def like_payload(like):
    """Execute like payload."""
    return {
        "type": "like",
        "id": like.fqid,
        "author": _author_payload_from_fqid(like.author_fqid),
        "object": like.object_fqid,
        "published": like.published.isoformat(),
    }


# Federation helpers

def push_entry_to_remote_inboxes(entry, update=False):
    """Execute push entry to remote inboxes."""
    payload = entry_payload(entry)
    recipients = set()
    if entry.visibility != "DELETED":
        recipients.update(
            remote_recipients_for_author(entry.author.fqid, visibility=entry.visibility)
        )

    if update or entry.visibility == "DELETED":
        recipients.update(
            entry.deliveries.values_list("recipient_fqid", flat=True)
        )

    recipients = {
        str(fqid).strip().rstrip("/")
        for fqid in recipients
        if str(fqid).strip().rstrip("/") != str(entry.author.fqid).strip().rstrip("/")
    }

    method = "PUT" if update else "POST"
    for recipient_fqid in sorted(recipients):
        delivered = send_inbox_item_to_author(recipient_fqid, payload, method=method)
        if delivered:
            EntryDelivery.objects.update_or_create(
                entry=entry,
                recipient_fqid=recipient_fqid,
                defaults={"recipient_node": find_node_for_author_fqid(recipient_fqid)},
            )


def push_comment_to_remote_inboxes(comment):
    """Execute push comment to remote inboxes."""
    payload = comment_payload(comment)
    entry = Entry.objects.filter(fqid=comment.entry_fqid).first()
    if not entry:
        return
    recipients = [entry.author.fqid] if is_remote_fqid(entry.author.fqid) else []
    logger = logging.getLogger(__name__)
    logger.info("Push comment: comment=%s entry=%s recipients=%s",
                comment.fqid, entry.fqid, recipients)
    for recipient_fqid in recipients:
        try:
            ok = send_inbox_item_to_author(recipient_fqid, payload)
            logger.info("Push comment result: to=%s ok=%s", recipient_fqid, ok)
        except Exception:
            logger.exception("Failed to push comment %s to %s",
                             comment.fqid, recipient_fqid)


def push_like_to_remote_inboxes(like):
    """Execute push like to remote inboxes."""
    payload = like_payload(like)
    entry = Entry.objects.filter(fqid=like.object_fqid).first()
    if entry:
        recipients = [entry.author.fqid] if is_remote_fqid(entry.author.fqid) else []
        logger = logging.getLogger(__name__)
        logger.info("Push like: like=%s entry=%s recipients=%s",
                    like.fqid, entry.fqid, recipients)
        for recipient_fqid in recipients:
            try:
                ok = send_inbox_item_to_author(recipient_fqid, payload)
                logger.info("Push like result: to=%s ok=%s",
                            recipient_fqid, ok)
            except Exception:
                logger.exception("Failed to push like %s to %s",
                                 like.fqid, recipient_fqid)
        return
    comment = Comment.objects.filter(fqid=like.object_fqid).first()
    if not comment:
        return
    entry = Entry.objects.filter(fqid=comment.entry_fqid).first()
    if not entry:
        return
    recipients = [entry.author.fqid] if is_remote_fqid(entry.author.fqid) else []
    for recipient_fqid in recipients:
        try:
            ok = send_inbox_item_to_author(recipient_fqid, payload)
            logging.getLogger(__name__).info(
                "Push like (comment) result: to=%s ok=%s", recipient_fqid, ok)
        except Exception:
            logging.getLogger(__name__).exception(
                "Failed to push like (comment) %s to %s", like.fqid, recipient_fqid)


def remote_entry_from_inbox_item(item):
    """Execute remote entry from inbox item."""
    payload = item.payload or {}
    author_data = payload.get(
        "author", {}) if isinstance(payload, dict) else {}
    content_type = str(payload.get("contentType", "text/plain"))
    content = payload.get("content", "")
    visibility = str(payload.get("visibility", "PUBLIC") or "PUBLIC").upper()
    author_fqid = str(author_data.get("id", "")).strip(
    ) or author_fqid_from_entry_fqid(payload.get("id", ""))

    author_ns = SimpleNamespace(
        id=author_fqid,
        display_name=author_data.get(
            "displayName") or author_data.get("id", "Remote Author"),
        profile_image=author_data.get("profileImage", ""),
    )

    published = coerce_datetime(payload.get("published"), item.received)
    updated = coerce_datetime(payload.get("updated"), published)

    entry_ns = SimpleNamespace(
        id=payload.get("id") or str(uuid.uuid4()),
        fqid=payload.get("id") or "",
        target_author_fqid=author_fqid,
        author=author_ns,
        title=payload.get("title", "Remote Entry"),
        description=str(payload.get("description", "") or "").lstrip(),
        content_type=content_type,
        content=content if isinstance(content, str) else json.dumps(content),
        visibility=visibility,
        published=published,
        updated_at=updated,
        likes_count=(payload.get("likes") or {}).get("count", 0),
        comments_count=(payload.get("comments") or {}).get("count", 0),
        liked_by_me=False,
        is_remote=True,
        display_has_gallery=False,
        display_has_image=False,
        display_is_markdown=False,
        display_image_src="",
        display_gallery_json="[]",
        display_text="",
        can_remote_interact=bool((payload.get("id") or "") and author_fqid),
    )

    if is_base64_image_content_type(content_type):
        entry_ns.display_has_image = True
        entry_ns.display_image_src = data_url_from_entry_content(
            content_type, content)
    elif "text/markdown" in content_type:
        entry_ns.display_is_markdown = True
        entry_ns.display_text = content if isinstance(content, str) else ""
    elif content_type.startswith("image/") and isinstance(content, str) and content.startswith("http"):
        entry_ns.display_has_image = True
        entry_ns.display_image_src = content
    else:
        entry_ns.display_text = content if isinstance(content, str) else ""

    return entry_ns


def remote_entry_interaction_state(entry_fqid, user):
    """Execute remote entry interaction state."""
    fqid = str(entry_fqid or "").strip()
    likes_count = Like.objects.filter(object_fqid=fqid).count()
    comments_count = Comment.objects.filter(entry_fqid=fqid).count()
    liked_by_me = bool(
        user.is_authenticated
        and Like.objects.filter(author_fqid=user.fqid, object_fqid=fqid).exists()
    )
    return likes_count, comments_count, liked_by_me


# Authorization helpers

def is_friend(me, author):
    """Return whether friend."""
    following = Follow.objects.filter(
        follower_fqid=me.fqid, following_fqid=author.fqid, accepted=True).exists()
    followed_by = Follow.objects.filter(
        follower_fqid=author.fqid, following_fqid=me.fqid, accepted=True).exists()
    return following and followed_by


def is_follower(me, author):
    """Return whether follower."""
    return Follow.objects.filter(follower_fqid=me.fqid, following_fqid=author.fqid, accepted=True).exists()


def can_user_see_entry(user, entry):
    """Execute can user see entry."""
    if entry.visibility == "DELETED":
        return bool(user.is_authenticated and user.is_staff)
    if entry.visibility in ("PUBLIC", "UNLISTED"):
        return True
    if entry.visibility == "FRIENDS":
        if not user.is_authenticated:
            return False
        if entry.author == user:
            return True
        return is_friend(user, entry.author)
    return False


def visible_comments_queryset(user, entry):
    """Execute visible comments queryset."""
    qs = Comment.objects.filter(entry_fqid=entry.fqid).order_by("-published")
    if entry.visibility != "FRIENDS":
        return qs
    if not user.is_authenticated:
        return qs.none()
    if user == entry.author or is_friend(user, entry.author):
        return qs
    return qs.filter(author_fqid=user.fqid)


def like_response_redirect(request, fallback_url):
    """Execute like response redirect."""
    next_url = request.POST.get("next", "").strip()
    if next_url:
        return redirect(next_url)
    return redirect(fallback_url)


def parse_image_index(request):
    """Execute parse image index."""
    raw = request.GET.get("index", request.GET.get("image", "0"))
    try:
        index = int(raw)
    except (TypeError, ValueError):
        raise Http404
    if index < 0:
        raise Http404
    return index


def decode_image_entry(entry, image_index=0):
    """Execute decode image entry."""
    if image_index != 0:
        return None
    if not is_base64_image_content_type(entry.content_type):
        return None
    try:
        raw = base64.b64decode(str(entry.content or ""))
    except Exception:
        return None
    response = HttpResponse(raw, content_type="application/octet-stream")
    response["X-Image-Index"] = str(image_index)
    response["X-Image-Count"] = "1"
    return response


def resolve_comment_for_entry(entry, comment_ref):
    """Execute resolve comment for entry."""
    decoded = unquote(comment_ref)
    comment = Comment.objects.filter(
        entry_fqid=entry.fqid, fqid=decoded).first()
    if comment:
        return comment
    comment = Comment.objects.filter(
        entry_fqid=entry.fqid, pk=comment_ref).first()
    if comment:
        return comment
    raise Http404


def entry_visibility_allows_remote(entry):
    """Execute entry visibility allows remote."""
    return entry.visibility in ("PUBLIC", "UNLISTED")


def comment_visible_for_list(comment, request, include_private):
    """Execute comment visible for list."""
    if include_private:
        return True
    entry = Entry.objects.filter(fqid=comment.entry_fqid).first()
    if not entry:
        return False
    return entry_visibility_allows_remote(entry)


def like_visible_for_list(like, include_private):
    """Execute like visible for list."""
    if include_private:
        return True

    entry = Entry.objects.filter(fqid=like.object_fqid).first()
    if entry:
        return entry_visibility_allows_remote(entry)

    comment = Comment.objects.filter(fqid=like.object_fqid).first()
    if not comment:
        return False
    parent = Entry.objects.filter(fqid=comment.entry_fqid).first()
    return bool(parent and entry_visibility_allows_remote(parent))
