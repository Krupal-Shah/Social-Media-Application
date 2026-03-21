from __future__ import annotations

import base64
import uuid
from urllib.parse import quote

from django.conf import settings
from rest_framework.test import APITestCase

from authors.models import Author
from entries.models import Entry
from social.models import Follow
from django.core.files.uploadedfile import SimpleUploadedFile

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


def _create_entry(
	*,
	author: Author,
	title: str,
	visibility: str,
	content: str = "hello",
	content_type: str = "text/plain",
	description: str = "",
) -> Entry:
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
		resp = self.client.get(self.list_url + "?size=50")
		self.assertEqual(resp.status_code, 200)
		return [e["title"] for e in resp.data["src"]]

	def test_unauthenticated_sees_public_only(self):
		titles = self._list_titles()
		self.assertEqual(titles, ["pub"])  # newest first, but only one visible

	def test_authenticated_non_follower_sees_public_only(self):
		self.client.force_authenticate(user=self.viewer)
		titles = self._list_titles()
		self.assertEqual(titles, ["pub"])

	def test_authenticated_follower_sees_public_and_unlisted(self):
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
		self.client.force_authenticate(user=self.author)
		titles = self._list_titles()
		self.assertCountEqual(titles, ["pub", "unlisted", "friends"])
		self.assertNotIn("deleted", titles)

	def test_list_is_paginated_response_shape(self):
		resp = self.client.get(self.list_url)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["type"], "entries")
		self.assertIn("src", resp.data)


class EntriesCreateUpdateDeleteAPITests(APITestCase):
	def setUp(self):
		super().setUp()
		self.me = _create_author(username="me", display_name="Me")
		self.other = _create_author(username="other", display_name="Other")
		self.list_url = f"/api/authors/{self.me.id}/entries/"

	def test_create_requires_auth(self):
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

		self.assertTrue(Entry.objects.filter(author=self.me, title="t").exists())

	def test_put_requires_owner_and_full_payload(self):
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


class EntriesFQIDAndImageAPITests(APITestCase):
	def setUp(self):
		super().setUp()
		self.author = _create_author(username="author", display_name="Author")
		self.viewer = _create_author(username="viewer", display_name="Viewer")

	def test_entry_get_by_fqid(self):
		entry = _create_entry(author=self.author, title="t", visibility="PUBLIC")
		encoded = quote(entry.fqid, safe="")
		resp = self.client.get(f"/api/entries/{encoded}")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["id"], entry.fqid)

	def test_entry_image_by_serial_returns_decoded_bytes(self):
		raw = b"\x89PNG\r\n"  # small fake header
		b64 = base64.b64encode(raw).decode("utf-8")
		entry = _create_entry(
			author=self.author,
			title="img",
			visibility="PUBLIC",
			content=b64,
			content_type="image/png",
		)
		url = f"/api/authors/{self.author.id}/entries/{entry.id}/image"
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp["Content-Type"], "image/png")
		self.assertEqual(resp.content, raw)

	def test_entry_image_by_serial_404_for_non_image(self):
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
		raw = b"GIF89a"  # fake gif header
		b64 = base64.b64encode(raw).decode("utf-8")
		entry = _create_entry(
			author=self.author,
			title="img",
			visibility="PUBLIC",
			content=b64,
			content_type="image/gif",
		)
		encoded = quote(entry.fqid, safe="")
		resp = self.client.get(f"/api/entries/{encoded}/image")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp["Content-Type"], "image/gif")
		self.assertEqual(resp.content, raw)

	def test_entry_image_by_fqid_404_for_combined_image_text(self):
		raw = b"abcd"
		b64 = base64.b64encode(raw).decode("utf-8")
		entry = _create_entry(
			author=self.author,
			title="combo",
			visibility="PUBLIC",
			content=b64,
			content_type="image/png/text/plain",
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
		self.author = _create_author(username="author2", display_name="Author2")
		self.friend = _create_author(username="friend2", display_name="Friend2")
		self.follower = _create_author(username="follower2", display_name="Follower2")
		self.stranger = _create_author(username="stranger2", display_name="Stranger2")

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
		return {e["id"] for e in resp.data["src"]}

	def test_unauthenticated_sees_only_public(self):
		resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
		self.assertEqual(resp.status_code, 200)
		ids = self._get_entry_ids(resp)
		self.assertIn(self.public_entry.fqid, ids)
		self.assertNotIn(self.unlisted_entry.fqid, ids)
		self.assertNotIn(self.friends_entry.fqid, ids)
		self.assertNotIn(self.deleted_entry.fqid, ids)

	def test_stranger_sees_only_public(self):
		self.client.force_authenticate(user=self.stranger)
		resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
		self.assertEqual(resp.status_code, 200)
		ids = self._get_entry_ids(resp)
		self.assertIn(self.public_entry.fqid, ids)
		self.assertNotIn(self.unlisted_entry.fqid, ids)
		self.assertNotIn(self.friends_entry.fqid, ids)
		self.assertNotIn(self.deleted_entry.fqid, ids)

	def test_follower_sees_public_and_unlisted_not_friends(self):
		self.client.force_authenticate(user=self.follower)
		resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
		self.assertEqual(resp.status_code, 200)
		ids = self._get_entry_ids(resp)
		self.assertIn(self.public_entry.fqid, ids)
		self.assertIn(self.unlisted_entry.fqid, ids)
		self.assertNotIn(self.friends_entry.fqid, ids)
		self.assertNotIn(self.deleted_entry.fqid, ids)

	def test_friend_sees_public_unlisted_and_friends(self):
		self.client.force_authenticate(user=self.friend)
		resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
		self.assertEqual(resp.status_code, 200)
		ids = self._get_entry_ids(resp)
		self.assertIn(self.public_entry.fqid, ids)
		self.assertIn(self.unlisted_entry.fqid, ids)
		self.assertIn(self.friends_entry.fqid, ids)
		self.assertNotIn(self.deleted_entry.fqid, ids)

	def test_author_sees_all_except_deleted(self):
		self.client.force_authenticate(user=self.author)
		resp = self.client.get(f"/api/authors/{self.author.id}/entries/")
		self.assertEqual(resp.status_code, 200)
		ids = self._get_entry_ids(resp)
		self.assertIn(self.public_entry.fqid, ids)
		self.assertIn(self.unlisted_entry.fqid, ids)
		self.assertIn(self.friends_entry.fqid, ids)
		self.assertNotIn(self.deleted_entry.fqid, ids)

	def test_pending_follow_does_not_grant_unlisted_access(self):
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
		self.author = _create_author(username="author3", display_name="Author3")
		self.friend = _create_author(username="friend3", display_name="Friend3")
		self.stranger = _create_author(username="stranger3", display_name="Stranger3")

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
		resp = self.client.get(
			f"/api/authors/{self.author.id}/entries/{self.friends_entry.id}/"
		)
		self.assertEqual(resp.status_code, 404)

	def test_friends_entry_hidden_from_stranger(self):
		self.client.force_authenticate(user=self.stranger)
		resp = self.client.get(
			f"/api/authors/{self.author.id}/entries/{self.friends_entry.id}/"
		)
		self.assertEqual(resp.status_code, 404)

	def test_friends_entry_visible_to_friend(self):
		self.client.force_authenticate(user=self.friend)
		resp = self.client.get(
			f"/api/authors/{self.author.id}/entries/{self.friends_entry.id}/"
		)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["title"], "Friends Only")

	def test_friends_entry_visible_to_author(self):
		self.client.force_authenticate(user=self.author)
		resp = self.client.get(
			f"/api/authors/{self.author.id}/entries/{self.friends_entry.id}/"
		)
		self.assertEqual(resp.status_code, 200)
  
