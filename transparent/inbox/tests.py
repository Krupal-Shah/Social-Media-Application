"""Test cases for the inbox app."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from django.test import TestCase

from authors.models import Author
from inbox.adapters import normalize_payload
from inbox.models import InboxItem
from nodes.models import Node


class InboxItemModelTests(TestCase):
	def test_can_store_inbox_item_payload(self):
		"""Test that can store inbox item payload."""
		author = Author.objects.create_user(
			username="a",
			password="pw123456!",
			display_name="Author",
			host=getattr(settings, "SERVICE_URL", "http://testserver/api/"),
			fqid="",
		)
		author.approved = True
		author.save()

		item = InboxItem.objects.create(
			author=author,
			type="follow",
			payload={"hello": "world"},
		)
		item.refresh_from_db()
		self.assertEqual(item.type, "follow")
		self.assertEqual(item.payload, {"hello": "world"})


class InboxAdapterTests(TestCase):
	def test_mintcream_entry_payload_is_normalized(self):
		"""Test that mintcream entry payload is normalized."""
		node = Node.objects.create(
			base_url="https://socialdistribution-darius-778c33d8611c.herokuapp.com/api/",
			username="mintcream_node",
			password="secret",
		)
		payload = {
			"type": "entry",
			"title": "Hello from Node A",
			"id": "https://node-a.example.com/api/authors/11111111-1111-1111-1111-111111111111/entries/22222222-2222-2222-2222-222222222222",
			"contentType": "text/plain",
			"content": "This is a federated entry.",
			"author": {
				"type": "author",
				"id": "https://node-a.example.com/api/authors/11111111-1111-1111-1111-111111111111",
				"host": "https://node-a.example.com/api/",
				"displayName": "alice",
			},
			"visibility": "PUBLIC",
		}

		normalized, slug = normalize_payload(node, HttpRequest(), payload)

		self.assertEqual(slug, "mintcream")
		self.assertEqual(normalized["type"], "entry")
		self.assertEqual(normalized["contentType"], "text/plain")
		self.assertEqual(normalized["content_type"], "text/plain")
		self.assertEqual(normalized["author"]["displayName"], "alice")

	def test_mintcream_follow_payload_defaults_requested_status(self):
		"""Test that mintcream follow payload defaults requested status."""
		node = Node.objects.create(
			base_url="https://socialdistribution-darius-778c33d8611c.herokuapp.com/api/",
			username="mintcream_node_2",
			password="secret",
		)
		payload = {
			"type": "follow",
			"summary": "alice wants to follow bob",
			"actor": {
				"id": "https://node-a.example.com/api/authors/11111111-1111-1111-1111-111111111111",
				"host": "https://node-a.example.com/api/",
				"displayName": "alice",
			},
			"object": {
				"id": "https://remote-node.example.com/api/authors/33333333-3333-3333-3333-333333333333",
				"host": "https://remote-node.example.com/api/",
				"displayName": "bob",
			},
		}

		normalized, slug = normalize_payload(node, HttpRequest(), payload)

		self.assertEqual(slug, "mintcream")
		self.assertEqual(normalized["status"], "REQUESTED")
		self.assertEqual(normalized["actor"]["displayName"], "alice")
		self.assertEqual(normalized["object"]["displayName"], "bob")

	def test_papayawhip_entry_payload_is_normalized(self):
		"""Test that papayawhip entry payload is normalized."""
		node = Node.objects.create(
			base_url="https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/",
			username="papayawhip_node",
			password="secret",
		)
		payload = {
			"type": "entry",
			"title": "Hello from Papayawhip",
			"id": "https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/authors/404967b7-edc5-496f-b581-f28ac3b51b9b/entries/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
			"content_type": "text/plain",
			"content": "Body text here.",
			"contentType": "text/plain",
			"ContentType": "text/plain",
			"visibility": "PUBLIC",
			"author": {
				"type": "author",
				"id": "https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/authors/404967b7-edc5-496f-b581-f28ac3b51b9b",
				"host": "https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/",
				"display_name": "Admin",
				"displayName": "Admin",
				"github": "null",
				"profile_image": "null",
				"profileImage": "null"
			},
		}

		normalized, slug = normalize_payload(node, HttpRequest(), payload)

		self.assertEqual(slug, "papayawhip")
		self.assertEqual(normalized["type"], "entry")
		self.assertEqual(normalized["content_type"], "text/plain")
		self.assertEqual(normalized["contentType"], "text/plain")
		self.assertEqual(normalized["author"]["displayName"], "Admin")
		self.assertNotIn("github", normalized["author"])
		self.assertNotIn("profileImage", normalized["author"])

	def test_papayawhip_post_alias_normalizes_to_entry(self):
		"""Test that papayawhip post alias normalizes to entry."""
		node = Node.objects.create(
			base_url="https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/",
			username="papayawhip_node_2",
			password="secret",
		)
		payload = {
			"type": "post",
			"id": "https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/authors/a/entries/b",
			"author": {
				"id": "https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/authors/a",
				"displayName": "Admin",
			},
			"content": "hello",
		}

		normalized, slug = normalize_payload(node, HttpRequest(), payload)

		self.assertEqual(slug, "papayawhip")
		self.assertEqual(normalized["type"], "entry")

	def test_steelblue_follow_requesting_status_normalizes_to_requested(self):
		"""Test that steelblue follow requesting status normalizes to requested."""
		node = Node.objects.create(
			base_url="https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/",
			username="steelblue_node",
			password="secret",
		)
		payload = {
			"id": "b91c88fa-8b68-45ff-a478-68c0809b6a46",
			"type": "follow",
			"status": "REQUESTING",
			"summary": "Borat wants to follow Alex Johnson",
			"actor": {
				"id": "https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/authors/742b2bdf-27fa-4e2f-96a0-14bf283a1a1a",
				"host": "https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/",
				"displayName": "Borat",
				"github": "Borat",
				"type": "author",
				"web": "https://steelblue-avg-user-app-322a36359cac.herokuapp.com/authors/742b2bdf-27fa-4e2f-96a0-14bf283a1a1a",
			},
			"object": {
				"id": "https://transparent-6dcb15dd6f71.herokuapp.com/api/authors/25a2d975-9243-4a3e-84d3-c85bcbe54d48",
				"host": "https://transparent-6dcb15dd6f71.herokuapp.com/api/",
				"displayName": "Alex Johnson",
				"type": "author",
				"web": "https://transparent-6dcb15dd6f71.herokuapp.com/authors/25a2d975-9243-4a3e-84d3-c85bcbe54d48",
			},
		}

		normalized, slug = normalize_payload(node, HttpRequest(), payload)

		self.assertEqual(slug, "steelblue")
		self.assertEqual(normalized["type"], "follow")
		self.assertEqual(normalized["status"], "REQUESTED")
		self.assertEqual(normalized["actor"]["displayName"], "Borat")
		self.assertEqual(normalized["object"]["displayName"], "Alex Johnson")

	def test_steelblue_entry_visibility_is_normalized(self):
		"""Test that steelblue entry visibility is normalized."""
		node = Node.objects.create(
			base_url="https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/",
			username="steelblue_node_entry",
			password="secret",
		)
		payload = {
			"type": "entry",
			"id": "https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/authors/6603d7e9-94d3-4f50-98f0-ccd9f4039118/entries/posts/2a779e9d-2aaf-45bd-87c3-6b8137e40eab",
			"title": "why test",
			"contentType": "text/plain",
			"content": "wwqed",
			"visibility": "FRIENDS ONLY",
			"author": {
				"id": "https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/authors/6603d7e9-94d3-4f50-98f0-ccd9f4039118",
				"host": "https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/",
				"displayName": "User3",
				"type": "author",
			},
		}

		normalized, slug = normalize_payload(node, HttpRequest(), payload)

		self.assertEqual(slug, "steelblue")
		self.assertEqual(normalized["type"], "entry")
		self.assertEqual(normalized["visibility"], "FRIENDS")

	def test_steelblue_entry_unlisted_visibility_is_preserved(self):
		"""Test that steelblue entry unlisted visibility is preserved."""
		node = Node.objects.create(
			base_url="https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/",
			username="steelblue_node_unlisted",
			password="secret",
		)
		payload = {
			"type": "entry",
			"id": "https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/authors/6603d7e9-94d3-4f50-98f0-ccd9f4039118/entries/posts/2a779e9d-2aaf-45bd-87c3-6b8137e40eab",
			"contentType": "text/plain",
			"content": "wwqed",
			"visibility": "UNLISTED",
			"author": {
				"id": "https://steelblue-avg-user-app-322a36359cac.herokuapp.com/api/authors/6603d7e9-94d3-4f50-98f0-ccd9f4039118",
				"displayName": "User3",
			},
		}

		normalized, slug = normalize_payload(node, HttpRequest(), payload)

		self.assertEqual(slug, "steelblue")
		self.assertEqual(normalized["visibility"], "UNLISTED")
