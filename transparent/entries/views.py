"""View logic for the entries app."""

import logging
import uuid
from django.core.paginator import Paginator
from urllib.parse import unquote
from django.utils import timezone

from authors.models import Author
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from rest_framework import status as drf_status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import EntriesPagination, parse_pagination
import core.utils as cutils
import entries.utils as eutils
from interactions.models import Comment, Like
from inbox.models import InboxItem
from social.models import Follow
from nodes.remote import send_inbox_item_to_author

from .models import Entry
from .serializers import CommentSerializer, EntrySerializer
from interactions.serializers import LikeSerializer, build_comments_object, build_likes_object
from core.fqid import api_to_web_url
from nodes.models import Node, RemoteAuthor

from rest_framework.permissions import AllowAny

logger = logging.getLogger(__name__)


def _active_node_scopes():
    """Execute active node scopes."""
    scopes = set()
    for node in Node.objects.filter(active=True).only("base_url"):
        api_base = cutils.normalize_api_base(node.base_url)
        if not api_base:
            continue
        scopes.add(api_base)
        if api_base.endswith("/api"):
            scopes.add(api_base[:-4])
    return scopes


@login_required
def stream(request):
    """Execute stream."""
    # unlisted = public but not showin in public stream unless followers
    # we need to filter the entries by public, unlisted, and friends only (of people i follow)
    # show the most recent entries, and not show entries that deleted
    me = request.user

    def _norm_fqid(value):
        """Execute norm fqid."""
        return str(value or "").strip().rstrip("/")

    following = {
        _norm_fqid(fqid)
        for fqid in Follow.objects.filter(follower_fqid=me.fqid, accepted=True)
        .values_list("following_fqid", flat=True)
        if _norm_fqid(fqid)
    }

    # Friends are mutual followers
    followers = {
        _norm_fqid(fqid)
        for fqid in Follow.objects.filter(following_fqid=me.fqid, accepted=True)
        .values_list("follower_fqid", flat=True)
        if _norm_fqid(fqid)
    }
    friends = following & followers  # check this
    my_entries = Entry.objects.filter(
        author=me,
        visibility__in=("PUBLIC", "FRIENDS"),
    )
    public_entries = Entry.objects.filter(
        visibility="PUBLIC").exclude(author=me)
    friends_entries = Entry.objects.filter(
        visibility="FRIENDS", author__fqid__in=friends).exclude(author=me)
    deleted_entries = Entry.objects.none()
    # if me.is_staff:
    #     deleted_entries = Entry.objects.filter(visibility="DELETED")
    # Combine them all together, remove duplicates, sort newest first
    entries = (my_entries | public_entries |
               friends_entries | deleted_entries).distinct().order_by("-updated_at")

    # Pending follow request count for navbar badge
    pending_count = Follow.objects.filter(
        following_fqid=me.fqid, accepted=False
    ).count()

    display_entries = []
    for entry in entries:
        annotated = eutils.attach_entry_interaction_state(
            eutils.annotate_entry(entry), request.user)
        annotated.share_url = (
            f"{request.scheme}://{request.get_host()}"
            f"/authors/{entry.author.id}/entries/{entry.id}/"
        )
        display_entries.append(annotated)

    active_scopes = _active_node_scopes()

    inbox_entries = []
    for item in InboxItem.objects.filter(type="entry").order_by("-received"):
        remote_entry = eutils.remote_entry_from_inbox_item(item)
        remote_author_fqid = str(
            getattr(remote_entry.author, "id", "")).strip()
        remote_author_norm = _norm_fqid(remote_author_fqid)
        if not cutils.is_from_active_node(remote_author_fqid, active_scopes):
            continue
        remote_visibility = str(
            getattr(remote_entry, "visibility", "PUBLIC") or "PUBLIC").upper()

        if remote_visibility == "PUBLIC":
            (
                remote_entry.likes_count,
                remote_entry.comments_count,
                remote_entry.liked_by_me,
            ) = eutils.remote_entry_interaction_state(remote_entry.fqid, request.user)
            remote_entry.share_url = cutils.shareable_entry_web_url(
                remote_entry.fqid)
            inbox_entries.append(remote_entry)
            continue

        if remote_visibility == "UNLISTED":
            if remote_author_norm in following or remote_author_norm in friends:
                (
                    remote_entry.likes_count,
                    remote_entry.comments_count,
                    remote_entry.liked_by_me,
                ) = eutils.remote_entry_interaction_state(remote_entry.fqid, request.user)
                remote_entry.share_url = cutils.shareable_entry_web_url(
                    remote_entry.fqid)
                inbox_entries.append(remote_entry)
            continue

        if remote_visibility == "FRIENDS":
            if remote_author_norm in friends:
                (
                    remote_entry.likes_count,
                    remote_entry.comments_count,
                    remote_entry.liked_by_me,
                ) = eutils.remote_entry_interaction_state(remote_entry.fqid, request.user)
                remote_entry.share_url = cutils.shareable_entry_web_url(
                    remote_entry.fqid)
                inbox_entries.append(remote_entry)

    merged_entries = list(display_entries) + inbox_entries
    # Deduplicate merged entries by fqid (prefer local entries when present).
    merged_by_fqid = {}

    def _key_for(e):
        """Execute key for."""
        return str(getattr(e, "fqid", getattr(e, "id", "")) or "").strip()

    for e in merged_entries:
        k = _key_for(e)
        if not k:
            # fallback to timestamp-unique
            k = f"_anon_{len(merged_by_fqid)}"
        existing = merged_by_fqid.get(k)
        if not existing:
            merged_by_fqid[k] = e
        else:
            # keep the newest by updated_at
            if getattr(e, "updated_at", timezone.now()) > getattr(existing, "updated_at", timezone.now()):
                merged_by_fqid[k] = e

    merged_entries = list(merged_by_fqid.values())
    logger.info(
        "Stream build: user=%s local_entries=%s inbox_entries=%s merged=%s",
        request.user.username,
        len(display_entries),
        len(inbox_entries),
        len(merged_entries),
    )
    merged_entries.sort(key=lambda e: getattr(
        e, "updated_at", timezone.now()), reverse=True)

    return render(
        request,
        "stream.html",
        {"entries": merged_entries, "active_nav": "home",
            "pending_count": pending_count},
    )


