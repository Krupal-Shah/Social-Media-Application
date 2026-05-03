"""View logic for the authors app."""

from urllib.parse import quote, unquote
import logging
import json
from types import SimpleNamespace
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth import authenticate, login
from .forms import RegisterForm, ProfileEditForm
from django.contrib.auth.decorators import login_required
from .models import Author
from inbox.models import InboxItem
from social.models import Follow
from django.http import Http404
from django.db.models import Q
from django.views.decorators.http import require_POST
from .github_utils import fetch_and_create_github_entries
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from .serializers import AuthorSerializer
from core.pagination import AuthorsPagination
from core.fqid import serial_from_fqid, api_to_web_url
import core.utils as cutils
import authors.utils as autils
from nodes.models import Node
from nodes.models import RemoteAuthor
from nodes.remote import (
    authenticate_remote_api_request,
    find_node_for_author_fqid,
    publish_local_author_to_nodes,
    send_follow_to_inbox,
)
import uuid


logger = logging.getLogger(__name__)


def _require_remote_or_local_api_auth(request):
    """Execute require remote or local api auth."""
    if request.user.is_authenticated:
        return None
    _, error = authenticate_remote_api_request(request, realm="node-authors")
    return error


def login_view(request):
    """Execute login view."""
    if request.user.is_authenticated:
        return redirect("stream")

    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.approved and not user.is_superuser:
                error = "Your account is currently pending admin approval."
            else:
                login(request, user)
                next_url = request.POST.get("next") or request.GET.get("next")
                return redirect(next_url if next_url else "stream")
        else:
            error = "Your username or password is incorrect. Please try again."

    return render(request, "registration/login.html", {"error": error, "next": request.GET.get("next", "")})


def register(request):
    """Execute register."""
    if request.user.is_authenticated:
        return redirect("stream")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            form.save(request=request)
            return render(request, "register_done.html")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


@login_required
def author_list(request):
    """Execute author list."""
    authors = Author.objects.filter(approved=True).exclude(pk=request.user.pk)
    pending_count = Follow.objects.filter(
        following_fqid=request.user.fqid, accepted=False
    ).count()

    active_scopes = set()
    for node in Node.objects.filter(active=True).only("base_url"):
        api_base = cutils.normalize_api_base(node.base_url)
        if not api_base:
            continue
        active_scopes.add(api_base)
        if api_base.endswith("/api"):
            active_scopes.add(api_base[:-4])

    def _is_from_active_node(value):
        """Execute is from active node."""
        return cutils.is_from_active_node(value, active_scopes)

    inbox_items = InboxItem.objects.filter(author=request.user)

    remote_authors = []
    for remote in RemoteAuthor.objects.select_related("node").filter(node__active=True).order_by("display_name", "fqid"):
        if not _is_from_active_node(remote.fqid):
            continue
        remote_authors.append(
            {
                "id": remote.fqid,
                "displayName": remote.display_name or remote.fqid.rstrip("/").split("/")[-1],
                "username": remote.username,
                "profileImage": remote.profile_image,
                "host": remote.host,
            }
        )
    logger.info(
        "Author list build: user=%s local_authors=%s remote_authors=%s inbox_items=%s",
        request.user.username,
        authors.count(),
        len(remote_authors),
        inbox_items.count(),
    )

    def _norm_fqid(value):
        """Execute norm fqid."""
        return str(value or "").strip().rstrip("/")

    my_follows = Follow.objects.filter(follower_fqid=request.user.fqid)
    following_fqids = {
        _norm_fqid(fqid)
        for fqid in my_follows.filter(accepted=True).values_list("following_fqid", flat=True)
        if _norm_fqid(fqid)
    }
    pending_fqids = {
        _norm_fqid(fqid)
        for fqid in my_follows.filter(accepted=False).values_list("following_fqid", flat=True)
        if _norm_fqid(fqid)
    }

    for author in remote_authors:
        fqid = _norm_fqid(author.get("id", ""))
        if fqid in following_fqids:
            author["follow_status"] = "following"
        elif fqid in pending_fqids:
            author["follow_status"] = "pending"
        else:
            author["follow_status"] = "none"

    pending_signups = Author.objects.none()
    if request.user.is_staff:
        pending_signups = Author.objects.filter(approved=False).exclude(
            pk=request.user.pk
        ).order_by("date_joined")

    return render(
        request,
        "author_list.html",
        {
            "authors": authors,
            "remote_authors": remote_authors,
            "active_nav": "authors",
            "pending_count": pending_count,
            "pending_signups": pending_signups,
        },
    )


