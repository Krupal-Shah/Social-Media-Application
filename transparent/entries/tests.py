"""Test cases for the entries app."""

from __future__ import annotations

import uuid
from urllib.parse import quote
from unittest.mock import patch

from django.conf import settings
import base64
from django.test import TestCase
from rest_framework.test import APITestCase

from authors.models import Author
from entries.models import Entry, EntryDelivery
from entries.utils import comment_payload, like_payload
from inbox.models import InboxItem
from interactions.models import Comment, Like
from nodes.models import Node, RemoteAuthor
from social.models import Follow
from django.core.files.uploadedfile import SimpleUploadedFile


def _create_author(*, username: str, display_name: str, approved: bool = True) -> Author:
    """Execute create author."""
    author = Author.objects.create_user(
        username=username,
        password="pw123456!",
        display_name=display_name,
        host=getattr(settings, "SERVICE_URL", "http://testserver/api/"),
        fqid="",
    )
    author.approved = approved
    author.save()
    return author


def _create_entry(
        *,
        author: Author,
        title: str,
        visibility: str,
        content: str = "hello",
        content_type: str = "text/plain",
        description: str = "",
) -> Entry:
    """Execute create entry."""
    entry = Entry.objects.create(
        author=author,
        title=title,
        description=description,
        content=content,
        content_type=content_type,
        visibility=visibility,
        fqid="",
    )
    return entry


class EntriesListVisibilityAPITests(APITestCase):
    def setUp(self):
        """Execute setUp."""
        super().setUp()
        self.author = _create_author(username="author", display_name="Author")
        self.viewer = _create_author(username="viewer", display_name="Viewer")

        self.public = _create_entry(
            author=self.author, title="pub", visibility="PUBLIC"
        )
        self.unlisted = _create_entry(
            author=self.author, title="unlisted", visibility="UNLISTED"
        )
        self.friends = _create_entry(
            author=self.author, title="friends", visibility="FRIENDS"
        )
        self.deleted = _create_entry(
            author=self.author, title="deleted", visibility="DELETED"
        )

        self.list_url = f"/api/authors/{self.author.id}/entries/"

    def _list_titles(self):
        """Execute list titles."""
        resp = self.client.get(self.list_url + "?size=50")
        self.assertEqual(resp.status_code, 200)
        return [e["title"] for e in resp.data["src"]]

    def test_unauthenticated_sees_public_only(self):
        """Test that unauthenticated sees public only."""
        titles = self._list_titles()
        self.assertEqual(titles, ["pub"])  # newest first, but only one visible


