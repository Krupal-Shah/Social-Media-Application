"""Test cases for the authors app."""

from __future__ import annotations

import base64
import uuid
from urllib.parse import quote
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APITestCase

from authors.models import Author
from nodes.models import Node, RemoteAuthor
from social.models import Follow
from inbox.models import InboxItem


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


class AuthorsListAndDetailAPITests(APITestCase):
    def test_author_list_only_includes_approved_and_paginates(self):
        """Test that author list only includes approved and paginates."""
        _create_author(username="a1", display_name="Alice", approved=True)
        _create_author(username="a2", display_name="Bob", approved=True)
        _create_author(username="a3", display_name="Charlie", approved=False)
        viewer = _create_author(username="viewer1", display_name="Viewer 1", approved=True)
        self.client.force_authenticate(user=viewer)

        resp = self.client.get("/api/authors/?size=1&page=2")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "authors")
        self.assertEqual(resp.data["count"], 3)
        self.assertEqual(resp.data["size"], 1)
        self.assertEqual(resp.data["page_number"], 2)
        self.assertEqual(len(resp.data["authors"]), 1)

    def test_author_list_size_is_clamped_to_max(self):
        """Test that author list size is clamped to max."""
        for i in range(12):
            _create_author(
                username=f"u{i}", display_name=f"User {i}", approved=True)
        viewer = _create_author(username="viewer2", display_name="Viewer 2", approved=True)
        self.client.force_authenticate(user=viewer)

        resp = self.client.get("/api/authors/?size=500")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["size"], 50)

    def test_author_detail_get(self):
        """Test that author detail get."""
        me = _create_author(username="me", display_name="Me", approved=True)
        viewer = _create_author(username="viewer3", display_name="Viewer 3", approved=True)
        self.client.force_authenticate(user=viewer)
        resp = self.client.get(f"/api/authors/{me.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "author")
        self.assertEqual(resp.data["displayName"], "Me")
        self.assertEqual(resp.data["id"], me.fqid)

    def test_author_list_requires_remote_basic_auth_or_local_session(self):
        """Test that author list requires remote basic auth or local session."""
        _create_author(username="a1", display_name="Alice", approved=True)
        resp = self.client.get("/api/authors/")
        self.assertEqual(resp.status_code, 401)

        viewer = _create_author(username="viewer", display_name="Viewer", approved=True)
        self.client.force_authenticate(user=viewer)
        resp = self.client.get("/api/authors/")
        self.assertEqual(resp.status_code, 200)

    def test_author_list_allows_active_node_basic_auth_without_base_url(self):
        """Test that author list allows active node basic auth without base url."""
        _create_author(username="a1", display_name="Alice", approved=True)
        Node.objects.create(
            base_url=None,
            username="papayawhip_node",
            password="papayawhip_secure_99",
            active=True,
        )
        token = base64.b64encode(b"papayawhip_node:papayawhip_secure_99").decode("ascii")

        resp = self.client.get(
            "/api/authors/",
            HTTP_AUTHORIZATION=f"Basic {token}",
        )

        self.assertEqual(resp.status_code, 200)

    def test_author_detail_put_requires_self(self):
        """Test that author detail put requires self."""
        me = _create_author(username="me", display_name="Me", approved=True)
        other = _create_author(
            username="other", display_name="Other", approved=True)

        payload = {
            "displayName": "New Name",
            "github": "https://github.com/example",
            "profileImage": "https://example.com/me.png",
            "description": "Hello",
        }

        # Not authenticated
        resp = self.client.put(
            f"/api/authors/{me.id}/", payload, format="json")
        self.assertEqual(resp.status_code, 401)

        # Authenticated as someone else
        self.client.force_authenticate(user=other)
        resp = self.client.put(
            f"/api/authors/{me.id}/", payload, format="json")
        self.assertEqual(resp.status_code, 403)

        # Authenticated as self
        self.client.force_authenticate(user=me)
        resp = self.client.put(
            f"/api/authors/{me.id}/", payload, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["displayName"], "New Name")

        me.refresh_from_db()
        self.assertEqual(me.display_name, "New Name")
        self.assertEqual(me.github, "https://github.com/example")
        self.assertEqual(me.profile_image, "https://example.com/me.png")
        self.assertEqual(me.description, "Hello")

    def test_author_by_fqid_get_percent_encoded(self):
        """Test that author by fqid get percent encoded."""
        me = _create_author(username="me", display_name="Me", approved=True)
        viewer = _create_author(username="viewer4", display_name="Viewer 4", approved=True)
        self.client.force_authenticate(user=viewer)
        encoded = quote(me.fqid, safe="")
        resp = self.client.get(f"/api/authors/{encoded}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], me.fqid)


class FollowingAndFollowersAPITests(APITestCase):
    def test_following_list_requires_auth_and_only_self(self):
        """Test that following list requires auth and only self."""
        me = _create_author(username="me", display_name="Me")
        other = _create_author(username="other", display_name="Other")

        resp = self.client.get(f"/api/authors/{me.id}/following")
        self.assertEqual(resp.status_code, 401)

        self.client.force_authenticate(user=other)
        resp = self.client.get(f"/api/authors/{me.id}/following")
        self.assertEqual(resp.status_code, 401)

    def test_following_list_returns_accepted_and_resolves_remote_stubs(self):
        """Test that following list returns accepted and resolves remote stubs."""
        me = _create_author(username="me", display_name="Me")
        local_target = _create_author(username="t1", display_name="Target")
        remote_fqid = "https://remote.example/api/authors/11111111-1111-1111-1111-111111111111"

        Follow.objects.create(
            follower_fqid=me.fqid, following_fqid=local_target.fqid, accepted=True
        )
        Follow.objects.create(
            follower_fqid=me.fqid, following_fqid=remote_fqid, accepted=True
        )

        self.client.force_authenticate(user=me)
        resp = self.client.get(f"/api/authors/{me.id}/following?size=10")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "following")
        self.assertEqual(resp.data["count"], 2)
        ids = {a.get("id") for a in resp.data["following"]}
        self.assertIn(local_target.fqid, ids)
        self.assertIn(remote_fqid, ids)
        remote_obj = next(
            a for a in resp.data["following"] if a.get("id") == remote_fqid)
        self.assertEqual(remote_obj.get("type"), "author")

    def test_following_detail_put_creates_pending_and_is_idempotent(self):
        """Test that following detail put creates pending and is idempotent."""
        me = _create_author(username="me", display_name="Me")
        target = _create_author(username="target", display_name="Target")
        target_encoded = quote(target.fqid, safe="")

        url = f"/api/authors/{me.id}/following/{target_encoded}"

        self.client.force_authenticate(user=me)
        resp = self.client.put(url, {}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            Follow.objects.filter(
                follower_fqid=me.fqid, following_fqid=target.fqid, accepted=False
            ).exists()
        )

        resp = self.client.put(url, {}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_following_detail_get_404_until_accepted_then_200(self):
        """Test that following detail get 404 until accepted then 200."""
        me = _create_author(username="me", display_name="Me")
        target = _create_author(username="target", display_name="Target")
        target_encoded = quote(target.fqid, safe="")

        Follow.objects.create(
            follower_fqid=me.fqid, following_fqid=target.fqid, accepted=False
        )

        self.client.force_authenticate(user=me)
        url = f"/api/authors/{me.id}/following/{target_encoded}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

        Follow.objects.filter(
            follower_fqid=me.fqid, following_fqid=target.fqid
        ).update(accepted=True)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], target.fqid)

    def test_following_detail_delete_unfollows(self):
        """Test that following detail delete unfollows."""
        me = _create_author(username="me", display_name="Me")
        target = _create_author(username="target", display_name="Target")
        target_encoded = quote(target.fqid, safe="")
        Follow.objects.create(
            follower_fqid=me.fqid, following_fqid=target.fqid, accepted=True
        )

        self.client.force_authenticate(user=me)
        url = f"/api/authors/{me.id}/following/{target_encoded}"
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(
            Follow.objects.filter(
                follower_fqid=me.fqid, following_fqid=target.fqid
            ).exists()
        )

    def test_followers_list_and_detail_get_do_not_require_auth(self):
        """Test that followers list and detail get do not require auth."""
        me = _create_author(username="me", display_name="Me")
        follower = _create_author(username="f", display_name="Follower")
        Follow.objects.create(
            follower_fqid=follower.fqid, following_fqid=me.fqid, accepted=True
        )
        viewer = _create_author(username="viewer5", display_name="Viewer 5", approved=True)
        self.client.force_authenticate(user=viewer)

        resp = self.client.get(f"/api/authors/{me.id}/followers")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "followers")
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["followers"][0]["id"], follower.fqid)

        encoded = quote(follower.fqid, safe="")
        resp = self.client.get(f"/api/authors/{me.id}/followers/{encoded}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], follower.fqid)

    @patch("nodes.remote.sync_remote_authors_for_node")
    def test_author_list_uses_cached_remote_authors_without_refreshing(self, sync_mock):
        """Test that author list uses cached remote authors without refreshing."""
        viewer = _create_author(username="viewer_remote", display_name="Viewer")
        self.client.login(username="viewer_remote", password="pw123456!")

        node = Node.objects.create(
            base_url="https://remote.example/api/",
            username="remote-user",
            password="remote-pass",
            active=True,
        )
        RemoteAuthor.objects.update_or_create(
            fqid="https://remote.example/api/authors/123",
            defaults={
                "node": node,
                "display_name": "Remote Cached Author",
                "username": "remote_author",
                "host": "https://remote.example/",
                "github": "",
                "profile_image": "",
                "raw": {"id": "https://remote.example/api/authors/123"},
            },
        )

        response = self.client.get("/authors/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Remote Cached Author")
        sync_mock.assert_not_called()

    def test_follower_detail_put_accept_requires_auth_and_pending_request(self):
        """Test that follower detail put accept requires auth and pending request."""
        me = _create_author(username="me", display_name="Me")
        follower = _create_author(username="f", display_name="Follower")
        encoded = quote(follower.fqid, safe="")
        url = f"/api/authors/{me.id}/followers/{encoded}"

        # No request exists
        self.client.force_authenticate(user=me)
        resp = self.client.put(url, {}, format="json")
        self.assertEqual(resp.status_code, 404)

        Follow.objects.create(
            follower_fqid=follower.fqid, following_fqid=me.fqid, accepted=False
        )
        resp = self.client.put(url, {}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], follower.fqid)
        self.assertTrue(
            Follow.objects.get(
                follower_fqid=follower.fqid, following_fqid=me.fqid
            ).accepted
        )

    def test_follower_detail_delete_requires_auth(self):
        """Test that follower detail delete requires auth."""
        me = _create_author(username="me", display_name="Me")
        follower = _create_author(username="f", display_name="Follower")
        Follow.objects.create(
            follower_fqid=follower.fqid, following_fqid=me.fqid, accepted=True
        )
        encoded = quote(follower.fqid, safe="")
        url = f"/api/authors/{me.id}/followers/{encoded}"

        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 401)

        self.client.force_authenticate(user=me)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(
            Follow.objects.filter(
                follower_fqid=follower.fqid, following_fqid=me.fqid
            ).exists()
        )