def _remote_follow_request_display(me, follower_fqid):
    """Execute remote follow request display."""
    follower_fqid = str(follower_fqid or "").strip()
    fallback_name = follower_fqid.rstrip("/").split("/")[-1][:20] or "remote"

    actor = {}
    inbox_match = InboxItem.objects.filter(
        author=me,
        type="follow",
    ).order_by("-received")

    for item in inbox_match:
        payload = item.payload or {}
        candidate = payload.get("actor", {})
        if str(candidate.get("id", "")).strip() == follower_fqid:
            actor = candidate
            break

    display_name = actor.get("displayName") or fallback_name
    username = (
        actor.get("username")
        or actor.get("preferredUsername")
        or display_name
        or "remote"
    )
    profile_image = actor.get("profileImage", "")

    return {
        "fqid": follower_fqid,
        "display_name": display_name,
        "id": None,
        "profile_image": profile_image,
        "username": username,
        "is_remote": True,
    }


@login_required
def follow_requests_page(request):
    """Dedicated page listing all pending follow requests."""
    me = request.user
    pending_follows = Follow.objects.filter(
        following_fqid=me.fqid, accepted=False
    ).order_by("-created")
    pending_authors = []
    for f in pending_follows:
        try:
            author = Author.objects.get(fqid=f.follower_fqid)
            if cutils.is_remote_fqid(author.fqid):
                pending_authors.append(
                    {
                        "fqid": author.fqid,
                        "display_name": author.display_name,
                        "id": None,
                        "profile_image": author.profile_image,
                        "username": author.username,
                        "is_remote": True,
                    }
                )
            else:
                pending_authors.append(author)
        except Author.DoesNotExist:
            pending_authors.append(
                _remote_follow_request_display(me, f.follower_fqid)
            )

    pending_count = len(pending_authors)
    return render(request, "follow_requests.html", {
        "pending_requests": pending_authors,
        "pending_count": pending_count,
    })


@login_required
@require_POST
def create_entry(request):
    """Create entry."""
    title = request.POST.get("title", "").strip()
    text_content = request.POST.get("content", "").strip()
    visibility = request.POST.get("visibility", "PUBLIC")
    use_markdown = bool(request.POST.get("use_markdown"))
    image_file = request.FILES.get("image")

    if not text_content and not image_file:
        messages.error(request, "Post content cannot be empty.")
        return redirect("stream")

    content_type = "text/markdown" if use_markdown else "text/plain"
    content_value = text_content

    if image_file:
        content_type = eutils.base64_image_type_for_upload(image_file)
        content_value = eutils.encode_upload_to_base64(image_file)

    entry = Entry.objects.create(
        author=request.user,
        title=title,
        content=content_value,
        content_type=content_type,
        visibility=visibility,
    )

    eutils.push_entry_to_remote_inboxes(entry)

    return redirect("stream")