class PayloadShapeTests(APITestCase):
    def setUp(self):
        """Execute setUp."""
        super().setUp()
        self.author = _create_author(
            username="author_payload", display_name="Author")
        self.viewer = _create_author(
            username="viewer_payload", display_name="Viewer")

        self.public = _create_entry(
            author=self.author, title="pub", visibility="PUBLIC"
        )
        self.unlisted = _create_entry(
            author=self.author, title="unlisted", visibility="UNLISTED"
        )
        self.friends = _create_entry(
            author=self.author, title="friends", visibility="FRIENDS"
        )
        self.deleted = _create_entry(
            author=self.author, title="deleted", visibility="DELETED"
        )

        self.list_url = f"/api/authors/{self.author.id}/entries/"

    def _list_titles(self):
        """Execute list titles."""
        resp = self.client.get(self.list_url + "?size=50")
        self.assertEqual(resp.status_code, 200)
        return [entry["title"] for entry in resp.data["src"]]

    def test_comment_payload_matches_expected_outbound_shape(self):
        """Test that comment payload matches expected outbound shape."""
        author = _create_author(username="commenter", display_name="Commenter")
        comment = Comment.objects.create(
            fqid=f"{author.host}authors/{author.id}/commented/{uuid.uuid4()}",
            author_fqid=author.fqid,
            entry_fqid="https://remote.example/api/authors/target/entries/entry-1/",
            comment="pls work",
            content_type="text/plain",
        )

        payload = comment_payload(comment)

        self.assertEqual(payload["type"], "comment")
        self.assertEqual(payload["entry"], comment.entry_fqid)
        self.assertEqual(payload["entry_url"], comment.entry_fqid)
        self.assertEqual(payload["contentType"], "text/plain")
        self.assertEqual(payload["content_type"], "text/plain")
        self.assertEqual(payload["author"]["displayName"], "Commenter")

    def test_like_payload_matches_expected_outbound_shape(self):
        """Test that like payload matches expected outbound shape."""
        author = _create_author(username="liker", display_name="Liker")
        like = Like.objects.create(
            fqid=f"{author.host}authors/{author.id}/liked/{uuid.uuid4()}",
            author_fqid=author.fqid,
            object_fqid="https://remote.example/api/authors/target/entries/entry-1/",
        )

        payload = like_payload(like)

        self.assertEqual(payload["type"], "like")
        self.assertEqual(payload["object"], like.object_fqid)
        self.assertEqual(payload["author"]["displayName"], "Liker")
        self.assertEqual(payload["author"]["host"], author.host)

    def test_authenticated_non_follower_sees_public_only(self):
        """Test that authenticated non follower sees public only."""
        self.client.force_authenticate(user=self.viewer)
        titles = self._list_titles()
        self.assertEqual(titles, ["pub"])

    def test_authenticated_follower_sees_public_and_unlisted(self):
        """Test that authenticated follower sees public and unlisted."""
        Follow.objects.create(
            follower_fqid=self.viewer.fqid,
            following_fqid=self.author.fqid,
            accepted=True,
        )
        self.client.force_authenticate(user=self.viewer)
        titles = self._list_titles()
        self.assertCountEqual(titles, ["pub", "unlisted"])
        self.assertNotIn("friends", titles)

    def test_authenticated_friend_sees_public_unlisted_and_friends(self):
        """Test that authenticated friend sees public unlisted and friends."""
        Follow.objects.create(
            follower_fqid=self.viewer.fqid,
            following_fqid=self.author.fqid,
            accepted=True,
        )
        Follow.objects.create(
            follower_fqid=self.author.fqid,
            following_fqid=self.viewer.fqid,
            accepted=True,
        )
        self.client.force_authenticate(user=self.viewer)
        titles = self._list_titles()
        self.assertCountEqual(titles, ["pub", "unlisted", "friends"])

    def test_author_sees_all_non_deleted(self):
        """Test that author sees all non deleted."""
        self.client.force_authenticate(user=self.author)
        titles = self._list_titles()
        self.assertCountEqual(titles, ["pub", "unlisted", "friends"])
        self.assertNotIn("deleted", titles)

    def test_list_is_paginated_response_shape(self):
        """Test that list is paginated response shape."""
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "entries")
        self.assertIn("src", resp.data)