class FollowRequestsAndInboxAPITests(APITestCase):
    def _basic_auth_header(self):
        """Execute basic auth header."""
        username = "remote-node"
        password = "remote-pass-123!"
        Node.objects.create(
            base_url="https://remote.example/api/",
            username=username,
            password=password,
        )

        token = base64.b64encode(
            f"{username}:{password}".encode("utf-8")).decode("utf-8")
        return {"HTTP_AUTHORIZATION": f"Basic {token}"}

    def test_follow_requests_requires_auth_as_self(self):
        """Test that follow requests requires auth as self."""
        me = _create_author(username="me", display_name="Me")
        follower = _create_author(username="f", display_name="Follower")
        Follow.objects.create(
            follower_fqid=follower.fqid, following_fqid=me.fqid, accepted=False
        )

        resp = self.client.get(f"/api/authors/{me.id}/follow_requests")
        self.assertEqual(resp.status_code, 401)

        self.client.force_authenticate(user=me)
        resp = self.client.get(f"/api/authors/{me.id}/follow_requests")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "follow_requests")
        self.assertEqual(len(resp.data["follow_requests"]), 1)
        req = resp.data["follow_requests"][0]
        self.assertEqual(req["type"], "follow")
        self.assertEqual(req["actor"]["id"], follower.fqid)
        self.assertEqual(req["object"]["id"], me.fqid)

    def test_inbox_post_creates_pending_follow_and_is_idempotent(self):
        """Test that inbox post creates pending follow and is idempotent."""
        me = _create_author(username="me", display_name="Me")
        remote_actor = f"https://remote.example/api/authors/{uuid.uuid4()}"

        payload = {
            "type": "follow",
            "status": "REQUESTED",
            "summary": "x wants to follow y",
            "actor": {"type": "author", "id": remote_actor},
            "object": {"type": "author", "id": me.fqid},
        }

        url = f"/api/authors/{me.id}/inbox"
        auth_headers = self._basic_auth_header()

        resp = self.client.post(url, payload, format="json", **auth_headers)
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            Follow.objects.filter(
                follower_fqid=remote_actor, following_fqid=me.fqid, accepted=False
            ).exists()
        )

        resp = self.client.post(url, payload, format="json", **auth_headers)
        self.assertEqual(resp.status_code, 200)

    def test_inbox_post_validates_type_and_actor_id(self):
        """Test that inbox post validates type and actor id."""
        me = _create_author(username="me", display_name="Me")
        url = f"/api/authors/{me.id}/inbox"
        auth_headers = self._basic_auth_header()

        resp = self.client.post(
            url, {"type": "post"}, format="json", **auth_headers)
        self.assertEqual(resp.status_code, 400)

        resp = self.client.post(
            url,
            {"type": "follow", "actor": {"type": "author"}},
            format="json",
            **auth_headers,
        )
        self.assertEqual(resp.status_code, 400)

        resp = self.client.post(
            url,
            {
                "type": "follow",
                "status": "MAYBE",
                "actor": {"type": "author", "id": "https://remote.example/api/authors/x"},
            },
            format="json",
            **auth_headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_inbox_post_follow_status_accepted_marks_local_follow_accepted(self):
        """Test that inbox post follow status accepted marks local follow accepted."""
        me = _create_author(username="me", display_name="Me")
        remote_actor = f"https://remote.example/api/authors/{uuid.uuid4()}"
        Follow.objects.create(
            follower_fqid=me.fqid,
            following_fqid=remote_actor,
            accepted=False,
        )

        resp = self.client.post(
            f"/api/authors/{me.id}/inbox",
            {
                "type": "follow",
                "status": "ACCEPTED",
                "actor": {"type": "author", "id": me.fqid},
                "object": {"type": "author", "id": remote_actor},
            },
            format="json",
            **self._basic_auth_header(),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            Follow.objects.get(
                follower_fqid=me.fqid,
                following_fqid=remote_actor,
            ).accepted
        )

    def test_inbox_post_follow_status_rejected_removes_local_follow(self):
        """Test that inbox post follow status rejected removes local follow."""
        me = _create_author(username="me", display_name="Me")
        remote_actor = f"https://remote.example/api/authors/{uuid.uuid4()}"
        Follow.objects.create(
            follower_fqid=me.fqid,
            following_fqid=remote_actor,
            accepted=True,
        )

        resp = self.client.post(
            f"/api/authors/{me.id}/inbox",
            {
                "type": "follow",
                "status": "REJECTED",
                "actor": {"type": "author", "id": me.fqid},
                "object": {"type": "author", "id": remote_actor},
            },
            format="json",
            **self._basic_auth_header(),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            Follow.objects.filter(
                follower_fqid=me.fqid,
                following_fqid=remote_actor,
            ).exists()
        )

    def test_inbox_post_author_upserts_remote_author_without_creating_inbox_item(self):
        """Test that inbox post author upserts remote author without creating inbox item."""
        me = _create_author(username="me", display_name="Me")
        url = f"/api/authors/{me.id}/inbox"
        auth_headers = self._basic_auth_header()
        remote_author_fqid = "https://remote.example/api/authors/123"

        resp = self.client.post(
            url,
            {
                "type": "author",
                "id": remote_author_fqid,
                "displayName": "Remote Author",
                "username": "remote_author",
                "host": "https://remote.example/",
            },
            format="json",
            **auth_headers,
        )

        self.assertEqual(resp.status_code, 201)
        remote_author = RemoteAuthor.objects.get(fqid=remote_author_fqid)
        self.assertEqual(remote_author.display_name, "Remote Author")
        self.assertEqual(remote_author.node.base_url, "https://remote.example/api")
        self.assertFalse(InboxItem.objects.filter(author=me, type="author").exists())


class ProfileEditViewTests(TestCase):
    """
    Browser-view tests for the profile-edit form (no REST API).
    """

    def setUp(self):
        """Execute setUp."""
        self.user = _create_author(username="me", display_name="Me")
        self.client.login(username="me", password="pw123456!")

    def test_login_required(self):
        """Anonymous users are redirected to the login page."""
        self.client.logout()
        resp = self.client.get("/profile/edit/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_get_loads_form(self):
        """Authenticated user sees the profile edit page."""
        resp = self.client.get("/profile/edit/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Display name")

    def test_post_saves_changes(self):
        """Submitting valid data updates the author's profile."""
        resp = self.client.post("/profile/edit/", {
            "display_name": "New Name",
            "description": "A bio",
            "profile_image": "https://example.com/me.png",
            "github": "https://github.com/newuser",
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "New Name")
        self.assertEqual(self.user.description, "A bio")
        self.assertEqual(self.user.profile_image, "https://example.com/me.png")
        self.assertEqual(self.user.github, "https://github.com/newuser")

    def test_post_rejects_invalid_url(self):
        """An invalid URL in profile_image keeps the user on the form."""
        resp = self.client.post("/profile/edit/", {
            "display_name": "Name",
            "description": "",
            "profile_image": "not-a-url",
            "github": "",
        })
        # re-renders the form with errors
        self.assertEqual(resp.status_code, 200)


class FollowApprovalTests(TestCase):
    """Tests for the follow request approval flow."""

    def test_local_follow_creates_pending_request(self):
        """Following via the UI creates a pending (not auto-accepted) follow."""
        me = _create_author(username="me", display_name="Me")
        other = _create_author(username="other", display_name="Other")
        self.client.login(username="me", password="pw123456!")
        resp = self.client.post(f"/authors/{other.id}/follow/")
        self.assertEqual(resp.status_code, 302)
        follow = Follow.objects.get(
            follower_fqid=me.fqid, following_fqid=other.fqid)
        self.assertFalse(follow.accepted)

    def test_approve_follow_request(self):
        """Approving a pending follow sets accepted=True."""
        me = _create_author(username="me", display_name="Me")
        requester = _create_author(username="req", display_name="Requester")
        Follow.objects.create(
            follower_fqid=requester.fqid, following_fqid=me.fqid, accepted=False,
        )
        self.client.login(username="me", password="pw123456!")
        resp = self.client.post(f"/authors/{requester.id}/approve/")
        self.assertEqual(resp.status_code, 302)
        follow = Follow.objects.get(
            follower_fqid=requester.fqid, following_fqid=me.fqid)
        self.assertTrue(follow.accepted)

    def test_deny_follow_request(self):
        """Denying a pending follow deletes it."""
        me = _create_author(username="me", display_name="Me")
        requester = _create_author(username="req", display_name="Requester")
        Follow.objects.create(
            follower_fqid=requester.fqid, following_fqid=me.fqid, accepted=False,
        )
        self.client.login(username="me", password="pw123456!")
        resp = self.client.post(f"/authors/{requester.id}/deny/")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            Follow.objects.filter(
                follower_fqid=requester.fqid, following_fqid=me.fqid).exists()
        )

    @patch("authors.views.send_follow_to_inbox")
    def test_approve_follow_request_notifies_remote_node_when_requester_author_row_is_remote(self, send_follow_mock):
        """Test that approve follow request notifies remote node when requester author row is remote."""
        me = _create_author(username="me", display_name="Me")
        remote_requester = Author.objects.create_user(
            username="remote-req",
            password="pw123456!",
            display_name="Remote Requester",
            host="https://remote.example/api/",
            fqid="https://remote.example/api/authors/remote-req",
        )
        remote_requester.approved = True
        remote_requester.save()
        node = Node.objects.create(
            base_url="https://remote.example/api/",
            username="remote-user",
            password="remote-pass",
            active=True,
        )
        Follow.objects.create(
            follower_fqid=remote_requester.fqid,
            following_fqid=me.fqid,
            accepted=False,
        )

        self.client.login(username="me", password="pw123456!")
        resp = self.client.post(f"/authors/{remote_requester.id}/approve/")

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Follow.objects.get(
                follower_fqid=remote_requester.fqid,
                following_fqid=me.fqid,
            ).accepted
        )
        send_follow_mock.assert_called_once_with(
            node,
            remote_requester.fqid,
            me.fqid,
            follow_status="ACCEPTED",
        )

    @patch("authors.views.send_follow_to_inbox")
    def test_deny_follow_request_notifies_remote_node_when_requester_author_row_is_remote(self, send_follow_mock):
        """Test that deny follow request notifies remote node when requester author row is remote."""
        me = _create_author(username="me", display_name="Me")
        remote_requester = Author.objects.create_user(
            username="remote-deny",
            password="pw123456!",
            display_name="Remote Deny",
            host="https://remote.example/api/",
            fqid="https://remote.example/api/authors/remote-deny",
        )
        remote_requester.approved = True
        remote_requester.save()
        node = Node.objects.create(
            base_url="https://remote.example/api/",
            username="remote-user",
            password="remote-pass",
            active=True,
        )
        Follow.objects.create(
            follower_fqid=remote_requester.fqid,
            following_fqid=me.fqid,
            accepted=False,
        )

        self.client.login(username="me", password="pw123456!")
        resp = self.client.post(f"/authors/{remote_requester.id}/deny/")

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            Follow.objects.filter(
                follower_fqid=remote_requester.fqid,
                following_fqid=me.fqid,
            ).exists()
        )
        send_follow_mock.assert_called_once_with(
            node,
            remote_requester.fqid,
            me.fqid,
            follow_status="REJECTED",
        )

    def test_follow_requests_page_uses_remote_actions_for_remote_author_rows(self):
        """Test that follow requests page uses remote actions for remote author rows."""
        me = _create_author(username="me", display_name="Me")
        remote_requester = Author.objects.create_user(
            username="remote-page",
            password="pw123456!",
            display_name="Remote Page",
            host="https://remote.example/api/",
            fqid="https://remote.example/api/authors/remote-page",
        )
        remote_requester.approved = True
        remote_requester.save()
        Follow.objects.create(
            follower_fqid=remote_requester.fqid,
            following_fqid=me.fqid,
            accepted=False,
        )

        self.client.login(username="me", password="pw123456!")
        resp = self.client.get("/profile/follow-requests/")

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'action="/authors/remote-approve/"')
        self.assertContains(resp, 'action="/authors/remote-deny/"')
        self.assertContains(
            resp,
            f'name="follower_fqid" value="{remote_requester.fqid}"',
            html=False,
        )