@login_required
def profile(request):
    """Execute profile."""
    if request.user.is_staff:
        entries = Entry.objects.filter(
            visibility="DELETED").order_by("-published")
    else:
        entries = request.user.entries.exclude(
            visibility="DELETED").order_by("-published")

    # Keep remote author display local-only (no direct remote fetches).
    def _resolve_remote_fqid(fqid):
        """Execute resolve remote fqid."""
        fqid = str(fqid or "").strip()
        short_name = fqid.rstrip("/").split("/")[-1][:12]

        actor = {}
        for item in InboxItem.objects.filter(author=request.user).order_by("-received"):
            payload = item.payload or {}
            candidate = {}
            if item.type == "follow":
                candidate = payload.get("actor", {})
            elif item.type in {"entry", "comment", "like", "follow_accepted", "follow_denied"}:
                candidate = payload.get("author") or payload.get("actor") or {}

            if str(candidate.get("id", "")).strip().rstrip("/") == fqid.rstrip("/"):
                actor = candidate
                break

        display_name = actor.get("displayName") or short_name
        username = (
            actor.get("username")
            or actor.get("preferredUsername")
            or display_name
            or "remote"
        )
        return {
            "fqid": fqid,
            "display_name": display_name,
            "id": None,
            "profile_image": actor.get("profileImage", ""),
            "username": username,
        }

    # Followers: people who follow the current user (accepted)
    follower_follows = Follow.objects.filter(
        following_fqid=request.user.fqid, accepted=True
    ).order_by("-created")
    followers_list = []
    for f in follower_follows:
        try:
            author = Author.objects.get(fqid=f.follower_fqid)
            followers_list.append(author)
        except Author.DoesNotExist:
            followers_list.append(_resolve_remote_fqid(f.follower_fqid))

    # Following: people the current user follows (accepted)
    following_follows = Follow.objects.filter(
        follower_fqid=request.user.fqid, accepted=True
    ).order_by("-created")
    following_list = []
    for f in following_follows:
        try:
            author = Author.objects.get(fqid=f.following_fqid)
            following_list.append(author)
        except Author.DoesNotExist:
            following_list.append(_resolve_remote_fqid(f.following_fqid))

    # Pending follow requests (people who want to follow the current user)
    pending_follows = Follow.objects.filter(
        following_fqid=request.user.fqid, accepted=False
    ).order_by("-created")
    pending_authors = []
    for f in pending_follows:
        try:
            author = Author.objects.get(fqid=f.follower_fqid)
            pending_authors.append(author)
        except Author.DoesNotExist:
            pending_authors.append(
                _remote_follow_request_display(request.user, f.follower_fqid)
            )

    display_entries = [
        eutils.attach_entry_interaction_state(
            eutils.annotate_entry(e), request.user)
        for e in entries
    ]

    return render(request, "profile.html", {
        "entries": display_entries,
        "followers_count": len(followers_list),
        "following_count": len(following_list),
        "followers_list": followers_list,
        "following_list": following_list,
        "pending_requests": pending_authors,
        "pending_count": len(pending_authors),
        "active_nav": "profile",
    })


@login_required
@require_POST
def edit_entry(request, entry_id):
    """Execute edit entry."""
    entry = get_object_or_404(Entry, pk=entry_id, author=request.user)

    title = request.POST.get("title", "").strip()
    text_content = request.POST.get("content", "").strip()
    description = request.POST.get("description", "").strip()
    visibility = request.POST.get("visibility", entry.visibility)
    use_markdown = bool(request.POST.get("use_markdown"))
    image_file = request.FILES.get("image")

    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )

    has_existing_image = cutils.is_base64_image_content_type(
        entry.content_type)

    if not text_content and not image_file and not has_existing_image:
        if wants_json:
            return JsonResponse({"error": "Post content cannot be empty."}, status=400)
        messages.error(request, "Post content cannot be empty.")
        return redirect("/profile/")

    if image_file:
        entry.content_type = eutils.base64_image_type_for_upload(image_file)
        entry.content = eutils.encode_upload_to_base64(image_file)
    else:
        entry.content_type = "text/markdown" if use_markdown else "text/plain"
        entry.content = text_content

    entry.title = title
    entry.description = description
    entry.visibility = visibility
    entry.save()

    eutils.push_entry_to_remote_inboxes(entry, update=True)

    if wants_json:
        return JsonResponse(
            {
                "id": str(entry.id),
                "title": entry.title,
                "description": entry.description,
                "visibility": entry.visibility,
                "content_type": entry.content_type,
                "content": entry.content,
                "published": entry.published.isoformat(),
            }
        )

    return redirect("/profile/")


@login_required
@require_POST
def delete_entry(request, entry_id):
    """Delete entry."""
    # should be this?
    entry = get_object_or_404(Entry, pk=entry_id, author=request.user)
    entry.visibility = "DELETED"
    entry.save()
    eutils.push_entry_to_remote_inboxes(entry, update=True)
    return redirect("/profile/")


def entry_detail(request, entry_id):
    """Execute entry detail."""
    entry = get_object_or_404(Entry, pk=entry_id)

    # Deleted: only admins can see
    if entry.visibility == "DELETED":
        if not request.user.is_authenticated or not request.user.is_staff:
            raise Http404

    # Friends-only: must be authenticated and be a friend of the author
    if entry.visibility == "FRIENDS":
        if not request.user.is_authenticated:
            raise Http404
        me = request.user
        # Author can always see their own entry
        if entry.author != me:
            following = set(
                Follow.objects.filter(follower_fqid=me.fqid, accepted=True)
                .values_list("following_fqid", flat=True)
            )
            followers = set(
                Follow.objects.filter(following_fqid=me.fqid, accepted=True)
                .values_list("follower_fqid", flat=True)
            )
            friends = following & followers
            if entry.author.fqid not in friends:
                raise Http404

    # Public and unlisted: anyone with the link can see
    entry = eutils.attach_entry_interaction_state(
        eutils.annotate_entry(entry), request.user)
    comments = list(eutils.visible_comments_queryset(request.user, entry))
    for comment in comments:
        comment.likes_count = Like.objects.filter(
            object_fqid=comment.fqid).count()
        comment.liked_by_me = bool(
            request.user.is_authenticated
            and Like.objects.filter(
                author_fqid=request.user.fqid, object_fqid=comment.fqid
            ).exists()
        )
        try:
            comment.author = Author.objects.get(fqid=comment.author_fqid)
        except Author.DoesNotExist:
            comment.author = None

    pending_count = 0
    if request.user.is_authenticated:
        pending_count = Follow.objects.filter(
            following_fqid=request.user.fqid, accepted=False
        ).count()

    return render(
        request,
        "entry_detail.html",
        {
            "entry": entry,
            "comments": comments,
            "active_nav": "home",
            "pending_count": pending_count,
        },
    )