class EntriesCreateUpdateDeleteAPITests(APITestCase):
    def setUp(self):
        """Execute setUp."""
        super().setUp()
        self.me = _create_author(username="me", display_name="Me")
        self.other = _create_author(username="other", display_name="Other")
        self.list_url = f"/api/authors/{self.me.id}/entries/"

    def test_create_requires_auth(self):
        """Test that create requires auth."""
        payload = {
            "title": "t",
            "description": "d",
            "contentType": "text/plain",
            "content": "hello",
            "visibility": "PUBLIC",
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_create_forbidden_when_not_author(self):
        """Test that create forbidden when not author."""
        self.client.force_authenticate(user=self.other)
        payload = {
            "title": "t",
            "description": "d",
            "contentType": "text/plain",
            "content": "hello",
            "visibility": "PUBLIC",
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_create_success(self):
        """Test that create success."""
        self.client.force_authenticate(user=self.me)
        payload = {
            "title": "t",
            "description": "d",
            "contentType": "text/plain",
            "content": "hello",
            "visibility": "UNLISTED",
        }
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["type"], "entry")
        self.assertEqual(resp.data["title"], "t")
        self.assertEqual(resp.data["contentType"], "text/plain")
        self.assertEqual(resp.data["visibility"], "UNLISTED")

        self.assertTrue(Entry.objects.filter(
            author=self.me, title="t").exists())

    def test_put_requires_owner_and_full_payload(self):
        """Test that put requires owner and full payload."""
        entry = _create_entry(
            author=self.me,
            title="old",
            description="old d",
            visibility="PUBLIC",
            content="old",
            content_type="text/plain",
        )
        url = f"/api/authors/{self.me.id}/entries/{entry.id}/"

        resp = self.client.put(url, {"title": "x"}, format="json")
        self.assertEqual(resp.status_code, 401)

        self.client.force_authenticate(user=self.other)
        resp = self.client.put(
            url,
            {
                "title": "new",
                "description": "new d",
                "contentType": "text/plain",
                "content": "new",
                "visibility": "PUBLIC",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

        self.client.force_authenticate(user=self.me)
        resp = self.client.put(url, {"title": "only title"}, format="json")
        self.assertEqual(resp.status_code, 400)

        resp = self.client.put(
            url,
            {
                "title": "new",
                "description": "new d",
                "contentType": "text/markdown",
                "content": "# hi",
                "visibility": "FRIENDS",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.title, "new")
        self.assertEqual(entry.description, "new d")
        self.assertEqual(entry.content_type, "text/markdown")
        self.assertEqual(entry.visibility, "FRIENDS")

    def test_delete_marks_deleted_and_hides_entry(self):
        """Test that delete marks deleted and hides entry."""
        entry = _create_entry(
            author=self.me,
            title="t",
            visibility="PUBLIC",
        )
        url = f"/api/authors/{self.me.id}/entries/{entry.id}/"

        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 401)

        self.client.force_authenticate(user=self.other)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 403)

        self.client.force_authenticate(user=self.me)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)
        entry.refresh_from_db()
        self.assertEqual(entry.visibility, "DELETED")

        # Deleted entries are not retrievable via API
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_staff_can_get_deleted_entry(self):
        """Test that staff can get deleted entry."""
        entry = _create_entry(
            author=self.me,
            title="t",
            visibility="DELETED",
        )
        staff = _create_author(username="staff_api", display_name="Staff API")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        url = f"/api/authors/{self.me.id}/entries/{entry.id}/"

        self.client.force_authenticate(user=staff)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)


class EntriesDeletedVisibilityStaffTests(APITestCase):
    def setUp(self):
        """Execute setUp."""
        super().setUp()
        self.author = _create_author(
            username="author_del", display_name="Author Del")
        self.staff = _create_author(
            username="staff_del", display_name="Staff Del")
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.viewer = _create_author(
            username="viewer_del", display_name="Viewer Del")
        self.deleted = _create_entry(
            author=self.author, title="deleted", visibility="DELETED")

    def test_non_staff_cannot_get_deleted_by_fqid(self):
        """Test that non staff cannot get deleted by fqid."""
        encoded = quote(self.deleted.fqid, safe="")
        self.client.force_authenticate(user=self.viewer)
        resp = self.client.get(f"/api/entries/{encoded}")
        self.assertEqual(resp.status_code, 404)

    def test_staff_can_get_deleted_by_fqid(self):
        """Test that staff can get deleted by fqid."""
        encoded = quote(self.deleted.fqid, safe="")
        self.client.force_authenticate(user=self.staff)
        resp = self.client.get(f"/api/entries/{encoded}")
        self.assertEqual(resp.status_code, 200)

    def test_staff_sees_deleted_in_author_entries_list(self):
        """Test that staff sees deleted in author entries list."""
        self.client.force_authenticate(user=self.staff)
        resp = self.client.get(
            f"/api/authors/{self.author.id}/entries/?size=50")
        self.assertEqual(resp.status_code, 200)
        titles = [e["title"] for e in resp.data["src"]]
        self.assertIn("deleted", titles)


