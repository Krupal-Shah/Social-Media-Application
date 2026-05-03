"""View logic for the inbox app."""

import logging
import uuid

from django.shortcuts import get_object_or_404
from rest_framework import status as drf_status
from rest_framework.response import Response
from rest_framework.views import APIView

from authors.models import Author
from interactions.models import Comment, Like
from social.models import Follow
from django.utils import timezone
from nodes.remote import authenticate_remote_api_request, upsert_remote_author

from .models import InboxItem
from .adapters import normalize_payload


logger = logging.getLogger(__name__)


def _upsert_remote_author_from_payload(item_type, payload, *, node=None):
    """Execute upsert remote author from payload."""
    data = payload or {}
    author_candidates = []
    if item_type == "author":
        author_candidates = [data if isinstance(data, dict) else {}]
    elif item_type == "follow":
        author_candidates = [
            data.get("actor", {}) if isinstance(data, dict) else {},
            data.get("object", {}) if isinstance(data, dict) else {},
        ]
    elif item_type in {"entry", "comment", "like"}:
        author_candidates = [data.get("author", {}) if isinstance(data, dict) else {}]

    for author_data in author_candidates:
        author_fqid = str(author_data.get("id", "")).strip()
        if not author_fqid:
            continue
        upsert_remote_author(author_data, node=node)


def _authenticate_remote_node(request, payload):
    """Execute authenticate remote node."""
    return authenticate_remote_api_request(request, payload=payload, realm="node-inbox")


