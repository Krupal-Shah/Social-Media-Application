import base64
import json
import uuid
from django.core.paginator import Paginator
from urllib.parse import unquote

from authors.models import Author
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from rest_framework import status as drf_status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import EntriesPagination
from interactions.models import Comment, Like
from social.models import Follow

from .models import Entry
from .serializers import CommentSerializer, EntrySerializer, LikeSerializer
from core.fqid import api_to_web_url


def _annotate_entry(entry):
    """Attach display-ready fields to an Entry instance for templates."""
    ct = entry.content_type or ""
    has_gallery = "image/gallery" in ct
    has_image = "image/" in ct
    has_text = "text/" in ct

    entry.display_has_gallery = has_gallery
    entry.display_has_image = has_image and not has_gallery
    entry.display_is_markdown = "text/markdown" in ct
    entry.display_image_src = ""
    entry.display_gallery_json = "[]"
    entry.display_text = ""

    if has_image and has_text:
        try:
            data = json.loads(entry.content)
        except (json.JSONDecodeError, ValueError):
            data = {}
        entry.display_text = data.get("text", "")
        if has_gallery:
            entry.display_gallery_json = json.dumps(data.get("gallery", []))
        else:
            img_type = ct.split("/text/")[0]
            entry.display_image_src = f"data:{img_type};base64,{data.get('image', '')}"
    elif has_gallery:
        entry.display_gallery_json = entry.content
    elif has_image:
        entry.display_image_src = f"data:{ct};base64,{entry.content}"
    else:
        entry.display_text = entry.content

    return entry


def _attach_entry_interaction_state(entry, user):
    """Attach like/comment state used by HTML templates."""
    entry.likes_count = Like.objects.filter(object_fqid=entry.fqid).count()
    entry.comments_count = Comment.objects.filter(
        entry_fqid=entry.fqid).count()
    entry.liked_by_me = bool(
        user.is_authenticated
        and Like.objects.filter(author_fqid=user.fqid, object_fqid=entry.fqid).exists()
    )
    return entry


@login_required
def stream(request):
    # unlisted = public but not showin in public stream unless followers
    # we need to filter the entries by public, unlisted, and friends only (of people i follow)
    # show the most recent entries, and not show entries that deleted
    me = request.user

    following = set(
        Follow.objects.filter(follower_fqid=me.fqid, accepted=True)
        .values_list("following_fqid", flat=True)
    )

    # Friends are mutual followers
    followers = set(
        Follow.objects.filter(following_fqid=me.fqid, accepted=True)
        .values_list("follower_fqid", flat=True))
    friends = following & followers  # check this
    # My own non-deleted posts
    # my_entries = Entry.objects.filter(author=me).exclude(visibility="DELETED")
    public_entries = Entry.objects.filter(
        visibility="PUBLIC").exclude(author=me)
    unlisted_entries = Entry.objects.filter(
        visibility="UNLISTED", author__fqid__in=following).exclude(author=me)
    friends_entries = Entry.objects.filter(
        visibility="FRIENDS", author__fqid__in=friends).exclude(author=me)
    # Combine them all together, remove duplicates, sort newest first
    entries = (public_entries | unlisted_entries |
               friends_entries).distinct().order_by("-updated_at")

    # Pending follow request count for navbar badge
    pending_count = Follow.objects.filter(
        following_fqid=me.fqid, accepted=False
    ).count()

    display_entries = [
        _attach_entry_interaction_state(_annotate_entry(e), request.user)
        for e in entries
    ]
    return render(
        request,
        "stream.html",
        {"entries": display_entries, "active_nav": "home",
            "pending_count": pending_count},
    )