class EntriesFQIDAndImageAPITests(APITestCase):
    def setUp(self):
        """Execute setUp."""
        super().setUp()
        self.author = _create_author(username="author", display_name="Author")
        self.viewer = _create_author(username="viewer", display_name="Viewer")

    def test_entry_get_by_fqid(self):
        """Test that entry get by fqid."""
        entry = _create_entry(author=self.author,
                              title="t", visibility="PUBLIC")
        encoded = quote(entry.fqid, safe="")
        resp = self.client.get(f"/api/entries/{encoded}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], entry.fqid)

    def test_entry_image_by_serial_returns_decoded_bytes(self):
        """Test that entry image by serial returns decoded bytes."""
        raw = b"\x89PNG\r\n"  # small fake header
        encoded = base64.b64encode(raw).decode("ascii")
        entry = _create_entry(
            author=self.author,
            title="img",
            visibility="PUBLIC",
            content=encoded,
            content_type="image/png;base64",
        )
        url = f"/api/authors/{self.author.id}/entries/{entry.id}/image"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/octet-stream")
        self.assertEqual(resp.content, raw)

    def test_entry_image_by_serial_404_for_non_image(self):
        """Test that entry image by serial 404 for non image."""
        entry = _create_entry(
            author=self.author,
            title="t",
            visibility="PUBLIC",
            content="hello",
            content_type="text/plain",
        )
        url = f"/api/authors/{self.author.id}/entries/{entry.id}/image"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_entry_image_by_fqid_returns_image(self):
        """Test that entry image by fqid returns image."""
        raw = b"GIF89a"  # fake gif header
        encoded = base64.b64encode(raw).decode("ascii")
        entry = _create_entry(
            author=self.author,
            title="img",
            visibility="PUBLIC",
            content=encoded,
            content_type="application/base64",
        )
        encoded_fqid = quote(entry.fqid, safe="")
        resp = self.client.get(f"/api/entries/{encoded_fqid}/image")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/octet-stream")
        self.assertEqual(resp.content, raw)

    def test_entry_image_by_fqid_404_when_no_image_files(self):
        """Test that entry image by fqid 404 when no image files."""
        entry = _create_entry(
            author=self.author,
            title="noimage",
            visibility="PUBLIC",
            content="hello",
            content_type="text/plain",
        )
        encoded = quote(entry.fqid, safe="")
        resp = self.client.get(f"/api/entries/{encoded}/image")
        self.assertEqual(resp.status_code, 404)


"""
Claude Sonnet 4.6, Anthropic, 2026-03-13, https://claude.ai/share/f7e1088d-8c54-42d6-b3a4-fac7fa9f00f5 
Prompt: Help me generate some test cases for the following and friends logic. only test the api endpoints and follow the existing testing structure
"""


class EntryVisibilityAPITests(APITestCase):
    """
    Tests for EntryListCreateAPIView GET — visibility filtering based on
    the relationship between the requesting user and the author.
    """

    def setUp(self):
        """Execute setUp."""
        self.author = _create_author(
            username="author2", display_name="Author2")
        self.friend = _create_author(
            username="friend2", display_name="Friend2")
        self.follower = _create_author(
            username="follower2", display_name="Follower2")
        self.stranger = _create_author(
            username="stranger2", display_name="Stranger2")

        # friend <-> author mutually follow each other
        Follow.objects.create(
            follower_fqid=self.friend.fqid,
            following_fqid=self.author.fqid,
            accepted=True,
        )
        Follow.objects.create(
            follower_fqid=self.author.fqid,
            following_fqid=self.friend.fqid,
            accepted=True,
        )

        # follower only follows author (not mutual)
        Follow.objects.create(
            follower_fqid=self.follower.fqid,
            following_fqid=self.author.fqid,
            accepted=True,
        )

        self.public_entry = _create_entry(
            author=self.author, title="Public", visibility="PUBLIC",
        )
        self.unlisted_entry = _create_entry(
            author=self.author, title="Unlisted", visibility="UNLISTED",
        )
        self.friends_entry = _create_entry(
            author=self.author, title="Friends", visibility="FRIENDS",
        )
        self.deleted_entry = _create_entry(
            author=self.author, title="Deleted", visibility="DELETED",
        )

    def _get_entry_ids(self, resp):
        """Execute get entry ids."""
        return {e["id"] for e in resp.data["src"]}

    def test_unauthenticated_sees_only_public(self):
        """Test that unauthenticated sees only public."""
        resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
        self.assertEqual(resp.status_code, 200)
        ids = self._get_entry_ids(resp)
        self.assertIn(self.public_entry.fqid, ids)
        self.assertNotIn(self.unlisted_entry.fqid, ids)
        self.assertNotIn(self.friends_entry.fqid, ids)
        self.assertNotIn(self.deleted_entry.fqid, ids)

    def test_stranger_sees_only_public(self):
        """Test that stranger sees only public."""
        self.client.force_authenticate(user=self.stranger)
        resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
        self.assertEqual(resp.status_code, 200)
        ids = self._get_entry_ids(resp)
        self.assertIn(self.public_entry.fqid, ids)
        self.assertNotIn(self.unlisted_entry.fqid, ids)
        self.assertNotIn(self.friends_entry.fqid, ids)
        self.assertNotIn(self.deleted_entry.fqid, ids)

    def test_follower_sees_public_and_unlisted_not_friends(self):
        """Test that follower sees public and unlisted not friends."""
        self.client.force_authenticate(user=self.follower)
        resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
        self.assertEqual(resp.status_code, 200)
        ids = self._get_entry_ids(resp)
        self.assertIn(self.public_entry.fqid, ids)
        self.assertIn(self.unlisted_entry.fqid, ids)
        self.assertNotIn(self.friends_entry.fqid, ids)
        self.assertNotIn(self.deleted_entry.fqid, ids)

    def test_friend_sees_public_unlisted_and_friends(self):
        """Test that friend sees public unlisted and friends."""
        self.client.force_authenticate(user=self.friend)
        resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
        self.assertEqual(resp.status_code, 200)
        ids = self._get_entry_ids(resp)
        self.assertIn(self.public_entry.fqid, ids)
        self.assertIn(self.unlisted_entry.fqid, ids)
        self.assertIn(self.friends_entry.fqid, ids)
        self.assertNotIn(self.deleted_entry.fqid, ids)

    def test_author_sees_all_except_deleted(self):
        """Test that author sees all except deleted."""
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
        self.assertEqual(resp.status_code, 200)
        ids = self._get_entry_ids(resp)
        self.assertIn(self.public_entry.fqid, ids)
        self.assertIn(self.unlisted_entry.fqid, ids)
        self.assertIn(self.friends_entry.fqid, ids)
        self.assertNotIn(self.deleted_entry.fqid, ids)

    def test_pending_follow_does_not_grant_unlisted_access(self):
        """Test that pending follow does not grant unlisted access."""
        pending = _create_author(username="pending2", display_name="Pending2")
        Follow.objects.create(
            follower_fqid=pending.fqid,
            following_fqid=self.author.fqid,
            accepted=False,
        )
        self.client.force_authenticate(user=pending)
        resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
        self.assertEqual(resp.status_code, 200)
        ids = self._get_entry_ids(resp)
        self.assertIn(self.public_entry.fqid, ids)
        self.assertNotIn(self.unlisted_entry.fqid, ids)
        self.assertNotIn(self.friends_entry.fqid, ids)

    def test_one_way_follow_is_not_friendship(self):
        """author follows one_way but one_way does NOT follow back — not friends."""
        one_way = _create_author(username="oneway2", display_name="OneWay2")
        Follow.objects.create(
            follower_fqid=self.author.fqid,
            following_fqid=one_way.fqid,
            accepted=True,
        )
        self.client.force_authenticate(user=one_way)
        resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
        self.assertEqual(resp.status_code, 200)
        ids = self._get_entry_ids(resp)
        self.assertNotIn(self.friends_entry.fqid, ids)


class EntryDetailAPIVisibilityTests(APITestCase):
    """
    Tests for EntryDetailAPIView GET — per-entry visibility gating.
    """

    def setUp(self):
        """Execute setUp."""
        self.author = _create_author(
            username="author3", display_name="Author3")
        self.friend = _create_author(
            username="friend3", display_name="Friend3")
        self.stranger = _create_author(
            username="stranger3", display_name="Stranger3")

        Follow.objects.create(
            follower_fqid=self.friend.fqid,
            following_fqid=self.author.fqid,
            accepted=True,
        )
        Follow.objects.create(
            follower_fqid=self.author.fqid,
            following_fqid=self.friend.fqid,
            accepted=True,
        )

        self.friends_entry = _create_entry(
            author=self.author, title="Friends Only", visibility="FRIENDS",
        )

    def test_friends_entry_hidden_from_unauthenticated(self):
        """Test that friends entry hidden from unauthenticated."""
        resp = self.client.get(
            f"/api/authors/{self.author.id}/entries/{self.friends_entry.id}/"
        )
        self.assertEqual(resp.status_code, 404)

    def test_friends_entry_hidden_from_stranger(self):
        """Test that friends entry hidden from stranger."""
        self.client.force_authenticate(user=self.stranger)
        resp = self.client.get(
            f"/api/authors/{self.author.id}/entries/{self.friends_entry.id}/"
        )
        self.assertEqual(resp.status_code, 404)

    def test_friends_entry_visible_to_friend(self):
        """Test that friends entry visible to friend."""
        self.client.force_authenticate(user=self.friend)
        resp = self.client.get(
            f"/api/authors/{self.author.id}/entries/{self.friends_entry.id}/"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["title"], "Friends Only")

    def test_friends_entry_visible_to_author(self):
        """Test that friends entry visible to author."""
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(
            f"/api/authors/{self.author.id}/entries/{self.friends_entry.id}/"
        )
        self.assertEqual(resp.status_code, 200)


class ImageHostingTests(APITestCase):
    def setUp(self):
        """Execute setUp."""
        super().setUp()
        # Using your internal helper function!
        self.author = _create_author(
            username="imguser", display_name="Img User", approved=True)
        # Log the user into the standard Django session
        self.client.login(username="imguser", password="pw123456!")

    def test_create_entry_with_image_saves_base64_content(self):
        """Test that uploaded images are stored directly as base64 in Entry.content."""
        # Create a tiny dummy GIF image in memory
        tiny_gif = b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x01\x00\x00"
        image_file = SimpleUploadedFile(
            "test.gif", tiny_gif, content_type="image/gif")

        # Simulate the user submitting the post form with the image attached
        resp = self.client.post("/api/entries/create/", {
            "title": "My Image Post",
            "visibility": "PUBLIC",
            "image": image_file
        })

        # It should successfully process and redirect the user back to the stream
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/stream/")

        # Check the database to ensure it was saved correctly
        entry = self.author.entries.first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.content_type, "application/base64")
        self.assertTrue(isinstance(entry.content, str)
                        and len(entry.content) > 0)