class NodeAdminApprovalTests(TestCase):
    def test_new_user_registration_is_unapproved(self):
        """Test that new registrations default to approved=False."""
        resp = self.client.post("/accounts/register/", {
            "username": "newuser",
            "display_name": "New User",
            "password1": "pw123456!",
            "password2": "pw123456!",
        })
        # Check that user exists in the database but is NOT approved
        user = Author.objects.get(username="newuser")
        self.assertFalse(user.approved)

    def test_unapproved_user_cannot_login(self):
        """Test that an unapproved user gets an error on login."""
        # Force-create an unapproved user
        _create_author(username="unapproved",
                       display_name="Unapproved", approved=False)

        resp = self.client.post("/accounts/login/", {
            "username": "unapproved",
            "password": "pw123456!"
        })

        # Login should fail and return the login page with the exact error message
        self.assertContains(
            resp, "Your account is currently pending admin approval.")
        # Verify the session does not contain a logged-in user ID
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_approved_user_can_login(self):
        """Test that an approved user can log in successfully."""
        # Force-create an approved user
        _create_author(username="approved",
                       display_name="Approved", approved=True)

        resp = self.client.post("/accounts/login/", {
            "username": "approved",
            "password": "pw123456!"
        })

        # Should successfully redirect to the stream
        self.assertRedirects(resp, "/stream/", fetch_redirect_response=False)
        self.assertIn('_auth_user_id', self.client.session)