def entry_detail_by_author(request, author_id, entry_id):
    """Author-style entry URL that renders the same entry detail page."""
    get_object_or_404(Entry, pk=entry_id, author__id=author_id)
    return entry_detail(request, entry_id)


def _remote_comment_author_display(author_fqid, viewer):
    """Resolve a readable display name for a remote comment author."""
    fqid = str(author_fqid or "").strip()
    if not fqid:
        return "Unknown author"

    local_author = Author.objects.filter(fqid=fqid).first()
    if local_author:
        return local_author.display_name

    remote_author = RemoteAuthor.objects.filter(fqid=fqid).first()
    if remote_author and remote_author.display_name:
        return remote_author.display_name

    for item in InboxItem.objects.filter(author=viewer).order_by("-received"):
        payload = item.payload or {}
        actor = {}
        if item.type == "follow":
            actor = payload.get("actor", {})
        elif item.type in {"entry", "comment", "like"}:
            actor = payload.get("author", {})

        if str(actor.get("id", "")).strip() == fqid:
            display_name = str(actor.get("displayName", "")).strip()
            if display_name:
                return display_name
            break

    return fqid.rstrip("/").split("/")[-1]


@login_required
def remote_entry_detail(request):
    """Render a remote entry with full comment detail and interaction state."""
    entry_fqid = str(request.GET.get("fqid", "")).strip()
    if not entry_fqid:
        raise Http404

    requested_target_author_fqid = str(
        request.GET.get("author", "")
    ).strip()

    normalized_entry_fqid = entry_fqid.rstrip("/")
    inbox_item = None
    for item in InboxItem.objects.filter(type="entry").order_by("-received"):
        payload = item.payload or {}
        payload_entry_id = str(payload.get("id", "")).strip().rstrip("/")
        if payload_entry_id == normalized_entry_fqid:
            inbox_item = item
            break

    if inbox_item is None:
        raise Http404

    entry = eutils.remote_entry_from_inbox_item(inbox_item)
    (
        entry.likes_count,
        entry.comments_count,
        entry.liked_by_me,
    ) = eutils.remote_entry_interaction_state(entry.fqid, request.user)

    if requested_target_author_fqid:
        entry.target_author_fqid = requested_target_author_fqid
    elif not str(getattr(entry, "target_author_fqid", "")).strip():
        entry.target_author_fqid = cutils.author_fqid_from_entry_fqid(
            entry.fqid)

    comments = list(Comment.objects.filter(
        entry_fqid=entry.fqid).order_by("-published"))
    for comment in comments:
        comment.likes_count = Like.objects.filter(
            object_fqid=comment.fqid).count()
        comment.liked_by_me = bool(
            Like.objects.filter(
                author_fqid=request.user.fqid,
                object_fqid=comment.fqid,
            ).exists()
        )
        comment.author_display = _remote_comment_author_display(
            comment.author_fqid,
            request.user,
        )

    pending_count = Follow.objects.filter(
        following_fqid=request.user.fqid,
        accepted=False,
    ).count()

    return render(
        request,
        "remote_entry_detail.html",
        {
            "entry": entry,
            "comments": comments,
            "active_nav": "home",
            "pending_count": pending_count,
        },
    )


# =============================================================================
# REST API views
# =============================================================================

# (direct calls to eutils, no wrapper functions)

@login_required
@require_POST
def create_comment(request, entry_id):
    """Create comment."""
    entry = get_object_or_404(Entry, pk=entry_id)
    if not eutils.can_user_see_entry(request.user, entry):
        raise Http404

    text = request.POST.get("comment", "").strip()
    if not text:
        messages.error(request, "Comment cannot be empty.")
        return eutils.like_response_redirect(request, f"/api/entries/{entry.id}/")

    comment = Comment.objects.create(
        fqid=f"{request.user.host}comments/{uuid.uuid4()}",
        author_fqid=request.user.fqid,
        entry_fqid=entry.fqid,
        comment=text,
        content_type="text/plain",
    )
    eutils.push_comment_to_remote_inboxes(comment)
    return eutils.like_response_redirect(request, f"/api/entries/{entry.id}/")


@login_required
@require_POST
def like_entry(request, entry_id):
    """Execute like entry."""
    entry = get_object_or_404(Entry, pk=entry_id)
    if not eutils.can_user_see_entry(request.user, entry):
        raise Http404

    like, created = Like.objects.get_or_create(
        author_fqid=request.user.fqid,
        object_fqid=entry.fqid,
        defaults={"fqid": f"{request.user.host}likes/{uuid.uuid4()}"},
    )
    logger.info("Like action: user=%s entry_id=%s like_id=%s created=%s",)
    if created:
        eutils.push_like_to_remote_inboxes(like)

    return eutils.like_response_redirect(request, f"/api/entries/{entry.id}/")