class FederationDeliveryTests(APITestCase):
    def setUp(self):
        """Execute setUp."""
        super().setUp()
        self.author = _create_author(
            username="federated_author",
            display_name="Federated Author",
        )
        self.remote_node = Node.objects.create(
            base_url="https://remote.example/api/",
            username="remote-user",
            password="remote-pass",
        )
        self.remote_follower_fqid = (
            "https://remote.example/api/authors/"
            "11111111-1111-1111-1111-111111111111"
        )

    @patch("entries.utils.send_inbox_item_to_author", autospec=True)
    def test_public_entries_send_to_all_discovered_remote_authors(self, send_mock):
        """Test that public entries send to all discovered remote authors."""
        send_mock.return_value = True
        remote_author_fqid = (
            "https://remote.example/api/authors/"
            "22222222-2222-2222-2222-222222222222"
        )
        inactive_node = Node.objects.create(
            base_url="https://inactive.example/api/",
            username="inactive-user",
            password="inactive-pass",
            active=False,
        )
        inactive_author_fqid = (
            "https://inactive.example/api/authors/"
            "33333333-3333-3333-3333-333333333333"
        )
        RemoteAuthor.objects.create(
            node=self.remote_node,
            fqid=self.remote_follower_fqid,
            display_name="Follower Remote",
        )
        RemoteAuthor.objects.create(
            node=self.remote_node,
            fqid=remote_author_fqid,
            display_name="Discovered Remote",
        )
        RemoteAuthor.objects.create(
            node=inactive_node,
            fqid=inactive_author_fqid,
            display_name="Inactive Remote",
        )

        entry = _create_entry(
            author=self.author,
            title="Broadcast",
            visibility="PUBLIC",
        )

        from entries.utils import push_entry_to_remote_inboxes

        push_entry_to_remote_inboxes(entry)

        self.assertEqual(send_mock.call_count, 2)
        sent_recipients = {call.args[0] for call in send_mock.call_args_list}
        self.assertSetEqual(
            sent_recipients,
            {self.remote_follower_fqid, remote_author_fqid},
        )
        self.assertFalse(
            EntryDelivery.objects.filter(
                entry=entry,
                recipient_fqid=inactive_author_fqid,
            ).exists()
        )

    @patch("entries.utils.send_inbox_item_to_author", autospec=True)
    def test_entry_edits_are_resent_to_previous_remote_destinations(self, send_mock):
        """Test that entry edits are resent to previous remote destinations."""
        send_mock.return_value = True
        Follow.objects.create(
            follower_fqid=self.remote_follower_fqid,
            following_fqid=self.author.fqid,
            accepted=True,
        )

        entry = _create_entry(
            author=self.author,
            title="Original",
            visibility="PUBLIC",
        )

        from entries.utils import push_entry_to_remote_inboxes

        push_entry_to_remote_inboxes(entry)
        self.assertEqual(send_mock.call_count, 1)
        self.assertTrue(
            EntryDelivery.objects.filter(
                entry=entry,
                recipient_fqid=self.remote_follower_fqid,
                recipient_node=self.remote_node,
            ).exists()
        )

        Follow.objects.filter(
            follower_fqid=self.remote_follower_fqid,
            following_fqid=self.author.fqid,
        ).delete()

        entry.title = "Edited"
        entry.save(update_fields=["title"])
        push_entry_to_remote_inboxes(entry, update=True)

        self.assertEqual(send_mock.call_count, 2)
        send_mock.assert_called_with(
            self.remote_follower_fqid,
            {
                "type": "entry",
                "id": entry.fqid,
                "title": "Edited",
                "description": "",
                "contentType": "text/plain",
                "content": "hello",
                "visibility": "PUBLIC",
                "published": entry.published.isoformat(),
                "updated": entry.updated_at.isoformat(),
                "author": {
                    "type": "author",
                    "id": self.author.fqid,
                    "displayName": self.author.display_name,
                    "username": self.author.username,
                    "host": self.author.host,
                    "github": "",
                    "profileImage": "",
                },
            },
            method="PUT",
        )

    def test_stream_includes_followed_remote_unlisted_entries(self):
        """Test that stream includes followed remote unlisted entries."""
        viewer = _create_author(
            username="viewer_remote", display_name="Viewer")
        self.client.login(username="viewer_remote", password="pw123456!")

        Follow.objects.create(
            follower_fqid=viewer.fqid,
            following_fqid=self.remote_follower_fqid,
            accepted=True,
        )
        InboxItem.objects.create(
            author=viewer,
            type="entry",
            payload={
                "type": "entry",
                "id": f"{self.remote_follower_fqid}/entries/abc123",
                "title": "Remote Unlisted",
                "description": "",
                "contentType": "text/plain",
                "content": "hello remote",
                "visibility": "UNLISTED",
                "published": "2026-03-28T12:00:00Z",
                "author": {
                    "type": "author",
                    "id": self.remote_follower_fqid,
                    "displayName": "Remote Person",
                },
            },
        )

        response = self.client.get("/stream/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Remote Unlisted")