@login_required
def explore(request):
    """Browse all PUBLIC entries from everyone."""
    me = request.user

    entries = (
        Entry.objects.filter(visibility="PUBLIC")
        .distinct()
        .order_by("-updated_at")
    )

    pending_count = Follow.objects.filter(
        following_fqid=me.fqid, accepted=False
    ).count()

    display_entries = [
        _attach_entry_interaction_state(_annotate_entry(e), me)
        for e in entries
    ]

    # Attach a small comment preview to each entry (most recent first)
    entry_fqids = [e.fqid for e in display_entries]
    comments_by_entry: dict[str, list[Comment]] = {fqid: [] for fqid in entry_fqids}
    if entry_fqids:
        preview_limit = 2
        preview_comments = Comment.objects.filter(
            entry_fqid__in=entry_fqids
        ).order_by("-published")

        # Collect up to N comments per entry
        for c in preview_comments:
            bucket = comments_by_entry.get(c.entry_fqid)
            if bucket is None or len(bucket) >= preview_limit:
                continue
            bucket.append(c)

        # Resolve comment authors (best-effort; remote authors may not be cached)
        author_fqids = {
            c.author_fqid
            for bucket in comments_by_entry.values()
            for c in bucket
        }
        author_map = {
            a.fqid: a
            for a in Author.objects.filter(fqid__in=author_fqids)
        }
        for bucket in comments_by_entry.values():
            for c in bucket:
                c.author = author_map.get(c.author_fqid)

    for e in display_entries:
        e.recent_comments = comments_by_entry.get(e.fqid, [])

    return render(
        request,
        "explore.html",
        {
            "entries": display_entries,
            "active_nav": "explore",
            "pending_count": pending_count,
        },
    )


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
            pending_authors.append(author)
        except Author.DoesNotExist:
            pending_authors.append(
                {"fqid": f.follower_fqid, "display_name": f.follower_fqid, "id": None})

    pending_count = len(pending_authors)
    return render(request, "follow_requests.html", {
        "pending_requests": pending_authors,
        "pending_count": pending_count,
    })


@login_required
@require_POST
def create_entry(request):
    title = request.POST.get("title", "").strip()
    text_content = request.POST.get("content", "").strip()
    visibility = request.POST.get("visibility", "PUBLIC")
    use_markdown = bool(request.POST.get("use_markdown"))
    image_files = request.FILES.getlist("image")[:5]

    if not text_content and not image_files:
        messages.error(request, "Post content cannot be empty.")
        return redirect("stream")

    text_suffix = "text/markdown" if use_markdown else "text/plain"

    # The following if logic is written by Github Copilot, "How do I implement multiple image upload in Django?", 2026-02-28
    if image_files:
        if len(image_files) == 1:
            img_type = image_files[0].content_type
            img_data = base64.b64encode(image_files[0].read()).decode("utf-8")
            if text_content:
                # Combined: single image + text → store as JSON
                content_type = f"{img_type}/{text_suffix}"
                content = json.dumps({"image": img_data, "text": text_content})
            else:
                content_type = img_type
                content = img_data
        else:
            gallery = [
                {"type": f.content_type, "data": base64.b64encode(
                    f.read()).decode("utf-8")}
                for f in image_files
            ]
            if text_content:
                # Combined: gallery + text → store as JSON
                content_type = f"image/gallery/{text_suffix}"
                content = json.dumps(
                    {"gallery": gallery, "text": text_content})
            else:
                content_type = "image/gallery"
                content = json.dumps(gallery)
    else:
        content_type = text_suffix
        content = text_content

    Entry.objects.create(
        author=request.user,
        title=title,
        content=content,
        content_type=content_type,
        visibility=visibility,
    )

    return redirect("stream")


@login_required
def profile(request):
    entries = request.user.entries.exclude(
        visibility="DELETED").order_by("-published")
    followers_count = Follow.objects.filter(
        following_fqid=request.user.fqid, accepted=True
    ).count()
    following_count = Follow.objects.filter(
        follower_fqid=request.user.fqid, accepted=True
    ).count()

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
            # Remote author not cached locally — show stub
            pending_authors.append(
                {"fqid": f.follower_fqid, "display_name": f.follower_fqid, "id": None})

    display_entries = [
        _attach_entry_interaction_state(_annotate_entry(e), request.user)
        for e in entries
    ]

    return render(request, "profile.html", {
        "entries": display_entries,
        "followers_count": followers_count,
        "following_count": following_count,
        "pending_requests": pending_authors,
        "pending_count": len(pending_authors),
        "active_nav": "profile",
    })


