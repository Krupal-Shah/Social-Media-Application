from urllib.parse import unquote
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth import authenticate, login
from .forms import RegisterForm, ProfileEditForm
from django.contrib.auth.decorators import login_required
from .models import Author
from social.models import Follow
from django.http import Http404
from django.views.decorators.http import require_POST
from .github_utils import fetch_and_create_github_entries
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from .serializers import AuthorSerializer
from core.pagination import AuthorsPagination
from interactions.models import Comment, Like
import uuid

def login_view(request):
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
    if request.user.is_authenticated:
        return redirect("stream")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            form.save()
            return render(request, "register_done.html")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


@login_required
def author_list(request):
    authors = Author.objects.filter(approved=True).exclude(pk=request.user.pk)
    pending_count = Follow.objects.filter(
        following_fqid=request.user.fqid, accepted=False
    ).count()
    return render(
        request,
        "author_list.html",
        {"authors": authors, "active_nav": "authors",
            "pending_count": pending_count},
    )


def author_profile(request, author_id):
    author = get_object_or_404(Author, pk=author_id)
    fetch_and_create_github_entries(author)
    entries = author.entries.filter(visibility="PUBLIC").order_by("-published")

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

    return render(request, "author_profile.html", {
        "author": author,
        "entries": entries,
        "is_following": is_following,
        "has_pending": has_pending,
        "active_nav": "authors",
        "pending_count": pending_count,
    })

#  ChatGPT5.1, OpenAI, "Help me generate some fuctions to follow/unfollow authors",https://chatgpt.com/, 2026-02-28


@login_required
@require_POST
def follow_author(request, author_id):
    author = get_object_or_404(Author, pk=author_id)
    Follow.objects.get_or_create(
        follower_fqid=request.user.fqid,
        following_fqid=author.fqid,
        defaults={"accepted": False}
    )
    return redirect("author_profile", author_id=author_id)


@login_required
@require_POST
def unfollow_author(request, author_id):
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
    """Accept a pending follow request from author_id."""
    follower = get_object_or_404(Author, pk=author_id)
    follow = Follow.objects.filter(
        follower_fqid=follower.fqid,
        following_fqid=request.user.fqid,
        accepted=False,
    ).first()
    if follow:
        follow.accepted = True
        follow.save()
    return redirect("profile")


@login_required
@require_POST
def deny_follow(request, author_id):
    """Reject (delete) a pending follow request from author_id."""
    follower = get_object_or_404(Author, pk=author_id)
    Follow.objects.filter(
        follower_fqid=follower.fqid,
        following_fqid=request.user.fqid,
        accepted=False,
    ).delete()
    return redirect("profile")


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
            form.save()
            return redirect("profile")
    else:
        form = ProfileEditForm(instance=request.user)

    return render(request, "profile_edit.html", {"form": form, "active_nav": "profile"})


# =============================================================================
# REST API helpers
# =============================================================================