def _ensure_staff(request):
    """Execute ensure staff."""
    if not request.user.is_staff:
        raise Http404


@login_required
@require_POST
def approve_signup(request, author_id):
    """Execute approve signup."""
    _ensure_staff(request)
    author = get_object_or_404(Author, pk=author_id)
    author.approved = True
    author.is_active = True
    author.save(update_fields=["approved", "is_active"])
    try:
        publish_local_author_to_nodes(author)
    except Exception:
        logger.exception(
            "Failed to publish author to remote nodes: %s", author.fqid)
    return redirect("author_list")


@login_required
@require_POST
def reject_signup(request, author_id):
    """Execute reject signup."""
    _ensure_staff(request)
    author = get_object_or_404(Author, pk=author_id)
    if author.pk != request.user.pk:
        author.delete()
    return redirect("author_list")


@login_required
@require_POST
def toggle_author_staff(request, author_id):
    """Execute toggle author staff."""
    _ensure_staff(request)
    author = get_object_or_404(Author, pk=author_id)
    if author.pk != request.user.pk:
        author.is_staff = not author.is_staff
        author.save(update_fields=["is_staff"])
    return redirect("author_list")


@login_required
@require_POST
def toggle_author_active(request, author_id):
    """Execute toggle author active."""
    _ensure_staff(request)
    author = get_object_or_404(Author, pk=author_id)
    if author.pk != request.user.pk:
        author.is_active = not author.is_active
        author.save(update_fields=["is_active"])
    return redirect("author_list")


@login_required
@require_POST
def delete_author_account(request, author_id):
    """Delete author account."""
    _ensure_staff(request)
    author = get_object_or_404(Author, pk=author_id)
    if author.pk != request.user.pk:
        author.delete()
    return redirect("author_list")


def author_profile(request, author_id):
    """Execute author profile."""
    author = get_object_or_404(Author, pk=author_id)
    fetch_and_create_github_entries(author)
    entries_qs = author.entries.filter(
        visibility="PUBLIC").order_by("-published")
    entries = [autils.annotate_profile_entry(entry) for entry in entries_qs]

    is_following = False
    has_pending = False

    if request.user.is_authenticated:
        is_following = Follow.objects.filter(
            follower_fqid=request.user.fqid,
            following_fqid=author.fqid,
            accepted=True,
        ).exists()
        has_pending = Follow.objects.filter(
            follower_fqid=request.user.fqid,
            following_fqid=author.fqid,
            accepted=False,
        ).exists()

    pending_count = 0
    if request.user.is_authenticated:
        pending_count = Follow.objects.filter(
            following_fqid=request.user.fqid, accepted=False
        ).count()

    return render(
        request,
        "author_profile.html",
        {
            "author": author,
            "entries": entries,
            "is_following": is_following,
            "has_pending": has_pending,
            "pending_count": pending_count,
        },
    )


@login_required
@require_POST
def follow_author(request, author_id):
    """Execute follow author."""
    author = get_object_or_404(Author, pk=author_id)
    if author.pk != request.user.pk:
        Follow.objects.get_or_create(
            follower_fqid=request.user.fqid,
            following_fqid=author.fqid,
            defaults={"accepted": False},
        )
    return redirect("author_profile", author_id=author_id)


@login_required
@require_POST
def follow_remote_author(request):
    """Follow a remote author by sending a follow activity to their inbox."""
    target_fqid = request.POST.get("author_fqid", "").strip()
    if not target_fqid or "/authors/" not in target_fqid.rstrip("/"):
        return redirect("author_list")

    node = find_node_for_author_fqid(target_fqid)
    if node and send_follow_to_inbox(node, request.user, target_fqid):
        follow, _ = Follow.objects.update_or_create(
            follower_fqid=request.user.fqid,
            following_fqid=target_fqid,
            defaults={"accepted": True},
        )

    return redirect("author_list")