@login_required
@require_POST
def edit_entry(request, entry_id):
    entry = get_object_or_404(Entry, pk=entry_id, author=request.user)

    title = request.POST.get("title", "").strip()
    text_content = request.POST.get("content", "").strip()
    description = request.POST.get("description", "").strip()
    visibility = request.POST.get("visibility", entry.visibility)
    use_markdown = bool(request.POST.get("use_markdown"))
    image_files = request.FILES.getlist("image")[:5]

    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )

    ct = entry.content_type or ""
    has_gallery = "image/gallery" in ct
    has_image = "image/" in ct
    is_combined = has_image and "text/" in ct

    if not text_content and not image_files and not has_image:
        if wants_json:
            return JsonResponse({"error": "Post content cannot be empty."}, status=400)
        messages.error(request, "Post content cannot be empty.")
        return redirect("/profile/")

    text_suffix = "text/markdown" if use_markdown else "text/plain"

    if image_files:
        # New image(s) uploaded: rebuild just like create_entry
        if len(image_files) == 1:
            img_type = image_files[0].content_type
            img_data = base64.b64encode(image_files[0].read()).decode("utf-8")
            if text_content:
                entry.content_type = f"{img_type}/{text_suffix}"
                entry.content = json.dumps(
                    {"image": img_data, "text": text_content})
            else:
                entry.content_type = img_type
                entry.content = img_data
        else:
            gallery = [
                {"type": f.content_type, "data": base64.b64encode(
                    f.read()).decode("utf-8")}
                for f in image_files
            ]
            if text_content:
                entry.content_type = f"image/gallery/{text_suffix}"
                entry.content = json.dumps(
                    {"gallery": gallery, "text": text_content})
            else:
                entry.content_type = "image/gallery"
                entry.content = json.dumps(gallery)
    elif has_gallery:
        # Keep existing gallery, update text
        existing = json.loads(entry.content)
        existing_gallery = existing.get(
            "gallery", existing) if is_combined else existing
        if text_content:
            entry.content_type = f"image/gallery/{text_suffix}"
            entry.content = json.dumps(
                {"gallery": existing_gallery, "text": text_content})
        else:
            entry.content_type = "image/gallery"
            entry.content = json.dumps(existing_gallery)
    elif has_image:
        # Keep existing single image, update text
        existing = json.loads(entry.content) if is_combined else {}
        existing_img = existing.get(
            "image", entry.content) if is_combined else entry.content
        img_type = ct.split("/text/")[0] if is_combined else ct
        if text_content:
            entry.content_type = f"{img_type}/{text_suffix}"
            entry.content = json.dumps(
                {"image": existing_img, "text": text_content})
        else:
            entry.content_type = img_type
            entry.content = existing_img
    else:
        # Pure text
        entry.content_type = text_suffix
        entry.content = text_content

    entry.title = title
    entry.description = description
    entry.visibility = visibility
    entry.save()

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
    # should be this?
    entry = get_object_or_404(Entry, pk=entry_id, author=request.user)
    entry.visibility = "DELETED"
    entry.save()
    # entry = get_object_or_404(Entry, pk=entry_id, author=request.user)
    # entry.delete()
    return redirect("/profile/")


def entry_detail(request, entry_id):
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
    entry = _attach_entry_interaction_state(
        _annotate_entry(entry), request.user)
    comments = list(_visible_comments_queryset(request.user, entry))
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


# =============================================================================
# REST API views
# =============================================================================


def _is_friend(me, author):
    """True when *me* and *author* mutually follow each other (accepted)."""
    following = Follow.objects.filter(
        follower_fqid=me.fqid, following_fqid=author.fqid, accepted=True
    ).exists()
    followed_by = Follow.objects.filter(
        follower_fqid=author.fqid, following_fqid=me.fqid, accepted=True
    ).exists()
    return following and followed_by


def _is_follower(me, author):
    """True when *me* follows *author* (accepted)."""
    return Follow.objects.filter(
        follower_fqid=me.fqid, following_fqid=author.fqid, accepted=True
    ).exists()


def _can_see_entry(request, entry):
    """Return True if the requesting user is allowed to view *entry*."""
    return _can_user_see_entry(request.user, entry)


def _can_user_see_entry(user, entry):
    """Return True if *user* can view *entry*."""
    if entry.visibility == "DELETED":
        return False
    if entry.visibility in ("PUBLIC", "UNLISTED"):
        return True
    if entry.visibility == "FRIENDS":
        if not user.is_authenticated:
            return False
        if entry.author == user:
            return True
        return _is_friend(user, entry.author)
    return False