class ImageHostingTests(APITestCase):
    def setUp(self):
        super().setUp()
        # Using your internal helper function!
        self.author = _create_author(username="imguser", display_name="Img User", approved=True)
        # Log the user into the standard Django session
        self.client.login(username="imguser", password="pw123456!")

    def test_create_entry_with_image_saves_as_base64(self):
        """Test that uploaded physical images are converted to Base64 strings for local hosting."""
        # Create a tiny dummy GIF image in memory
        tiny_gif = b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x01\x00\x00"
        image_file = SimpleUploadedFile("test.gif", tiny_gif, content_type="image/gif")

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
        self.assertEqual(entry.content_type, "image/gif")
        
        # Base64 strings for GIFs always start with 'R0lGODlh'
        self.assertTrue(entry.content.startswith("R0lGODlh"))
        self.assertNotIn("test.gif", entry.content) # Proves it's raw encoded data, not a file path


class ExplorePageTests(APITestCase):
	def setUp(self):
		super().setUp()
		self.viewer = _create_author(username="viewer2", display_name="Viewer2")
		self.other = _create_author(username="other2", display_name="Other2")
		self.client.login(username="viewer2", password="pw123456!")

		_create_entry(author=self.other, title="Public Post", visibility="PUBLIC")
		_create_entry(author=self.other, title="Unlisted Post", visibility="UNLISTED")
		_create_entry(author=self.other, title="Friends Post", visibility="FRIENDS")
		_create_entry(author=self.other, title="Deleted Post", visibility="DELETED")

	def test_explore_requires_login(self):
		self.client.logout()
		resp = self.client.get("/explore/")
		self.assertEqual(resp.status_code, 302)
		self.assertIn("/accounts/login/", resp.url)

	def test_explore_shows_public_only(self):
		resp = self.client.get("/explore/")
		self.assertEqual(resp.status_code, 200)
		content = resp.content.decode("utf-8")
		self.assertIn("Public Post", content)
		self.assertNotIn("Unlisted Post", content)
		self.assertNotIn("Friends Post", content)
		self.assertNotIn("Deleted Post", content)