@login_required
@require_POST
def like_remote_entry(request):
    """Execute like remote entry."""
    entry_fqid = str(request.POST.get("entry_fqid", "")).strip()
    target_author_fqid = str(request.POST.get(
        "target_author_fqid", "")).strip()
    if not target_author_fqid:
        target_author_fqid = cutils.author_fqid_from_entry_fqid(entry_fqid)

    if not entry_fqid or not target_author_fqid:
        messages.error(
            request,
            "Could not like this remote item because its remote metadata is incomplete.",
        )
        return eutils.like_response_redirect(request, "/stream/")

    like, created = Like.objects.get_or_create(
        author_fqid=request.user.fqid,
        object_fqid=entry_fqid,
        defaults={"fqid": f"{request.user.host}likes/{uuid.uuid4()}"},
    )

    if created:
        payload = {
            "type": "like",
            "id": like.fqid,
            "author": eutils.author_payload(request.user),
            "object": entry_fqid,
            "published": like.published.isoformat(),
        }
        send_inbox_item_to_author(target_author_fqid, payload)

    return eutils.like_response_redirect(request, "/stream/")


@login_required
@require_POST
def create_remote_entry_comment(request):
    """Create remote entry comment."""
    entry_fqid = str(request.POST.get("entry_fqid", "")).strip()
    target_author_fqid = str(request.POST.get(
        "target_author_fqid", "")).strip()
    if not target_author_fqid:
        target_author_fqid = cutils.author_fqid_from_entry_fqid(entry_fqid)
    comment_text = str(request.POST.get("comment", "")).strip()

    if not entry_fqid or not target_author_fqid:
        messages.error(
            request,
            "Could not comment on this remote item because its remote metadata is incomplete.",
        )
        return eutils.like_response_redirect(request, "/stream/")

    if not comment_text:
        messages.error(request, "Comment cannot be empty.")
        return eutils.like_response_redirect(request, "/stream/")

    comment = Comment.objects.create(
        fqid=f"{request.user.host}comments/{uuid.uuid4()}",
        author_fqid=request.user.fqid,
        entry_fqid=entry_fqid,
        comment=comment_text,
        content_type="text/plain",
    )

    payload = {
        "type": "comment",
        "id": comment.fqid,
        "author": eutils.author_payload(request.user),
        "entry": entry_fqid,
        "entry_url": entry_fqid,
        "comment": comment.comment,
        "contentType": comment.content_type,
        "content_type": comment.content_type,
        "published": comment.published.isoformat(),
    }
    send_inbox_item_to_author(target_author_fqid, payload)
    return eutils.like_response_redirect(request, "/stream/")


@login_required
@require_POST
def like_comment(request, comment_id):
    """Execute like comment."""
    comment = get_object_or_404(Comment, pk=comment_id)
    entry = get_object_or_404(Entry, fqid=comment.entry_fqid)

    can_view_comment = comment.author_fqid == request.user.fqid or bool(
        eutils.visible_comments_queryset(
            request.user, entry).filter(pk=comment.pk).exists()
    )
    if not can_view_comment:
        raise Http404

    like, created = Like.objects.get_or_create(
        author_fqid=request.user.fqid,
        object_fqid=comment.fqid,
        defaults={"fqid": f"{request.user.host}likes/{uuid.uuid4()}"},
    )
    if created:
        eutils.push_like_to_remote_inboxes(like)
    return eutils.like_response_redirect(request, f"/api/entries/{entry.id}/")