class StaffAuthorManagementTests(TestCase):
    def setUp(self):
        """Execute setUp."""
        self.staff = _create_author(
            username="staff", display_name="Staff", approved=True)
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.user = _create_author(
            username="u1", display_name="User One", approved=False)
        self.client.login(username="staff", password="pw123456!")

    def test_authors_page_shows_admin_badge_for_staff(self):
        """Test that authors page shows admin badge for staff."""
        resp = self.client.get("/authors/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ADMIN")
        self.assertContains(resp, "Pending Signups")
        self.assertNotContains(resp, "Author Management")
        self.assertContains(resp, "Reject")

    def test_approve_signup(self):
        """Test that approve signup."""
        resp = self.client.post(f"/authors/{self.user.id}/approve-signup/")
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.approved)

    def test_reject_signup(self):
        """Test that reject signup."""
        reject_user = _create_author(
            username="u2", display_name="User Two", approved=False)
        resp = self.client.post(f"/authors/{reject_user.id}/reject-signup/")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Author.objects.filter(pk=reject_user.id).exists())

    def test_toggle_staff_and_active(self):
        """Test that toggle staff and active."""
        resp = self.client.post(f"/authors/{self.user.id}/toggle-staff/")
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staff)

        resp = self.client.post(f"/authors/{self.user.id}/toggle-active/")
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_non_staff_cannot_use_admin_actions(self):
        """Test that non staff cannot use admin actions."""
        self.client.logout()
        normal = _create_author(
            username="normal", display_name="Normal", approved=True)
        self.client.login(username="normal", password="pw123456!")
        resp = self.client.post(f"/authors/{self.user.id}/approve-signup/")
        self.assertEqual(resp.status_code, 404)
