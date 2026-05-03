"""Test cases for the nodes app."""

import uuid
from unittest.mock import patch
from unittest.mock import Mock

from django.test import TestCase
from nodes.models import Node, RemoteAuthor
from authors.models import Author
from core.utils import normalize_api_base
from nodes.remote import _request_to_inbox, fetch_remote_authors, publish_local_author_to_nodes, send_follow_to_inbox
import requests


class NodeModelTests(TestCase):
    def test_can_create_node_and_defaults_active_true(self):
        """Test that can create node and defaults active true."""
        node = Node.objects.create(
            base_url="https://remote.example/api/",
            username="u",
            password="p",
        )
        self.assertTrue(node.active)

    def test_active_queryset_skips_blank_base_urls(self):
        """Test that active queryset skips blank base urls."""
        Node.objects.create(
            base_url="https://remote.example/api/",
            username="u",
            password="p",
            active=True,
        )
        Node.objects.create(
            base_url="https://inactive.example/api/",
            username="u2",
            password="p2",
            active=False,
        )
        blank_node = Node(
            base_url="",
            username="u3",
            password="p3",
            active=True,
        )
        blank_node.save(force_insert=True)

        self.assertIsNone(blank_node.base_url)
        self.assertEqual(Node.objects.active().count(), 1)

    @patch("nodes.remote.requests.get")
    def test_fetch_remote_authors_retries_without_auth_when_basic_auth_is_rejected(self, get_mock):
        """Test that fetch remote authors retries without auth when basic auth is rejected."""
        node = Node.objects.create(
            base_url="https://remote.example/api/",
            username="node-user",
            password="node-pass",
        )

        forbidden_response = Mock()
        forbidden_response.status_code = 403
        forbidden_response.raise_for_status.side_effect = requests.HTTPError(
            response=forbidden_response
        )

        ok_response = Mock()
        ok_response.status_code = 200
        ok_response.raise_for_status.return_value = None
        ok_response.json.return_value = {
            "authors": [
                {
                    "id": "https://remote.example/api/authors/123",
                    "displayName": "Remote Author",
                }
            ]
        }

        get_mock.side_effect = [forbidden_response, ok_response]

        result = fetch_remote_authors(node)

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["authors"]), 1)
        self.assertEqual(get_mock.call_count, 2)
        self.assertEqual(
            get_mock.call_args_list[0].kwargs["auth"], ("node-user", "node-pass"))
        self.assertIsNone(get_mock.call_args_list[1].kwargs["auth"])


class NodeAdminTests(TestCase):
    def setUp(self):
        """Execute setUp."""
        # Create a superuser (Node Admin) for our tests
        self.admin_user = Author.objects.create_user(
            username="nodeadmin",
            password="supersecretpassword",
            display_name="The Node Admin",
            host="http://testserver/api/"
        )
        self.admin_user.is_staff = True
        self.admin_user.is_superuser = True
        self.admin_user.save()

        # Log the admin in
        self.client.login(username="nodeadmin", password="supersecretpassword")

    def test_node_admin_page_loads(self):
        """Test that the Node admin list page loads successfully for an admin."""
        resp = self.client.get("/admin/nodes/node/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Select node to change")

    def test_admin_can_create_node_via_panel(self):
        """Test that an admin can create a remote node purely through the Django admin form."""
        resp = self.client.post("/admin/nodes/node/add/", {
            "base_url": "https://team-yoshi.herokuapp.com/api/",
            "username": "yoshi_user",
            "password": "yoshi_password",
            "active": "on",  # This is how HTML checkboxes send 'True'
        })

        # A successful form submission in Django Admin returns a 302 redirect back to the list
        self.assertEqual(resp.status_code, 302)

        # Verify it was actually saved to the database!
        self.assertTrue(
            Node.objects.filter(
                base_url=normalize_api_base(
                    "https://team-yoshi.herokuapp.com/api/")
            ).exists()
        )

    def test_non_admin_cannot_access_nodes(self):
        """Test that standard users are blocked from seeing the remote nodes."""
        # Log out the admin and log in a regular user
        self.client.logout()
        regular_user = Author.objects.create_user(
            username="regular",
            password="password123",
            display_name="Regular User",
            host="http://testserver/api/"
        )
        self.client.login(username="regular", password="password123")

        resp = self.client.get("/admin/nodes/node/")

        # Should redirect them to the admin login page because they lack staff status
        self.assertRedirects(
            resp, "/admin/login/?next=/admin/nodes/node/", fetch_redirect_response=False)

    @patch("nodes.views.sync_remote_authors_for_node")
    def test_nodes_add_runs_initial_remote_author_sync(self, sync_mock):
        """Test that nodes add runs initial remote author sync."""
        sync_mock.return_value = {
            "ok": True,
            "authors": [],
            "upserted": 2,
            "error": "",
            "status_code": 200,
            "url": "https://team-yoshi.herokuapp.com/api/authors/",
        }

        resp = self.client.post("/nodes/add/", {
            "base_url": "https://team-yoshi.herokuapp.com/api/",
            "username": "yoshi_user",
            "password": "yoshi_password",
        }, follow=True)

        self.assertEqual(resp.status_code, 200)
        node = Node.objects.get(
            base_url=normalize_api_base(
                "https://team-yoshi.herokuapp.com/api/")
        )
        sync_mock.assert_called_once_with(node)
        self.assertContains(
            resp, "Connected https://team-yoshi.herokuapp.com/api")