class EntryDetailAPIView(APIView):
    permission_classes = [AllowAny]

    def get_entry(self, author_fqid, entry_fqid):
        """Return entry."""
        author = get_object_or_404(Author, pk=author_fqid)
        return get_object_or_404(Entry, pk=entry_fqid, author=author)

    def get(self, request, author_fqid, entry_fqid):
        """Execute get."""
        entry = self.get_entry(author_fqid, entry_fqid)
        if not eutils.can_user_see_entry(request.user, entry):
            return Response(
                {"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND
            )
        serializer = EntrySerializer(entry, context={"request": request})
        return Response(serializer.data)

    def delete(self, request, author_fqid, entry_fqid):
        """Execute delete."""
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        entry = self.get_entry(author_fqid, entry_fqid)
        if entry.author != request.user:
            return Response(
                {"detail": "Forbidden."}, status=drf_status.HTTP_403_FORBIDDEN
            )
        entry.visibility = "DELETED"
        entry.save()
        eutils.push_entry_to_remote_inboxes(entry, update=True)
        return Response(status=drf_status.HTTP_204_NO_CONTENT)

    def put(self, request, author_fqid, entry_fqid):
        """Execute put."""
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        entry = self.get_entry(author_fqid, entry_fqid)
        if entry.author != request.user:
            return Response(
                {"detail": "Forbidden."}, status=drf_status.HTTP_403_FORBIDDEN
            )
        serializer = EntrySerializer(
            entry, data=request.data, partial=False, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        updated_entry = serializer.save()
        eutils.push_entry_to_remote_inboxes(updated_entry, update=True)
        return Response(serializer.data)


class EntryFQIDAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, fqid):
        """Execute get."""
        decoded_fqid = unquote(fqid)
        entry = get_object_or_404(Entry, fqid=decoded_fqid)
        if not eutils.can_user_see_entry(request.user, entry):
            return Response(
                {"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND
            )
        serializer = EntrySerializer(entry, context={"request": request})
        return Response(serializer.data)


class EntryImageBySerialAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, author_fqid, entry_fqid):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        entry = get_object_or_404(Entry, pk=entry_fqid, author=author)
        if not eutils.can_user_see_entry(request.user, entry):
            raise Http404
        image_index = eutils.parse_image_index(request)
        response = eutils.decode_image_entry(entry, image_index=image_index)
        if response is None:
            raise Http404
        return response


class EntryImageByFQIDAPIView(APIView):

    permission_classes = [AllowAny]

    def get(self, request, fqid):
        """Execute get."""
        decoded_fqid = unquote(fqid)
        entry = get_object_or_404(Entry, fqid=decoded_fqid)
        if not eutils.can_user_see_entry(request.user, entry):
            raise Http404
        image_index = eutils.parse_image_index(request)
        response = eutils.decode_image_entry(entry, image_index=image_index)
        if response is None:
            raise Http404
        return response


class EntryListCreateAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, author_fqid):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        qs = Entry.objects.filter(author=author).order_by("-published")

        if not (request.user.is_authenticated and request.user.is_staff):
            qs = qs.exclude(visibility="DELETED")

        user = request.user
        if user.is_authenticated:
            if user.is_staff or user == author or eutils.is_friend(user, author):
                # Author / friend: see everything
                pass
            elif eutils.is_follower(user, author):
                # Follower: PUBLIC + UNLISTED
                qs = qs.filter(visibility__in=("PUBLIC", "UNLISTED"))
            else:
                # Other authenticated user: PUBLIC only
                qs = qs.filter(visibility="PUBLIC")
        else:
            # Unauthenticated: PUBLIC only
            qs = qs.filter(visibility="PUBLIC")

        paginator = EntriesPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = EntrySerializer(
            page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, author_fqid):
        """Execute post."""
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        author = get_object_or_404(Author, pk=author_fqid)
        if request.user != author:
            return Response(
                {"detail": "Forbidden."}, status=drf_status.HTTP_403_FORBIDDEN
            )

        data = request.data
        entry = Entry.objects.create(
            author=author,
            title=data.get("title", ""),
            description=data.get("description", ""),
            content=data.get("content", ""),
            content_type=data.get("contentType", "text/plain"),
            visibility=data.get("visibility", "PUBLIC"),
        )
        eutils.push_entry_to_remote_inboxes(entry)
        serializer = EntrySerializer(entry, context={"request": request})
        return Response(serializer.data, status=drf_status.HTTP_201_CREATED)