@login_required
def remote_author_profile(request):
    """Execute remote author profile."""
    remote_fqid = request.GET.get("fqid", "").strip()
    if not remote_fqid:
        raise Http404

    # Build profile from what we know locally (inbox + follow graph).
    remote_author = {
        "id": remote_fqid,
        "displayName": remote_fqid.rstrip("/").split("/")[-1],
        "profileImage": "",
        "host": remote_fqid.split("/api/")[0] + "/" if "/api/" in remote_fqid else remote_fqid,
    }

    persisted_remote = RemoteAuthor.objects.filter(fqid=remote_fqid).first()
    if persisted_remote:
        remote_author = {
            "id": persisted_remote.fqid,
            "displayName": persisted_remote.display_name or remote_author["displayName"],
            "profileImage": persisted_remote.profile_image,
            "host": persisted_remote.host or remote_author["host"],
        }

    inbox_items = InboxItem.objects.filter(
        author=request.user).order_by("-received")
    for item in inbox_items:
        payload = item.payload or {}
        actor = {}
        if item.type == "follow":
            actor = payload.get("actor", {})
        elif item.type in {"entry", "comment", "like"}:
            actor = payload.get("author", {})
        actor_fqid = str(actor.get("id", "")).strip()
        if actor_fqid != remote_fqid:
            continue
        remote_author = {
            "id": remote_fqid,
            "displayName": actor.get("displayName") or remote_author["displayName"],
            "profileImage": actor.get("profileImage", remote_author["profileImage"]),
            "host": actor.get("host") or remote_author["host"],
        }
        break

    remote_fqid_norm = str(remote_fqid).strip().rstrip("/")
    my_follows = Follow.objects.filter(
        follower_fqid=request.user.fqid,
    ).values("following_fqid", "accepted")

    is_following = any(
        str(row.get("following_fqid", "")).strip().rstrip(
            "/") == remote_fqid_norm
        and bool(row.get("accepted"))
        for row in my_follows
    )
    has_pending = any(
        str(row.get("following_fqid", "")).strip().rstrip(
            "/") == remote_fqid_norm
        and not bool(row.get("accepted"))
        for row in my_follows
    )

    remote_entries = []
    for item in InboxItem.objects.filter(author=request.user, type="entry").order_by("-received"):
        payload = item.payload or {}
        author_data = payload.get("author", {})
        if str(author_data.get("id", "")).strip() != remote_fqid:
            continue

        visibility = str(payload.get("visibility", "PUBLIC")
                         or "PUBLIC").upper()
        if visibility != "PUBLIC":
            continue

        content = payload.get("content", "")
        content_type = str(payload.get(
            "contentType", "text/plain") or "text/plain")
        display_has_image = cutils.is_base64_image_content_type(content_type)
        remote_entries.append(
            SimpleNamespace(
                title=payload.get("title", ""),
                content=content if isinstance(
                    content, str) else json.dumps(content),
                content_type=content_type,
                visibility=visibility,
                published=item.received,
                display_is_markdown="text/markdown" in content_type,
                display_has_image=display_has_image,
                display_image_src=(
                    cutils.data_url_from_entry_content(content_type, content)
                    if isinstance(content, str)
                    else ""
                ),
                display_text=(
                    ""
                    if display_has_image
                    else (content if isinstance(content, str) else json.dumps(content))
                ).lstrip(),
            )
        )

    pending_count = Follow.objects.filter(
        following_fqid=request.user.fqid, accepted=False
    ).count()

    return render(
        request,
        "remote_author_profile.html",
        {
            "author": remote_author,
            "entries": remote_entries,
            "is_following": is_following,
            "has_pending": has_pending,
            "pending_count": pending_count,
            "remote_fqid": remote_fqid,
        },
    )


