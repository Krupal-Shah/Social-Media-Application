from __future__ import annotations

import uuid
from urllib.parse import quote

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APITestCase

from authors.models import Author
from social.models import Follow


def _create_author(*, username: str, display_name: str, approved: bool = True) -> Author:
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
		_create_author(username="a1", display_name="Alice", approved=True)
		_create_author(username="a2", display_name="Bob", approved=True)
		_create_author(username="a3", display_name="Charlie", approved=False)

		resp = self.client.get("/api/authors/?size=1&page=2")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["type"], "authors")
		self.assertEqual(resp.data["count"], 2)
		self.assertEqual(resp.data["size"], 1)
		self.assertEqual(resp.data["page_number"], 2)
		self.assertEqual(len(resp.data["authors"]), 1)

	def test_author_list_size_is_clamped_to_max(self):
		for i in range(12):
			_create_author(username=f"u{i}", display_name=f"User {i}", approved=True)

		resp = self.client.get("/api/authors/?size=500")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["size"], 50)

	def test_author_detail_get(self):
		me = _create_author(username="me", display_name="Me", approved=True)
		resp = self.client.get(f"/api/authors/{me.id}/")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["type"], "author")
		self.assertEqual(resp.data["displayName"], "Me")
		self.assertEqual(resp.data["id"], me.fqid)

	def test_author_detail_put_requires_self(self):
		me = _create_author(username="me", display_name="Me", approved=True)
		other = _create_author(username="other", display_name="Other", approved=True)

		payload = {
			"displayName": "New Name",
			"github": "https://github.com/example",
			"profileImage": "https://example.com/me.png",
			"description": "Hello",
		}

		# Not authenticated
		resp = self.client.put(f"/api/authors/{me.id}/", payload, format="json")
		self.assertEqual(resp.status_code, 403)

		# Authenticated as someone else
		self.client.force_authenticate(user=other)
		resp = self.client.put(f"/api/authors/{me.id}/", payload, format="json")
		self.assertEqual(resp.status_code, 403)

		# Authenticated as self
		self.client.force_authenticate(user=me)
		resp = self.client.put(f"/api/authors/{me.id}/", payload, format="json")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["displayName"], "New Name")

		me.refresh_from_db()
		self.assertEqual(me.display_name, "New Name")
		self.assertEqual(me.github, "https://github.com/example")
		self.assertEqual(me.profile_image, "https://example.com/me.png")
		self.assertEqual(me.description, "Hello")

	def test_author_by_fqid_get_percent_encoded(self):
		me = _create_author(username="me", display_name="Me", approved=True)
		encoded = quote(me.fqid, safe="")
		resp = self.client.get(f"/api/authors/{encoded}")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["id"], me.fqid)


class FollowingAndFollowersAPITests(APITestCase):
	def test_following_list_requires_auth_and_only_self(self):
		me = _create_author(username="me", display_name="Me")
		other = _create_author(username="other", display_name="Other")

		resp = self.client.get(f"/api/authors/{me.id}/following")
		self.assertEqual(resp.status_code, 401)

		self.client.force_authenticate(user=other)
		resp = self.client.get(f"/api/authors/{me.id}/following")
		self.assertEqual(resp.status_code, 401)

	def test_following_list_returns_accepted_and_resolves_remote_stubs(self):
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
		remote_obj = next(a for a in resp.data["following"] if a.get("id") == remote_fqid)
		self.assertEqual(remote_obj.get("type"), "author")

	def test_following_detail_put_creates_pending_and_is_idempotent(self):
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
		me = _create_author(username="me", display_name="Me")
		follower = _create_author(username="f", display_name="Follower")
		Follow.objects.create(
			follower_fqid=follower.fqid, following_fqid=me.fqid, accepted=True
		)

		resp = self.client.get(f"/api/authors/{me.id}/followers")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["type"], "followers")
		self.assertEqual(resp.data["count"], 1)
		self.assertEqual(resp.data["followers"][0]["id"], follower.fqid)

		encoded = quote(follower.fqid, safe="")
		resp = self.client.get(f"/api/authors/{me.id}/followers/{encoded}")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["id"], follower.fqid)

	def test_follower_detail_put_accept_requires_auth_and_pending_request(self):
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
	def test_follow_requests_requires_auth_as_self(self):
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
		me = _create_author(username="me", display_name="Me")
		remote_actor = f"https://remote.example/api/authors/{uuid.uuid4()}"

		payload = {
			"type": "follow",
			"summary": "x wants to follow y",
			"actor": {"type": "author", "id": remote_actor},
			"object": {"type": "author", "id": me.fqid},
		}

		url = f"/api/authors/{me.id}/inbox"
		resp = self.client.post(url, payload, format="json")
		self.assertEqual(resp.status_code, 201)
		self.assertTrue(
			Follow.objects.filter(
				follower_fqid=remote_actor, following_fqid=me.fqid, accepted=False
			).exists()
		)

		resp = self.client.post(url, payload, format="json")
		self.assertEqual(resp.status_code, 200)

	def test_inbox_post_validates_type_and_actor_id(self):
		me = _create_author(username="me", display_name="Me")
		url = f"/api/authors/{me.id}/inbox"

		resp = self.client.post(url, {"type": "post"}, format="json")
		self.assertEqual(resp.status_code, 400)

		resp = self.client.post(
			url,
			{"type": "follow", "actor": {"type": "author"}},
			format="json",
		)
		self.assertEqual(resp.status_code, 400)


class ProfileEditViewTests(TestCase):
    """
    Browser-view tests for the profile-edit form (no REST API).
    """

    def setUp(self):
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
        self.assertEqual(resp.status_code, 200)  # re-renders the form with errors


class FollowApprovalTests(TestCase):
    """Tests for the follow request approval flow."""

    def test_local_follow_creates_pending_request(self):
        """Following via the UI creates a pending (not auto-accepted) follow."""
        me = _create_author(username="me", display_name="Me")
        other = _create_author(username="other", display_name="Other")
        self.client.login(username="me", password="pw123456!")
        resp = self.client.post(f"/authors/{other.id}/follow/")
        self.assertEqual(resp.status_code, 302)
        follow = Follow.objects.get(follower_fqid=me.fqid, following_fqid=other.fqid)
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
        follow = Follow.objects.get(follower_fqid=requester.fqid, following_fqid=me.fqid)
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
            Follow.objects.filter(follower_fqid=requester.fqid, following_fqid=me.fqid).exists()
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
        _create_author(username="unapproved", display_name="Unapproved", approved=False)
        
        resp = self.client.post("/accounts/login/", {
            "username": "unapproved",
            "password": "pw123456!"
        })
        
        # Login should fail and return the login page with the exact error message
        self.assertContains(resp, "Your account is currently pending admin approval.")
        # Verify the session does not contain a logged-in user ID
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_approved_user_can_login(self):
        """Test that an approved user can log in successfully."""
        # Force-create an approved user
        _create_author(username="approved", display_name="Approved", approved=True)
        
        resp = self.client.post("/accounts/login/", {
            "username": "approved",
            "password": "pw123456!"
        })
        
        # Should successfully redirect to the stream
        self.assertRedirects(resp, "/stream/", fetch_redirect_response=False)
        self.assertIn('_auth_user_id', self.client.session)