class EntryCommentsAPIView(APIView):
    permission_classes = [AllowAny]

    def get_entry(self, author_fqid, entry_fqid):
        """Return entry."""
        author = get_object_or_404(Author, pk=author_fqid)
        return get_object_or_404(Entry, pk=entry_fqid, author=author)

    def get(self, request, author_fqid, entry_fqid):
        """Execute get."""
        entry = self.get_entry(author_fqid, entry_fqid)
        if entry.visibility == "DELETED" and not (
            request.user.is_authenticated and request.user.is_staff
        ):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        comments_qs = eutils.visible_comments_queryset(request.user, entry)
        if not eutils.can_user_see_entry(request.user, entry) and not comments_qs.exists():
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(build_comments_object(request, comments_qs, entry.fqid, request.path))

    def post(self, request, author_fqid, entry_fqid):
        """Execute post."""
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        entry = self.get_entry(author_fqid, entry_fqid)
        if not eutils.can_user_see_entry(request.user, entry):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        comment_text = str(request.data.get("comment", "")).strip()
        if not comment_text:
            return Response(
                {"detail": "Comment cannot be empty."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        content_type = str(request.data.get(
            "contentType", "text/plain")).strip() or "text/plain"
        comment = Comment.objects.create(
            fqid=f"{request.user.host}comments/{uuid.uuid4()}",
            author_fqid=request.user.fqid,
            entry_fqid=entry.fqid,
            comment=comment_text,
            content_type=content_type,
        )
        eutils.push_comment_to_remote_inboxes(comment)
        serializer = CommentSerializer(comment)
        return Response(serializer.data, status=drf_status.HTTP_201_CREATED)


class EntryLikesAPIView(APIView):
    permission_classes = [AllowAny]

    def get_entry(self, author_fqid, entry_fqid):
        """Return entry."""
        author = get_object_or_404(Author, pk=author_fqid)
        return get_object_or_404(Entry, pk=entry_fqid, author=author)

    def get(self, request, author_fqid, entry_fqid):
        """Execute get."""
        entry = self.get_entry(author_fqid, entry_fqid)
        if not eutils.can_user_see_entry(request.user, entry):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        likes_qs = Like.objects.filter(
            object_fqid=entry.fqid).order_by("-published")
        return Response(build_likes_object(request, likes_qs, entry.fqid, request.path))

    def post(self, request, author_fqid, entry_fqid):
        """Execute post."""
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        entry = self.get_entry(author_fqid, entry_fqid)
        if not eutils.can_user_see_entry(request.user, entry):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        like, created = Like.objects.get_or_create(
            author_fqid=request.user.fqid,
            object_fqid=entry.fqid,
            defaults={"fqid": f"{request.user.host}likes/{uuid.uuid4()}"},
        )
        if created:
            eutils.push_like_to_remote_inboxes(like)
        serializer = LikeSerializer(like)
        return Response(
            serializer.data,
            status=(
                drf_status.HTTP_201_CREATED if created else drf_status.HTTP_200_OK),
        )

    def delete(self, request, author_fqid, entry_fqid):
        """Execute delete."""
        return Response(
            {"detail": "Unliking is disabled."},
            status=drf_status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class CommentLikesAPIView(APIView):
    permission_classes = [AllowAny]

    def get_comment(self, author_fqid, entry_fqid, comment_ref):
        """Return comment."""
        author = get_object_or_404(Author, pk=author_fqid)
        entry = get_object_or_404(Entry, pk=entry_fqid, author=author)
        comment = eutils.resolve_comment_for_entry(entry, comment_ref)
        return entry, comment

    def _can_view_comment(self, user, entry, comment):
        """Execute can view comment."""
        if entry.visibility != "FRIENDS":
            return eutils.can_user_see_entry(user, entry)
        if not user.is_authenticated:
            return False
        if user == entry.author or eutils.is_friend(user, entry.author):
            return True
        return comment.author_fqid == user.fqid

    def get(self, request, author_fqid, entry_fqid, comment_id=None, comment_ref=None):
        """Execute get."""
        ref = str(comment_id or comment_ref)
        entry, comment = self.get_comment(author_fqid, entry_fqid, ref)
        if not self._can_view_comment(request.user, entry, comment):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        likes_qs = Like.objects.filter(
            object_fqid=comment.fqid).order_by("-published")
        return Response(build_likes_object(request, likes_qs, comment.fqid, request.path))

    def post(self, request, author_fqid, entry_fqid, comment_id=None, comment_ref=None):
        """Execute post."""
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        ref = str(comment_id or comment_ref)
        entry, comment = self.get_comment(author_fqid, entry_fqid, ref)
        if not self._can_view_comment(request.user, entry, comment):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        like, created = Like.objects.get_or_create(
            author_fqid=request.user.fqid,
            object_fqid=comment.fqid,
            defaults={"fqid": f"{request.user.host}likes/{uuid.uuid4()}"},
        )
        if created:
            eutils.push_like_to_remote_inboxes(like)
        serializer = LikeSerializer(like)
        return Response(
            serializer.data,
            status=(
                drf_status.HTTP_201_CREATED if created else drf_status.HTTP_200_OK),
        )

    def delete(self, request, author_fqid, entry_fqid, comment_id=None, comment_ref=None):
        """Execute delete."""
        return Response(
            {"detail": "Unliking is disabled."},
            status=drf_status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class EntryCommentsByFQIDAPIView(APIView):
    """GET /api/entries/{ENTRY_FQID}/comments"""
    permission_classes = [AllowAny]

    def get(self, request, fqid):
        """Execute get."""
        entry = get_object_or_404(Entry, fqid=unquote(fqid))
        if entry.visibility == "DELETED" and not (
            request.user.is_authenticated and request.user.is_staff
        ):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        comments_qs = eutils.visible_comments_queryset(request.user, entry)
        if not eutils.can_user_see_entry(request.user, entry) and not comments_qs.exists():
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(build_comments_object(request, comments_qs, entry.fqid, request.path))


class EntryLikesByFQIDAPIView(APIView):
    """GET /api/entries/{ENTRY_FQID}/likes"""
    permission_classes = [AllowAny]

    def get(self, request, fqid):
        """Execute get."""
        entry = get_object_or_404(Entry, fqid=unquote(fqid))
        if not eutils.can_user_see_entry(request.user, entry):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        likes_qs = Like.objects.filter(
            object_fqid=entry.fqid).order_by("-published")
        return Response(build_likes_object(request, likes_qs, entry.fqid, request.path))


class EntryCommentDetailAPIView(APIView):
    """GET /api/authors/{AUTHOR}/entries/{ENTRY}/comments/{REMOTE_COMMENT_FQID_OR_SERIAL}"""
    permission_classes = [AllowAny]

    def get(self, request, author_fqid, entry_fqid, comment_ref):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        entry = get_object_or_404(Entry, pk=entry_fqid, author=author)
        comment = eutils.resolve_comment_for_entry(entry, comment_ref)

        can_view_comment = comment.author_fqid == getattr(request.user, "fqid", None) or bool(
            eutils.visible_comments_queryset(
                request.user, entry).filter(pk=comment.pk).exists()
        )
        if not can_view_comment:
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(CommentSerializer(comment).data)


class AuthorCommentedAPIView(APIView):
    """GET/POST /api/authors/{AUTHOR_SERIAL}/commented"""

    def get(self, request, author_fqid):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        qs = Comment.objects.filter(
            author_fqid=author.fqid).order_by("-published")
        include_private = request.user.is_authenticated and request.user.pk == author.pk
        comments = [c for c in qs if eutils.comment_visible_for_list(
            c, request, include_private)]
        page_num, size = parse_pagination(
            request, default_size=5, max_size=50)
        paginator = Paginator(comments, size)
        page = paginator.get_page(page_num)
        return Response(
            {
                "type": "comments",
                "web": author.web,
                "id": request.path,
                "page_number": page.number,
                "size": size,
                "count": paginator.count,
                "src": CommentSerializer(page.object_list, many=True).data,
            }
        )

    def post(self, request, author_fqid):
        """Execute post."""
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        if request.data.get("type") != "comment":
            return Response(
                {"detail": "Only type='comment' is supported."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        entry_fqid = str(request.data.get("entry", "")).strip()
        comment_text = str(request.data.get("comment", "")).strip()
        content_type = str(request.data.get(
            "contentType", "text/plain")).strip() or "text/plain"

        if not entry_fqid or not comment_text:
            return Response(
                {"detail": "entry and comment are required."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        comment = Comment.objects.create(
            fqid=f"{author.host}authors/{author.id}/commented/{uuid.uuid4()}",
            author_fqid=author.fqid,
            entry_fqid=entry_fqid,
            comment=comment_text,
            content_type=content_type,
        )
        eutils.push_comment_to_remote_inboxes(comment)
        return Response(CommentSerializer(comment).data, status=drf_status.HTTP_201_CREATED)


class AuthorCommentedByFQIDAPIView(APIView):
    """GET /api/authors/{AUTHOR_FQID}/commented (local node only)"""

    def get(self, request, author_encoded_fqid):
        """Execute get."""
        author_fqid = unquote(author_encoded_fqid)
        comments_qs = Comment.objects.filter(
            author_fqid=author_fqid).order_by("-published")
        page_num, size = parse_pagination(
            request, default_size=5, max_size=50)
        paginator = Paginator(list(comments_qs), size)
        page = paginator.get_page(page_num)
        return Response(
            {
                "type": "comments",
                "web": api_to_web_url(author_fqid),
                "id": request.path,
                "page_number": page.number,
                "size": size,
                "count": paginator.count,
                "src": CommentSerializer(page.object_list, many=True).data,
            }
        )


class AuthorCommentDetailAPIView(APIView):
    """GET /api/authors/{AUTHOR_SERIAL}/commented/{COMMENT_SERIAL}"""

    def get(self, request, author_fqid, comment_id):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        comment = get_object_or_404(
            Comment, pk=comment_id, author_fqid=author.fqid)
        include_private = request.user.is_authenticated and request.user.pk == author.pk
        if not eutils.comment_visible_for_list(comment, request, include_private):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)
        return Response(CommentSerializer(comment).data)


class CommentByFQIDAPIView(APIView):
    """GET /api/commented/{COMMENT_FQID}"""

    def get(self, request, comment_fqid):
        """Execute get."""
        decoded = unquote(comment_fqid)
        comment = get_object_or_404(Comment, fqid=decoded)
        return Response(CommentSerializer(comment).data)


class AuthorLikedAPIView(APIView):
    """GET /api/authors/{AUTHOR_SERIAL}/liked"""

    def get(self, request, author_fqid):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        qs = Like.objects.filter(
            author_fqid=author.fqid).order_by("-published")
        include_private = request.user.is_authenticated and request.user.pk == author.pk
        likes = [like_item for like_item in qs if eutils.like_visible_for_list(
            like_item, include_private)]
        page_num, size = parse_pagination(
            request, default_size=50, max_size=100)
        paginator = Paginator(likes, size)
        page = paginator.get_page(page_num)
        return Response(
            {
                "type": "likes",
                "web": author.web,
                "id": request.path,
                "page_number": page.number,
                "size": size,
                "count": paginator.count,
                "src": LikeSerializer(page.object_list, many=True).data,
            }
        )


class AuthorLikedByFQIDAPIView(APIView):
    """GET /api/authors/{AUTHOR_FQID}/liked (local node only)"""

    def get(self, request, author_encoded_fqid):
        """Execute get."""
        author_fqid = unquote(author_encoded_fqid)
        likes_qs = Like.objects.filter(
            author_fqid=author_fqid).order_by("-published")
        page_num, size = parse_pagination(
            request, default_size=50, max_size=100)
        paginator = Paginator(list(likes_qs), size)
        page = paginator.get_page(page_num)
        return Response(
            {
                "type": "likes",
                "web": api_to_web_url(author_fqid),
                "id": request.path,
                "page_number": page.number,
                "size": size,
                "count": paginator.count,
                "src": LikeSerializer(page.object_list, many=True).data,
            }
        )


class AuthorLikeDetailAPIView(APIView):
    """GET /api/authors/{AUTHOR_SERIAL}/liked/{LIKE_SERIAL}"""

    def get(self, request, author_fqid, like_id):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        like = get_object_or_404(Like, pk=like_id, author_fqid=author.fqid)
        include_private = request.user.is_authenticated and request.user.pk == author.pk
        if not eutils.like_visible_for_list(like, include_private):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)
        return Response(LikeSerializer(like).data)


class LikeByFQIDAPIView(APIView):
    """GET /api/liked/{LIKE_FQID}"""

    def get(self, request, like_fqid):
        """Execute get."""
        decoded = unquote(like_fqid)
        like = get_object_or_404(Like, fqid=decoded)
        return Response(LikeSerializer(like).data)