def _resolve_author(fqid, context):
    """Return a serialized author dict for `fqid`.

    Falls back to a minimal stub ``{"type": "author", "id": fqid}`` if the
    author is not found in the local database (e.g. a remote author whose
    profile hasn't been cached yet).
    """
    try:
        author = Author.objects.get(fqid=fqid)
        return AuthorSerializer(author, context=context).data
    except Author.DoesNotExist:
        return {"type": "author", "id": fqid}


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

    def get(self, request):
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

    def get(self, request, author_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        return Response(AuthorSerializer(author, context={"request": request}).data)

    def put(self, request, author_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Forbidden."}, status=drf_status.HTTP_403_FORBIDDEN
            )
        serializer = AuthorSerializer(
            author, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class AuthorFQIDAPIView(APIView):
    """
    GET /api/authors/{AUTHOR_FQID}/

    Retrieve a profile by its percent-encoded FQID.  Primarily used by remote
    nodes that know an author's full API URL.

    Example:
        GET /api/authors/http%3A%2F%2Fnodeaaaa%2Fapi%2Fauthors%2F111
    """

    def get(self, request, fqid):
        decoded = unquote(fqid)
        author = get_object_or_404(Author, fqid=decoded)
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
        items = [_resolve_author(f, ctx) for f in page.object_list]
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
        return Follow.objects.filter(
            follower_fqid=author.fqid, following_fqid=decoded_fqid
        ).first()

    def get(self, request, author_fqid, foreign_fqid):
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
        return Response(_resolve_author(decoded, {"request": request}))

    def put(self, request, author_fqid, foreign_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        if not request.user.is_authenticated or request.user.pk != author.pk:
            return Response(
                {"detail": "Authentication required."},
                status=drf_status.HTTP_401_UNAUTHORIZED,
            )
        decoded = unquote(foreign_fqid)
        _, created = Follow.objects.get_or_create(
            follower_fqid=author.fqid,
            following_fqid=decoded,
            defaults={"accepted": False},
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
        items = [_resolve_author(f, ctx) for f in page.object_list]
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
        return Follow.objects.filter(
            follower_fqid=decoded_fqid, following_fqid=author.fqid
        ).first()

    def get(self, request, author_fqid, foreign_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        decoded = unquote(foreign_fqid)
        follow = self._follow(author, decoded)
        if not follow or not follow.accepted:
            raise Http404
        return Response(_resolve_author(decoded, {"request": request}))

    def put(self, request, author_fqid, foreign_fqid):
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
        follow.save()
        return Response(_resolve_author(decoded, {"request": request}))

    def delete(self, request, author_fqid, foreign_fqid):
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
            actor_data = _resolve_author(f.follower_fqid, ctx)
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


class InboxAPIView(APIView):
    """
    POST /api/authors/{AUTHOR_SERIAL}/inbox

    Receives a follow request sent by a remote node on behalf of a remote
    author (the "actor") who wants to follow the local AUTHOR_SERIAL (the
    "object").  Creates a pending Follow record (accepted=False).

    Expected body::

        {
            "type": "follow",
            "summary": "actor wants to follow object",
            "actor":  { "type": "author", "id": "<actor FQID>", ... },
            "object": { "type": "author", "id": "<AUTHOR_SERIAL FQID>", ... }
        }
    """

    def post(self, request, author_fqid):
        author = get_object_or_404(Author, pk=author_fqid)
        data = request.data

        item_type = str(data.get("type", "")).strip().lower()
        if item_type not in {"follow", "comment", "like"}:
            return Response(
                {"detail": "Unsupported inbox item type. Expected one of: follow, comment, like."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        if item_type == "follow":
            actor = data.get("actor", {})
            actor_fqid = (actor.get("id") or "").strip()
            if not actor_fqid:
                return Response(
                    {"detail": "actor.id is required."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )

            _, created = Follow.objects.get_or_create(
                follower_fqid=actor_fqid,
                following_fqid=author.fqid,
                defaults={"accepted": False},
            )
            return Response(
                {
                    "detail": (
                        "Follow request received."
                        if created
                        else "Follow request already exists."
                    )
                },
                status=drf_status.HTTP_201_CREATED if created else drf_status.HTTP_200_OK,
            )

        if item_type == "comment":
            comment_id = str(data.get("id", "")).strip()
            author_obj = data.get("author", {})
            comment_author_fqid = str(author_obj.get("id", "")).strip()
            entry_fqid = str(data.get("entry", "")).strip()
            comment_text = str(data.get("comment", "")).strip()
            content_type = str(
                data.get("contentType", "text/plain")).strip() or "text/plain"

            if not comment_author_fqid or not entry_fqid or not comment_text:
                return Response(
                    {"detail": "comment.author.id, comment.entry, and comment.comment are required."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )

            comment_fqid = comment_id or f"{author.host}authors/{author.id}/commented/{uuid.uuid4()}"
            _, created = Comment.objects.get_or_create(
                fqid=comment_fqid,
                defaults={
                    "author_fqid": comment_author_fqid,
                    "entry_fqid": entry_fqid,
                    "comment": comment_text,
                    "content_type": content_type,
                },
            )
            return Response(
                {"detail": "Comment received." if created else "Comment already exists."},
                status=drf_status.HTTP_201_CREATED if created else drf_status.HTTP_200_OK,
            )

        like_id = str(data.get("id", "")).strip()
        author_obj = data.get("author", {})
        like_author_fqid = str(author_obj.get("id", "")).strip()
        object_fqid = str(data.get("object", "")).strip()

        if not like_author_fqid or not object_fqid:
            return Response(
                {"detail": "like.author.id and like.object are required."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        like_fqid = like_id or f"{author.host}authors/{author.id}/liked/{uuid.uuid4()}"
        _, created = Like.objects.get_or_create(
            fqid=like_fqid,
            defaults={
                "author_fqid": like_author_fqid,
                "object_fqid": object_fqid,
            },
        )
        return Response(
            {"detail": "Like received." if created else "Like already exists."},
            status=drf_status.HTTP_201_CREATED if created else drf_status.HTTP_200_OK,
        )