@login_required
@require_POST
def unfollow_remote_author(request):
    """Execute unfollow remote author."""
    target_fqid = request.POST.get("author_fqid", "").strip()
    if not target_fqid:
        return redirect("author_list")

    node = find_node_for_author_fqid(target_fqid)
    if node:
        send_follow_to_inbox(
            node,
            request.user,
            target_fqid,
            follow_status="UNFOLLOW",
        )

    # Delete follow records matching common FQID variants (api vs web, trailing slash)
    norm = target_fqid.rstrip("/")
    web = api_to_web_url(target_fqid).rstrip("/")
    variants = {norm, web}
    Follow.objects.filter(follower_fqid=request.user.fqid,
                          following_fqid__in=variants).delete()

    return redirect(f"/authors/remote-profile/?fqid={quote(target_fqid)}")


@login_required
@require_POST
def unfollow_author(request, author_id):
    """Execute unfollow author."""
    author = get_object_or_404(Author, pk=author_id)
    from social.models import Follow
    Follow.objects.filter(
        follower_fqid=request.user.fqid,
        following_fqid=author.fqid,
    ).delete()
    return redirect("author_profile", author_id=author_id)


@login_required
@require_POST
def approve_follow(request, author_id):
    """Accept a pending follow request from a local author_id."""
    follower = get_object_or_404(Author, pk=author_id)
    follow = Follow.objects.filter(
        follower_fqid=follower.fqid,
        following_fqid=request.user.fqid,
        accepted=False,
    ).first()
    if follow:
        follow.accepted = True
        follow.save(update_fields=["accepted"])
        if cutils.is_remote_fqid(follower.fqid):
            node = find_node_for_author_fqid(follower.fqid)
            if node:
                send_follow_to_inbox(
                    node,
                    follower.fqid,
                    request.user.fqid,
                    follow_status="ACCEPTED",
                )
    return redirect("follow_requests_page")


@login_required
@require_POST
def deny_follow(request, author_id):
    """Reject (delete) a pending follow request from a local author_id."""
    follower = get_object_or_404(Author, pk=author_id)
    deleted, _ = Follow.objects.filter(
        follower_fqid=follower.fqid,
        following_fqid=request.user.fqid,
        accepted=False,
    ).delete()
    if deleted and cutils.is_remote_fqid(follower.fqid):
        node = find_node_for_author_fqid(follower.fqid)
        if node:
            send_follow_to_inbox(
                node,
                follower.fqid,
                request.user.fqid,
                follow_status="REJECTED",
            )
    return redirect("follow_requests_page")


@login_required
@require_POST
def approve_follow_by_fqid(request):
    """Accept a pending follow request from a remote author (by FQID)."""
    follower_fqid = request.POST.get("follower_fqid", "").strip()
    if not follower_fqid:
        return redirect("follow_requests_page")

    follow = Follow.objects.filter(
        follower_fqid=follower_fqid,
        following_fqid=request.user.fqid,
        accepted=False,
    ).first()
    if follow:
        follow.accepted = True
        follow.save(update_fields=["accepted"])
        node = find_node_for_author_fqid(follower_fqid)
        if node:
            send_follow_to_inbox(
                node,
                follower_fqid,
                request.user.fqid,
                follow_status="ACCEPTED",
            )

    return redirect("follow_requests_page")


@login_required
@require_POST
def deny_follow_by_fqid(request):
    """Reject (delete) a pending follow request from a remote author (by FQID)."""
    follower_fqid = request.POST.get("follower_fqid", "").strip()
    if not follower_fqid:
        return redirect("follow_requests_page")

    Follow.objects.filter(
        follower_fqid=follower_fqid,
        following_fqid=request.user.fqid,
    ).delete()

    node = find_node_for_author_fqid(follower_fqid)
    if node:
        send_follow_to_inbox(
            node,
            follower_fqid,
            request.user.fqid,
            follow_status="REJECTED",
        )

    return redirect("follow_requests_page")