def _visible_comments_queryset(user, entry):
    """Return comments on an entry filtered by friend/comment-author visibility."""
    qs = Comment.objects.filter(entry_fqid=entry.fqid).order_by("-published")
    if entry.visibility != "FRIENDS":
        return qs

    if not user.is_authenticated:
        return qs.none()
    if user == entry.author or _is_friend(user, entry.author):
        return qs
    return qs.filter(author_fqid=user.fqid)


def _like_response_redirect(request, fallback_url):
    next_url = request.POST.get("next", "").strip()
    if next_url:
        return redirect(next_url)
    return redirect(fallback_url)


@login_required
@require_POST
def create_comment(request, entry_id):
    entry = get_object_or_404(Entry, pk=entry_id)
    if not _can_user_see_entry(request.user, entry):
        raise Http404

    text = request.POST.get("comment", "").strip()
    if not text:
        messages.error(request, "Comment cannot be empty.")
        return _like_response_redirect(request, f"/api/entries/{entry.id}/")

    Comment.objects.create(
        fqid=f"{request.user.host}comments/{uuid.uuid4()}",
        author_fqid=request.user.fqid,
        entry_fqid=entry.fqid,
        comment=text,
        content_type="text/plain",
    )
    return _like_response_redirect(request, f"/api/entries/{entry.id}/")


@login_required
@require_POST
def like_entry(request, entry_id):
    entry = get_object_or_404(Entry, pk=entry_id)
    if not _can_user_see_entry(request.user, entry):
        raise Http404

    Like.objects.get_or_create(
        author_fqid=request.user.fqid,
        object_fqid=entry.fqid,
        defaults={"fqid": f"{request.user.host}likes/{uuid.uuid4()}"},
    )
    return _like_response_redirect(request, f"/api/entries/{entry.id}/")


@login_required
@require_POST
def unlike_entry(request, entry_id):
    entry = get_object_or_404(Entry, pk=entry_id)
    Like.objects.filter(
        author_fqid=request.user.fqid,
        object_fqid=entry.fqid,
    ).delete()
    return _like_response_redirect(request, f"/api/entries/{entry.id}/")


@login_required
@require_POST
def like_comment(request, comment_id):
    comment = get_object_or_404(Comment, pk=comment_id)
    entry = get_object_or_404(Entry, fqid=comment.entry_fqid)

    can_view_comment = comment.author_fqid == request.user.fqid or bool(
        _visible_comments_queryset(
            request.user, entry).filter(pk=comment.pk).exists()
    )
    if not can_view_comment:
        raise Http404

    Like.objects.get_or_create(
        author_fqid=request.user.fqid,
        object_fqid=comment.fqid,
        defaults={"fqid": f"{request.user.host}likes/{uuid.uuid4()}"},
    )
    return _like_response_redirect(request, f"/api/entries/{entry.id}/")


@login_required
@require_POST
def unlike_comment(request, comment_id):
    comment = get_object_or_404(Comment, pk=comment_id)
    entry = get_object_or_404(Entry, fqid=comment.entry_fqid)

    can_view_comment = comment.author_fqid == request.user.fqid or bool(
        _visible_comments_queryset(
            request.user, entry).filter(pk=comment.pk).exists()
    )
    if not can_view_comment:
        raise Http404

    Like.objects.filter(
        author_fqid=request.user.fqid,
        object_fqid=comment.fqid,
    ).delete()
    return _like_response_redirect(request, f"/api/entries/{entry.id}/")


@login_required
@require_POST
def delete_comment(request, comment_id):
    comment = get_object_or_404(Comment, pk=comment_id)
    entry = get_object_or_404(Entry, fqid=comment.entry_fqid)

    can_delete = (
        comment.author_fqid == request.user.fqid
        or entry.author == request.user
    )
    if not can_delete:
        raise Http404

    Like.objects.filter(object_fqid=comment.fqid).delete()
    comment.delete()
    return _like_response_redirect(request, f"/api/entries/{entry.id}/")