class NodeFederationPublishTests(TestCase):
    @patch("nodes.remote.requests.post")
    def test_request_to_inbox_uses_trailing_slash_and_enriched_entry_payload(self, post_mock):
        """Test that request to inbox uses trailing slash and enriched entry payload."""
        response = Mock()
        response.status_code = 201
        response.raise_for_status.return_value = None
        post_mock.return_value = response

        node = Node.objects.create(
            base_url="https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/",
            username="papaya-user",
            password="papaya-pass",
            active=True,
        )

        delivered = _request_to_inbox(
            node,
            "https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/authors/32df23b6-1ba6-48c0-b23c-f1d6aa42e64e",
            {
                "type": "entry",
                "id": "http://testserver/api/authors/111/entries/249",
                "title": "A Post",
                "description": "",
                "contentType": "text/plain",
                "content": "Content here",
                "visibility": "PUBLIC",
                "author": {
                    "type": "author",
                    "id": "http://testserver/api/authors/111",
                    "displayName": "Local Author",
                    "host": "http://testserver/api/",
                    "github": "",
                    "profileImage": "",
                },
            },
        )

        self.assertIsNotNone(delivered)
        self.assertTrue(post_mock.call_args.args[0].endswith("/inbox/"))
        sent_json = post_mock.call_args.kwargs["json"]
        self.assertEqual(sent_json["author"]["web"],
                         "http://testserver/authors/111")
        self.assertEqual(sent_json["web"],
                         "http://testserver/authors/111/entries/249")
        self.assertEqual(sent_json["content_type"], "text/plain")
        self.assertIn("comments", sent_json)
        self.assertIn("likes", sent_json)
        self.assertNotIn("github", sent_json["author"])
        self.assertNotIn("profileImage", sent_json["author"])

    @patch("nodes.remote._request_to_inbox")
    def test_publish_local_author_to_nodes_sends_once_per_active_node(self, request_mock):
        """Test that publish local author to nodes sends once per active node."""
        request_mock.return_value = object()
        author = Author.objects.create_user(
            username="local-author",
            password="pw123456!",
            display_name="Local Author",
            host="http://testserver/api/",
            fqid="",
        )
        author.approved = True
        author.save()

        node_one = Node.objects.create(
            base_url="https://remote-one.example/api/",
            username="node-one-user",
            password="node-one-pass",
            active=True,
        )
        node_two = Node.objects.create(
            base_url="https://remote-two.example/api/",
            username="node-two-user",
            password="node-two-pass",
            active=True,
        )
        inactive_node = Node.objects.create(
            base_url="https://remote-inactive.example/api/",
            username="inactive-user",
            password="inactive-pass",
            active=False,
        )

        RemoteAuthor.objects.create(
            node=node_one,
            fqid="https://remote-one.example/api/authors/111",
            display_name="Remote One A",
        )
        RemoteAuthor.objects.create(
            node=node_one,
            fqid="https://remote-one.example/api/authors/222",
            display_name="Remote One B",
        )
        RemoteAuthor.objects.create(
            node=node_two,
            fqid="https://remote-two.example/api/authors/333",
            display_name="Remote Two A",
        )
        RemoteAuthor.objects.create(
            node=inactive_node,
            fqid="https://remote-inactive.example/api/authors/444",
            display_name="Remote Inactive",
        )

        delivered = publish_local_author_to_nodes(author)

        self.assertEqual(delivered, 2)
        self.assertEqual(request_mock.call_count, 2)
        sent_recipients = {call.args[1]
                           for call in request_mock.call_args_list}
        self.assertSetEqual(
            sent_recipients,
            {
                "https://remote-one.example/api/authors/111",
                "https://remote-two.example/api/authors/333",
            },
        )

    @patch("nodes.remote._request_to_inbox")
    def test_send_follow_to_inbox_uses_expected_statuses(self, request_mock):
        """Test that send follow to inbox uses expected statuses."""
        request_mock.return_value = object()
        follower = Author.objects.create_user(
            username="follower",
            password="pw123456!",
            display_name="Follower",
            host="http://testserver/api/",
            fqid="",
        )
        follower.approved = True
        follower.save()
        followed = Author.objects.create_user(
            username="followed",
            password="pw123456!",
            display_name="Followed",
            host="http://testserver/api/",
            fqid="",
        )
        followed.approved = True
        followed.save()

        node = Node.objects.create(
            base_url="https://remote.example/api/",
            username="remote-user",
            password="remote-pass",
            active=True,
        )
        RemoteAuthor.objects.create(
            node=node,
            fqid="https://remote.example/api/authors/123",
            display_name="Remote Follower",
            host="https://remote.example/",
        )

        request_mock.reset_mock()
        delivered = send_follow_to_inbox(
            node,
            follower,
            "https://remote.example/api/authors/123",
            follow_status="REQUESTED",
        )
        self.assertTrue(delivered)
        self.assertEqual(
            request_mock.call_args.args[1],
            "https://remote.example/api/authors/123",
        )
        payload = request_mock.call_args.args[2]
        self.assertEqual(payload["type"], "follow")
        self.assertEqual(payload["status"], "REQUESTED")
        self.assertEqual(payload["summary"],
                         "Follower wants to follow Remote Follower")
        self.assertEqual(
            payload["actor"],
            {
                "id": follower.fqid,
                "web": follower.web,
                "host": "http://testserver/api/",
                "type": "author",
                "github": "",
                "displayName": "Follower",
            },
        )
        self.assertEqual(
            payload["object"],
            {
                "id": "https://remote.example/api/authors/123",
                "web": "https://remote.example/authors/123",
                "host": "https://remote.example/api/",
                "type": "author",
                "github": "",
                "displayName": "Remote Follower",
            },
        )
        uuid.UUID(payload["id"])

        request_mock.reset_mock()
        delivered = send_follow_to_inbox(
            node,
            "https://remote.example/api/authors/123",
            followed.fqid,
            follow_status="ACCEPTED",
        )
        self.assertTrue(delivered)
        self.assertEqual(
            request_mock.call_args.args[1],
            "https://remote.example/api/authors/123",
        )
        payload = request_mock.call_args.args[2]
        self.assertEqual(payload["status"], "ACCEPTED")
        self.assertEqual(
            payload["summary"],
            "Followed accepted Remote Follower's follow request",
        )
        self.assertEqual(
            payload["actor"],
            {
                "id": "https://remote.example/api/authors/123",
                "web": "https://remote.example/authors/123",
                "host": "https://remote.example/api/",
                "type": "author",
                "github": "",
                "displayName": "Remote Follower",
            },
        )
        self.assertEqual(
            payload["object"],
            {
                "id": followed.fqid,
                "web": followed.web,
                "host": "http://testserver/api/",
                "type": "author",
                "github": "",
                "displayName": "Followed",
            },
        )

        request_mock.reset_mock()
        delivered = send_follow_to_inbox(
            node,
            "https://remote.example/api/authors/123",
            followed.fqid,
            follow_status="REJECTED",
        )
        self.assertTrue(delivered)
        self.assertEqual(
            request_mock.call_args.args[1],
            "https://remote.example/api/authors/123",
        )
        payload = request_mock.call_args.args[2]
        self.assertEqual(payload["status"], "REJECTED")
        self.assertEqual(
            payload["summary"],
            "Followed rejected Remote Follower's follow request",
        )
        self.assertEqual(
            payload["actor"],
            {
                "id": "https://remote.example/api/authors/123",
                "web": "https://remote.example/authors/123",
                "host": "https://remote.example/api/",
                "type": "author",
                "github": "",
                "displayName": "Remote Follower",
            },
        )

        self.assertEqual(
            payload["object"],
            {
                "id": followed.fqid,
                "web": followed.web,
                "host": "http://testserver/api/",
                "type": "author",
                "github": "",
                "displayName": "Followed",
            },
        )

        request_mock.reset_mock()
        delivered = send_follow_to_inbox(
            node,
            follower,
            "https://remote.example/api/authors/123",
            follow_status="UNFOLLOW",
        )
        self.assertTrue(delivered)
        self.assertEqual(
            request_mock.call_args.args[1],
            "https://remote.example/api/authors/123",
        )
        payload = request_mock.call_args.args[2]
        self.assertEqual(payload["status"], "UNFOLLOW")
        self.assertEqual(payload["summary"],
                         "Follower no longer follows Remote Follower")
        self.assertEqual(
            payload["actor"],
            {
                "id": follower.fqid,
                "web": follower.web,
                "host": "http://testserver/api/",
                "type": "author",
                "github": "",
                "displayName": "Follower",
            },
        )
        self.assertEqual(
            payload["object"],
            {
                "id": "https://remote.example/api/authors/123",
                "web": "https://remote.example/authors/123",
                "host": "https://remote.example/api/",
                "type": "author",
                "github": "",
                "displayName": "Remote Follower",
            },
        )

    @patch("nodes.remote.requests.put")
    @patch("nodes.remote.requests.post")
    def test_request_to_inbox_prefers_post_for_entry_updates_on_compat_nodes(self, post_mock, put_mock):
        """Test that request to inbox prefers post for entry updates on compat nodes."""
        response = Mock()
        response.status_code = 201
        response.raise_for_status.return_value = None
        post_mock.return_value = response

        node = Node.objects.create(
            base_url="https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/",
            username="papaya-user",
            password="papaya-pass",
            active=True,
        )

        delivered = _request_to_inbox(
            node,
            "https://papayawhip-socialdistribution-8613e08ec965.herokuapp.com/api/authors/32df23b6-1ba6-48c0-b23c-f1d6aa42e64e",
            {
                "type": "entry",
                "id": "http://testserver/api/authors/111/entries/249",
                "title": "Updated Post",
                "description": "",
                "contentType": "text/plain",
                "content": "Updated content",
                "visibility": "PUBLIC",
                "author": {
                    "type": "author",
                    "id": "http://testserver/api/authors/111",
                    "displayName": "Local Author",
                    "host": "http://testserver/api/",
                },
            },
            method="PUT",
        )

        self.assertIsNotNone(delivered)
        put_mock.assert_not_called()
        post_mock.assert_called_once()

    @patch("nodes.remote.requests.put")
    @patch("nodes.remote.requests.post")
    def test_request_to_inbox_retries_post_when_put_is_not_allowed(self, post_mock, put_mock):
        """Test that request to inbox retries post when put is not allowed."""
        put_response = Mock()
        put_response.status_code = 405
        put_response.text = '{"detail":"Method not allowed."}'
        put_response.raise_for_status.side_effect = requests.HTTPError(
            response=put_response
        )
        put_mock.return_value = put_response

        post_response = Mock()
        post_response.status_code = 201
        post_response.raise_for_status.return_value = None
        post_mock.return_value = post_response

        node = Node.objects.create(
            base_url="https://generic-remote.example/api/",
            username="generic-user",
            password="generic-pass",
            active=True,
        )

        delivered = _request_to_inbox(
            node,
            "https://generic-remote.example/api/authors/remote-id",
            {
                "type": "entry",
                "id": "http://testserver/api/authors/111/entries/249",
                "title": "Updated Post",
                "description": "",
                "contentType": "text/plain",
                "content": "Updated content",
                "visibility": "PUBLIC",
                "author": {
                    "type": "author",
                    "id": "http://testserver/api/authors/111",
                    "displayName": "Local Author",
                    "host": "http://testserver/api/",
                },
            },
            method="PUT",
        )

        self.assertIs(delivered, post_response)
        put_mock.assert_called_once()
        post_mock.assert_called_once()