@login_required
def edit_profile(request):
    """
    Display and handle the profile edit form.
    Get : show form pre-filled with current author data.
    Post : validate, save, and redirect back to the profile page.
    """
    if request.method == "POST":
        form = ProfileEditForm(request.POST, instance=request.user)
        if form.is_valid():
            author = form.save()
            try:
                publish_local_author_to_nodes(author)
            except Exception:
                logger.exception(
                    "Failed to publish updated author to remote nodes: %s",
                    author.fqid,
                )
            return redirect("profile")
    else:
        form = ProfileEditForm(instance=request.user)

    return render(request, "profile_edit.html", {"form": form, "active_nav": "profile"})


# =============================================================================
# REST API helpers
# =============================================================================

# No local wrapper; use autils.resolve_author directly


# =============================================================================
# REST API: Author list & detail
# =============================================================================

class AuthorListAPIView(APIView):
    """
    GET /api/authors/

    Returns a paginated list of all approved authors as JSON, or renders the
    ``author_list.html`` template for browser (text/html) requests.

    Query parameters:   ?page=<int>  (1-based, default 1)
                        ?size=<int>  (default 10, max 50)

    JSON response shape::

        {
            "type": "authors",
            "page_number": 1,
            "size": 10,
            "count": 42,
            "authors": [ {...}, ... ]
        }
    """

    permission_classes = []

    def get(self, request):
        """Execute get."""
        auth_error = _require_remote_or_local_api_auth(request)
        if auth_error is not None:
            return auth_error
        qs = Author.objects.filter(approved=True).order_by("display_name")
        paginator = AuthorsPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = AuthorSerializer(
            page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


class AuthorDetailAPIView(APIView):
    """
    GET /api/authors/{AUTHOR_SERIAL}/ – retrieve a single author's profile.
    PUT /api/authors/{AUTHOR_SERIAL}/ – update the author's own profile
                                        (must be authenticated as that author).
    """

    permission_classes = []

    def get(self, request, author_fqid):
        """Execute get."""
        auth_error = _require_remote_or_local_api_auth(request)
        if auth_error is not None:
            return auth_error
        author = get_object_or_404(Author, pk=author_fqid)
        return Response(AuthorSerializer(author, context={"request": request}).data)

    def put(self, request, author_fqid):
        """Execute put."""
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        if request.user.pk != author.pk:
            return Response(
                {"detail": "Forbidden."}, status=drf_status.HTTP_403_FORBIDDEN
            )
        serializer = AuthorSerializer(
            author, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        author = serializer.save()
        try:
            publish_local_author_to_nodes(author)
        except Exception:
            logger.exception(
                "Failed to publish updated author to remote nodes: %s",
                author.fqid,
            )
        return Response(serializer.data)


class AuthorFQIDAPIView(APIView):
    """
    GET /api/authors/{AUTHOR_FQID}/

    Retrieve a profile by its percent-encoded FQID.  Primarily used by remote
    nodes that know an author's full API URL.

    Example:
        GET /api/authors/http%3A%2F%2Fnodeaaaa%2Fapi%2Fauthors%2F111
    """

    permission_classes = []

    def get(self, request, fqid):
        """Execute get."""
        auth_error = _require_remote_or_local_api_auth(request)
        if auth_error is not None:
            return auth_error
        decoded = unquote(fqid)
        author = Author.objects.filter(fqid=decoded).first()
        if not author:
            serial = serial_from_fqid(decoded).strip()
            try:
                author = Author.objects.filter(pk=uuid.UUID(serial)).first()
            except ValueError:
                author = None
        if not author:
            raise Http404("No Author matches the given query.")
        return Response(AuthorSerializer(author, context={"request": request}).data)


# =============================================================================
# REST API: Following
# =============================================================================

class FollowingListAPIView(APIView):
    """
    GET /api/authors/{AUTHOR_SERIAL}/following

    Returns a paginated list of authors that AUTHOR_SERIAL is following
    (accepted follows only).  Must be authenticated as AUTHOR_SERIAL.

    Response shape::

        {
            "type": "following",
            "page_number": 1,
            "size": 10,
            "count": 5,
            "following": [ {...author}, ... ]
        }
    """

    def get(self, request, author_fqid):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        fqids = list(
            Follow.objects.filter(follower_fqid=author.fqid, accepted=True)
            .values_list("following_fqid", flat=True)
        )

        try:
            page_num = max(1, int(request.GET.get("page", 1)))
            size = max(1, int(request.GET.get("size", 10)))
        except ValueError:
            page_num, size = 1, 10

        paginator = Paginator(fqids, size)
        page = paginator.get_page(page_num)
        ctx = {"request": request}
        items = [autils.resolve_author(f, ctx) for f in page.object_list]
        return Response(
            {
                "type": "following",
                "page_number": page.number,
                "size": size,
                "count": paginator.count,
                "following": items,
            }
        )


class FollowingDetailAPIView(APIView):
    """
    /api/authors/{AUTHOR_SERIAL}/following/{FOREIGN_AUTHOR_FQID}

    All operations must be authenticated as AUTHOR_SERIAL.

    GET    – 200 with author object if AUTHOR_SERIAL follows
             FOREIGN_AUTHOR_FQID; 404 otherwise.
    PUT    – AUTHOR_SERIAL creates a follow request for FOREIGN_AUTHOR_FQID.
             Creates a pending Follow (accepted=False) if none exists.
    DELETE – AUTHOR_SERIAL unfollows FOREIGN_AUTHOR_FQID; 404 if not following.
    """

    def _follow(self, author, decoded_fqid):
        """Execute follow."""
        return Follow.objects.filter(
            follower_fqid=author.fqid, following_fqid=decoded_fqid
        ).first()

    def get(self, request, author_fqid, foreign_fqid):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        decoded = unquote(foreign_fqid)
        follow = self._follow(author, decoded)
        if not follow or not follow.accepted:
            raise Http404
        return Response(autils.resolve_author(decoded, {"request": request}))

    def put(self, request, author_fqid, foreign_fqid):
        """Execute put."""
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        decoded = unquote(foreign_fqid)
        defaults = {"accepted": False}
        node = find_node_for_author_fqid(decoded)
        if cutils.is_remote_fqid(decoded) and node:
            if not send_follow_to_inbox(node, author, decoded):
                return Response(
                    {"detail": "Could not deliver follow request to remote node."},
                    status=drf_status.HTTP_502_BAD_GATEWAY,
                )
            defaults["accepted"] = True

        _, created = Follow.objects.update_or_create(
            follower_fqid=author.fqid,
            following_fqid=decoded,
            defaults=defaults,
        )
        if created:
            return Response(
                {"detail": "Follow request created."},
                status=drf_status.HTTP_201_CREATED,
            )
        return Response(
            {"detail": "Follow request already exists."},
            status=drf_status.HTTP_200_OK,
        )

    def delete(self, request, author_fqid, foreign_fqid):
        """Execute delete."""
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        decoded = unquote(foreign_fqid)
        deleted, _ = Follow.objects.filter(
            follower_fqid=author.fqid, following_fqid=decoded
        ).delete()
        if deleted and cutils.is_remote_fqid(decoded):
            node = find_node_for_author_fqid(decoded)
            if node:
                send_follow_to_inbox(
                    node,
                    author,
                    decoded,
                    follow_status="UNFOLLOW",
                )
        if not deleted:
            raise Http404
        return Response(status=drf_status.HTTP_204_NO_CONTENT)


# =============================================================================
# REST API: Followers
# =============================================================================

class FollowerListAPIView(APIView):
    """
    GET /api/authors/{AUTHOR_SERIAL}/followers

    Returns a paginated list of authors who are following AUTHOR_SERIAL
    (accepted follows only).

    Response shape::

        {
            "type": "followers",
            "page_number": 1,
            "size": 10,
            "count": 3,
            "followers": [ {...author}, ... ]
        }
    """

    def get(self, request, author_fqid):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        fqids = list(
            Follow.objects.filter(following_fqid=author.fqid, accepted=True)
            .values_list("follower_fqid", flat=True)
        )

        try:
            page_num = max(1, int(request.GET.get("page", 1)))
            size = max(1, int(request.GET.get("size", 10)))
        except ValueError:
            page_num, size = 1, 10

        paginator = Paginator(fqids, size)
        page = paginator.get_page(page_num)
        ctx = {"request": request}
        items = [autils.resolve_author(f, ctx) for f in page.object_list]
        return Response(
            {
                "type": "followers",
                "page_number": page.number,
                "size": size,
                "count": paginator.count,
                "followers": items,
            }
        )


class FollowerDetailAPIView(APIView):
    """
    /api/authors/{AUTHOR_SERIAL}/followers/{FOREIGN_AUTHOR_FQID}

    GET    – 200 with the follower's author object if FOREIGN_AUTHOR_FQID
             is an accepted follower of AUTHOR_SERIAL; 404 otherwise.
             (local + remote; no auth required — useful for remote checks)
    PUT    – AUTHOR_SERIAL accepts FOREIGN_AUTHOR_FQID's follow request.
             Must be authenticated as AUTHOR_SERIAL.
             Returns 404 if no matching pending follow request exists.
    DELETE – AUTHOR_SERIAL rejects / removes FOREIGN_AUTHOR_FQID.
             Must be authenticated as AUTHOR_SERIAL.
             Returns 404 if no matching follow record exists.
    """

    def _follow(self, author, decoded_fqid):
        """Execute follow."""
        return Follow.objects.filter(
            follower_fqid=decoded_fqid, following_fqid=author.fqid
        ).first()

    def get(self, request, author_fqid, foreign_fqid):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        decoded = unquote(foreign_fqid)
        follow = self._follow(author, decoded)
        if not follow or not follow.accepted:
            raise Http404
        return Response(autils.resolve_author(decoded, {"request": request}))

    def put(self, request, author_fqid, foreign_fqid):
        """Execute put."""
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        decoded = unquote(foreign_fqid)
        follow = self._follow(author, decoded)
        if not follow:
            return Response(
                {"detail": "No follow request found."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )
        follow.accepted = True
        follow.save(update_fields=["accepted"])
        if cutils.is_remote_fqid(decoded):
            node = find_node_for_author_fqid(decoded)
            if node:
                send_follow_to_inbox(
                    node,
                    decoded,
                    author.fqid,
                    follow_status="ACCEPTED",
                )
        return Response(autils.resolve_author(decoded, {"request": request}))

    def delete(self, request, author_fqid, foreign_fqid):
        """Execute delete."""
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        decoded = unquote(foreign_fqid)
        deleted, _ = Follow.objects.filter(
            follower_fqid=decoded, following_fqid=author.fqid
        ).delete()
        if deleted and cutils.is_remote_fqid(decoded):
            node = find_node_for_author_fqid(decoded)
            if node:
                send_follow_to_inbox(
                    node,
                    decoded,
                    author.fqid,
                    follow_status="REJECTED",
                )
        if not deleted:
            raise Http404
        return Response(status=drf_status.HTTP_204_NO_CONTENT)


# =============================================================================
# REST API: Follow requests & Inbox
# =============================================================================

class FollowRequestsAPIView(APIView):
    """
    GET /api/authors/{AUTHOR_SERIAL}/follow_requests

    Returns all *pending* (not yet accepted) follow requests for AUTHOR_SERIAL.
    Must be authenticated as AUTHOR_SERIAL.

    Response shape::

        {
            "type": "follow_requests",
            "follow_requests": [
                {
                    "type": "follow",
                    "summary": "<actor> wants to follow <object>",
                    "actor":  {...author},
                    "object": {...author}    // AUTHOR_SERIAL
                },
                ...
            ]
        }
    """

    def get(self, request, author_fqid):
        """Execute get."""
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )

        pending = Follow.objects.filter(
            following_fqid=author.fqid, accepted=False
        ).order_by("-created")

        ctx = {"request": request}
        object_data = AuthorSerializer(author, context=ctx).data
        requests_list = []
        for f in pending:
            actor_data = autils.resolve_author(f.follower_fqid, ctx)
            requests_list.append(
                {
                    "type": "follow",
                    "summary": (
                        f"{actor_data.get('displayName', f.follower_fqid)}"
                        f" wants to follow {author.display_name}"
                    ),
                    "actor": actor_data,
                    "object": object_data,
                }
            )

        return Response({"type": "follow_requests", "follow_requests": requests_list})