class InboxAPIView(APIView):
    """Node-to-node inbox endpoint for follows, authors, entries, comments, and likes."""

    authentication_classes = []
    permission_classes = []

    def _upsert_entry_item(self, author, data):
        """Execute upsert entry item."""
        entry_id = str(data.get("id", "")).strip()
        if not entry_id:
            InboxItem.objects.create(author=author, type="entry", payload=data)
            return

        existing = None
        for item in InboxItem.objects.filter(author=author, type="entry").order_by("-received"):
            payload = item.payload or {}
            if str(payload.get("id", "")).strip() == entry_id:
                existing = item
                break

        if existing:
            existing.payload = data
            existing.received = timezone.now()
            existing.save(update_fields=["payload", "received"])
            return

        InboxItem.objects.create(author=author, type="entry", payload=data)

    def _handle(self, request, author_fqid, is_update=False):
        """Execute handle."""
        raw_payload = request.data
        logger.debug("Received inbox request: author_fqid=%s is_update=%s payload=%s",
                     author_fqid, is_update, raw_payload)
        node, auth_error = _authenticate_remote_node(request, raw_payload)
        if auth_error is not None:
            return auth_error

        data, adapter_slug = normalize_payload(node, request, raw_payload)
        item_type = str(data.get("type", "")).strip().lower()
        author = get_object_or_404(Author, pk=author_fqid)
        verb = "PUT" if is_update else "POST"
        logger.info(
            "Inbox %s received: target_author=%s type=%s adapter=%s",
            verb,
            author_fqid,
            item_type,
            adapter_slug,
        )

        if item_type not in {"follow", "author", "entry", "comment", "like"}:
            return Response(
                {"detail": "Unsupported inbox item type. Expected one of: follow, author, entry, comment, like."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        _upsert_remote_author_from_payload(item_type, data, node=node)

        if item_type == "author":
            author_id = str(data.get("id", "")).strip()
            if not author_id:
                return Response(
                    {"detail": "author.id is required."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            logger.info(
                "Inbox author processed: target_author=%s remote_author=%s adapter=%s",
                author_fqid,
                author_id,
                adapter_slug,
            )
            return Response({"detail": "Author received."}, status=drf_status.HTTP_201_CREATED)

        # Prevent accepting items that originate from the target author itself
        # (e.g., misconfigured SERVICE_URL or node that reflects back). If the
        # payload's author id equals the target author, ignore storage.
        payload_author = {}
        if isinstance(data, dict):
            payload_author = data.get("author", {}) or {}
        payload_author_id = str(payload_author.get("id", "")).strip()
        if payload_author_id and payload_author_id == str(author.fqid).strip():
            logger.info(
                "Inbox ignored self-originated item: target=%s type=%s payload_author=%s",
                author_fqid,
                item_type,
                payload_author_id,
            )
            return Response({"detail": "Ignored self-originated item."}, status=drf_status.HTTP_200_OK)

        if item_type == "entry":
            self._upsert_entry_item(author, data)
        else:
            # For non-entry types attempt to upsert by payload id to avoid duplicate
            # inbox items when the same notification is received multiple times.
            payload_id = ""
            if isinstance(data, dict):
                payload_id = str(data.get("id", "")).strip()

            if payload_id and item_type in {"comment", "like", "follow"}:
                existing = None
                for item in InboxItem.objects.filter(author=author, type=item_type).order_by("-received"):
                    p = item.payload or {}
                    if str(p.get("id", "")).strip() == payload_id:
                        existing = item
                        break
                if existing:
                    existing.payload = data
                    existing.received = timezone.now()
                    existing.save(update_fields=["payload", "received"])
                else:
                    InboxItem.objects.create(
                        author=author, type=item_type, payload=data)
            else:
                InboxItem.objects.create(
                    author=author, type=item_type, payload=data)
        logger.info(
            "Inbox item stored: target_author=%s type=%s adapter=%s payload=%s",
            author_fqid,
            item_type,
            adapter_slug,
            data,
        )

        if item_type == "follow":
            actor = data.get("actor", {})
            object_data = data.get("object", {})
            actor_fqid = (actor.get("id") or "").strip()
            object_fqid = (object_data.get("id") or "").strip()
            status = str(data.get("status") or "REQUESTED").upper()
            if not actor_fqid:
                logger.warning(
                    "Inbox follow validation failed: missing actor id payload=%s target=%s adapter=%s",
                    data,
                    author_fqid,
                    adapter_slug,
                )
                return Response(
                    {"detail": "follow.actor.id is required."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            if status not in {"REQUESTED", "ACCEPTED", "REJECTED", "UNFOLLOW"}:
                logger.warning(
                    "Inbox follow validation failed: invalid status=%s payload=%s target=%s adapter=%s",
                    status,
                    data,
                    author_fqid,
                    adapter_slug,
                )
                return Response(
                    {"detail": "follow.status must be one of REQUESTED, ACCEPTED, REJECTED, UNFOLLOW."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )

            if status == "REQUESTED":
                _, created = Follow.objects.get_or_create(
                    follower_fqid=actor_fqid,
                    following_fqid=author.fqid,
                    defaults={"accepted": False},
                )
                logger.info(
                    "Inbox follow processed: status=%s follower=%s target=%s created=%s",
                    status,
                    actor_fqid,
                    author.fqid,
                    created,
                )
                status_code = drf_status.HTTP_201_CREATED if created else drf_status.HTTP_200_OK
                return Response({"detail": "Follow received."}, status=status_code)

            if status == "ACCEPTED":
                target_fqid = object_fqid or actor_fqid
                Follow.objects.update_or_create(
                    follower_fqid=author.fqid,
                    following_fqid=target_fqid,
                    defaults={"accepted": True},
                )
                logger.info(
                    "Inbox follow processed: status=%s follower=%s accepted_target=%s",
                    status,
                    author.fqid,
                    target_fqid,
                )
                return Response({"detail": "Follow acceptance received."}, status=drf_status.HTTP_200_OK)

            if status == "UNFOLLOW":
                # Remote actor is unfollowing the target author; remove follow record(s)
                deleted, _ = Follow.objects.filter(
                    follower_fqid=actor_fqid,
                    following_fqid=author.fqid,
                ).delete()
                logger.info(
                    "Inbox unfollow processed: actor=%s target=%s deleted=%s",
                    actor_fqid,
                    author.fqid,
                    deleted,
                )
                return Response({"detail": "Unfollow received."}, status=drf_status.HTTP_200_OK)

            target_fqid = object_fqid or actor_fqid
            deleted, _ = Follow.objects.filter(
                follower_fqid=author.fqid,
                following_fqid=target_fqid,
            ).delete()
            if not deleted:
                Follow.objects.filter(
                    follower_fqid=actor_fqid,
                    following_fqid=target_fqid,
                ).delete()
            logger.info(
                "Inbox follow processed: status=%s follower=%s target=%s",
                status,
                author.fqid,
                target_fqid,
            )
            return Response({"detail": "Follow rejection received."}, status=drf_status.HTTP_200_OK)

        if item_type == "entry":
            status_code = drf_status.HTTP_200_OK if is_update else drf_status.HTTP_201_CREATED
            return Response({"detail": "Entry received."}, status=status_code)

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
            Comment.objects.get_or_create(
                fqid=comment_fqid,
                defaults={
                    "author_fqid": comment_author_fqid,
                    "entry_fqid": entry_fqid,
                    "comment": comment_text,
                    "content_type": content_type,
                },
            )
            logger.info(
                "Inbox comment processed: comment=%s entry=%s",
                comment_fqid,
                entry_fqid,
            )
            return Response({"detail": "Comment received."}, status=drf_status.HTTP_201_CREATED)

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
        Like.objects.get_or_create(
            fqid=like_fqid,
            defaults={
                "author_fqid": like_author_fqid,
                "object_fqid": object_fqid,
            },
        )
        logger.info("Inbox like processed: like=%s object=%s",
                    like_fqid, object_fqid)
        return Response({"detail": "Like received."}, status=drf_status.HTTP_201_CREATED)

    def post(self, request, author_fqid):
        """Execute post."""
        return self._handle(request, author_fqid, is_update=False)

    def put(self, request, author_fqid):
        """Execute put."""
        return self._handle(request, author_fqid, is_update=True)