class EntryDetailAPIView(APIView):
    def get_entry(self, author_fqid, entry_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        return get_object_or_404(Entry, pk=entry_fqid, author=author)

    def get(self, request, author_fqid, entry_fqid):
        entry = self.get_entry(author_fqid, entry_fqid)
        if not _can_see_entry(request, entry):
            return Response(
                {"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND
            )
        serializer = EntrySerializer(entry, context={"request": request})
        return Response(serializer.data)

    def delete(self, request, author_fqid, entry_fqid):
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
        return Response(status=drf_status.HTTP_204_NO_CONTENT)

    def put(self, request, author_fqid, entry_fqid):
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
        serializer.save()
        return Response(serializer.data)


class EntryFQIDAPIView(APIView):
    def get(self, request, fqid):
        decoded_fqid = unquote(fqid)
        entry = get_object_or_404(Entry, fqid=decoded_fqid)
        if not _can_see_entry(request, entry):
            return Response(
                {"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND
            )
        serializer = EntrySerializer(entry, context={"request": request})
        return Response(serializer.data)


def _decode_image_entry(entry):
    ct = entry.content_type or ""
    if "image/" not in ct or "text/" in ct or "image/gallery" in ct:
        return None
    try:
        image_data = base64.b64decode(entry.content)
    except Exception:
        return None
    return HttpResponse(image_data, content_type=ct)


class EntryImageBySerialAPIView(APIView):
    def get(self, request, author_fqid, entry_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        entry = get_object_or_404(Entry, pk=entry_fqid, author=author)
        if not _can_see_entry(request, entry):
            raise Http404
        response = _decode_image_entry(entry)
        if response is None:
            raise Http404
        return response


class EntryImageByFQIDAPIView(APIView):
    def get(self, request, fqid):
        decoded_fqid = unquote(fqid)
        entry = get_object_or_404(Entry, fqid=decoded_fqid)
        if not _can_see_entry(request, entry):
            raise Http404
        response = _decode_image_entry(entry)
        if response is None:
            raise Http404
        return response


class EntryListCreateAPIView(APIView):
    def get(self, request, author_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        qs = (
            Entry.objects.filter(author=author)
            .exclude(visibility="DELETED")
            .order_by("-published")
        )

        user = request.user
        if user.is_authenticated:
            if user == author or _is_friend(user, author):
                # Author / friend: see everything
                pass
            elif _is_follower(user, author):
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
        serializer = EntrySerializer(entry, context={"request": request})
        return Response(serializer.data, status=drf_status.HTTP_201_CREATED)


class EntryCommentsAPIView(APIView):
    def get_entry(self, author_fqid, entry_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        return get_object_or_404(Entry, pk=entry_fqid, author=author)

    def get(self, request, author_fqid, entry_fqid):
        entry = self.get_entry(author_fqid, entry_fqid)
        if entry.visibility == "DELETED":
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        comments_qs = _visible_comments_queryset(request.user, entry)
        if not _can_user_see_entry(request.user, entry) and not comments_qs.exists():
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(_build_comments_object(request, comments_qs, entry.fqid, request.path))

    def post(self, request, author_fqid, entry_fqid):
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        entry = self.get_entry(author_fqid, entry_fqid)
        if not _can_user_see_entry(request.user, entry):
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
        serializer = CommentSerializer(comment)
        return Response(serializer.data, status=drf_status.HTTP_201_CREATED)


class EntryLikesAPIView(APIView):
    def get_entry(self, author_fqid, entry_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        return get_object_or_404(Entry, pk=entry_fqid, author=author)

    def get(self, request, author_fqid, entry_fqid):
        entry = self.get_entry(author_fqid, entry_fqid)
        if not _can_user_see_entry(request.user, entry):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        likes_qs = Like.objects.filter(
            object_fqid=entry.fqid).order_by("-published")
        return Response(_build_likes_object(request, likes_qs, entry.fqid, request.path))

    def post(self, request, author_fqid, entry_fqid):
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        entry = self.get_entry(author_fqid, entry_fqid)
        if not _can_user_see_entry(request.user, entry):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        like, created = Like.objects.get_or_create(
            author_fqid=request.user.fqid,
            object_fqid=entry.fqid,
            defaults={"fqid": f"{request.user.host}likes/{uuid.uuid4()}"},
        )
        serializer = LikeSerializer(like)
        return Response(
            serializer.data,
            status=(
                drf_status.HTTP_201_CREATED if created else drf_status.HTTP_200_OK),
        )

    def delete(self, request, author_fqid, entry_fqid):
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        entry = self.get_entry(author_fqid, entry_fqid)
        if not _can_user_see_entry(request.user, entry):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        Like.objects.filter(
            author_fqid=request.user.fqid,
            object_fqid=entry.fqid,
        ).delete()
        return Response(status=drf_status.HTTP_204_NO_CONTENT)


class CommentLikesAPIView(APIView):
    def get_comment(self, author_fqid, entry_fqid, comment_ref):
        author = get_object_or_404(Author, pk=author_fqid)
        entry = get_object_or_404(Entry, pk=entry_fqid, author=author)
        comment = _resolve_comment_for_entry(entry, comment_ref)
        return entry, comment

    def _can_view_comment(self, user, entry, comment):
        if entry.visibility != "FRIENDS":
            return _can_user_see_entry(user, entry)
        if not user.is_authenticated:
            return False
        if user == entry.author or _is_friend(user, entry.author):
            return True
        return comment.author_fqid == user.fqid

    def get(self, request, author_fqid, entry_fqid, comment_id=None, comment_ref=None):
        ref = str(comment_id or comment_ref)
        entry, comment = self.get_comment(author_fqid, entry_fqid, ref)
        if not self._can_view_comment(request.user, entry, comment):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        likes_qs = Like.objects.filter(
            object_fqid=comment.fqid).order_by("-published")
        return Response(_build_likes_object(request, likes_qs, comment.fqid, request.path))

    def post(self, request, author_fqid, entry_fqid, comment_id=None, comment_ref=None):
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
        serializer = LikeSerializer(like)
        return Response(
            serializer.data,
            status=(
                drf_status.HTTP_201_CREATED if created else drf_status.HTTP_200_OK),
        )

    def delete(self, request, author_fqid, entry_fqid, comment_id=None, comment_ref=None):
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        ref = str(comment_id or comment_ref)
        entry, comment = self.get_comment(author_fqid, entry_fqid, ref)
        if not self._can_view_comment(request.user, entry, comment):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        Like.objects.filter(
            author_fqid=request.user.fqid,
            object_fqid=comment.fqid,
        ).delete()
        return Response(status=drf_status.HTTP_204_NO_CONTENT)


def _parse_pagination(request, default_size, max_size):
    try:
        page_num = max(1, int(request.GET.get("page", 1)))
    except (TypeError, ValueError):
        page_num = 1

    try:
        requested_size = int(request.GET.get("size", default_size))
    except (TypeError, ValueError):
        requested_size = default_size

    size = min(max(1, requested_size), max_size)
    return page_num, size


def _build_comments_object(request, comments_qs, entry_fqid, comments_api_id):
    page_num, size = _parse_pagination(request, default_size=5, max_size=50)
    paginator = Paginator(comments_qs, size)
    page = paginator.get_page(page_num)
    serialized = CommentSerializer(page.object_list, many=True).data
    return {
        "type": "comments",
        "web": api_to_web_url(entry_fqid),
        "id": comments_api_id,
        "page_number": page.number,
        "size": size,
        "count": paginator.count,
        "src": serialized,
    }


def _build_likes_object(request, likes_qs, object_fqid, likes_api_id):
    page_num, size = _parse_pagination(request, default_size=50, max_size=100)
    paginator = Paginator(likes_qs, size)
    page = paginator.get_page(page_num)
    serialized = LikeSerializer(page.object_list, many=True).data
    return {
        "type": "likes",
        "web": api_to_web_url(object_fqid),
        "id": likes_api_id,
        "page_number": page.number,
        "size": size,
        "count": paginator.count,
        "src": serialized,
    }


def _resolve_comment_for_entry(entry, comment_ref):
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


class EntryCommentsByFQIDAPIView(APIView):
    """GET /api/entries/{ENTRY_FQID}/comments"""

    def get(self, request, fqid):
        entry = get_object_or_404(Entry, fqid=unquote(fqid))
        if entry.visibility == "DELETED":
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        comments_qs = _visible_comments_queryset(request.user, entry)
        if not _can_user_see_entry(request.user, entry) and not comments_qs.exists():
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(_build_comments_object(request, comments_qs, entry.fqid, request.path))


class EntryLikesByFQIDAPIView(APIView):
    """GET /api/entries/{ENTRY_FQID}/likes"""

    def get(self, request, fqid):
        entry = get_object_or_404(Entry, fqid=unquote(fqid))
        if not _can_user_see_entry(request.user, entry):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        likes_qs = Like.objects.filter(
            object_fqid=entry.fqid).order_by("-published")
        return Response(_build_likes_object(request, likes_qs, entry.fqid, request.path))


class EntryCommentDetailAPIView(APIView):
    """GET /api/authors/{AUTHOR}/entries/{ENTRY}/comments/{REMOTE_COMMENT_FQID_OR_SERIAL}"""

    def get(self, request, author_fqid, entry_fqid, comment_ref):
        author = get_object_or_404(Author, pk=author_fqid)
        entry = get_object_or_404(Entry, pk=entry_fqid, author=author)
        comment = _resolve_comment_for_entry(entry, comment_ref)

        can_view_comment = comment.author_fqid == getattr(request.user, "fqid", None) or bool(
            _visible_comments_queryset(
                request.user, entry).filter(pk=comment.pk).exists()
        )
        if not can_view_comment:
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        return Response(CommentSerializer(comment).data)


def _entry_visibility_allows_remote(entry):
    return entry.visibility in ("PUBLIC", "UNLISTED")


def _comment_visible_for_list(comment, request, include_private):
    if include_private:
        return True
    entry = Entry.objects.filter(fqid=comment.entry_fqid).first()
    if not entry:
        return False
    return _entry_visibility_allows_remote(entry)


def _like_visible_for_list(like, include_private):
    if include_private:
        return True

    entry = Entry.objects.filter(fqid=like.object_fqid).first()
    if entry:
        return _entry_visibility_allows_remote(entry)

    comment = Comment.objects.filter(fqid=like.object_fqid).first()
    if not comment:
        return False
    parent = Entry.objects.filter(fqid=comment.entry_fqid).first()
    return bool(parent and _entry_visibility_allows_remote(parent))


class AuthorCommentedAPIView(APIView):
    """GET/POST /api/authors/{AUTHOR_SERIAL}/commented"""

    def get(self, request, author_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        qs = Comment.objects.filter(
            author_fqid=author.fqid).order_by("-published")
        include_private = request.user.is_authenticated and request.user.pk == author.pk
        comments = [c for c in qs if _comment_visible_for_list(
            c, request, include_private)]
        page_num, size = _parse_pagination(
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
        return Response(CommentSerializer(comment).data, status=drf_status.HTTP_201_CREATED)


class AuthorCommentedByFQIDAPIView(APIView):
    """GET /api/authors/{AUTHOR_FQID}/commented (local node only)"""

    def get(self, request, author_encoded_fqid):
        author_fqid = unquote(author_encoded_fqid)
        comments_qs = Comment.objects.filter(
            author_fqid=author_fqid).order_by("-published")
        page_num, size = _parse_pagination(
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
        author = get_object_or_404(Author, pk=author_fqid)
        comment = get_object_or_404(
            Comment, pk=comment_id, author_fqid=author.fqid)
        include_private = request.user.is_authenticated and request.user.pk == author.pk
        if not _comment_visible_for_list(comment, request, include_private):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)
        return Response(CommentSerializer(comment).data)


class CommentByFQIDAPIView(APIView):
    """GET /api/commented/{COMMENT_FQID}"""

    def get(self, request, comment_fqid):
        decoded = unquote(comment_fqid)
        comment = get_object_or_404(Comment, fqid=decoded)
        return Response(CommentSerializer(comment).data)


class AuthorLikedAPIView(APIView):
    """GET /api/authors/{AUTHOR_SERIAL}/liked"""

    def get(self, request, author_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        qs = Like.objects.filter(
            author_fqid=author.fqid).order_by("-published")
        include_private = request.user.is_authenticated and request.user.pk == author.pk
        likes = [like_item for like_item in qs if _like_visible_for_list(
            like_item, include_private)]
        page_num, size = _parse_pagination(
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
        author_fqid = unquote(author_encoded_fqid)
        likes_qs = Like.objects.filter(
            author_fqid=author_fqid).order_by("-published")
        page_num, size = _parse_pagination(
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
        author = get_object_or_404(Author, pk=author_fqid)
        like = get_object_or_404(Like, pk=like_id, author_fqid=author.fqid)
        include_private = request.user.is_authenticated and request.user.pk == author.pk
        if not _like_visible_for_list(like, include_private):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)
        return Response(LikeSerializer(like).data)


class LikeByFQIDAPIView(APIView):
    """GET /api/liked/{LIKE_FQID}"""

    def get(self, request, like_fqid):
        decoded = unquote(like_fqid)
        like = get_object_or_404(Like, fqid=decoded)
        return Response(LikeSerializer(like).data)
