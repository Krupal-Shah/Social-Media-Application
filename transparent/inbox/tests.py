from __future__ import annotations

from django.conf import settings
from django.test import TestCase

from authors.models import Author
from inbox.models import InboxItem


class InboxItemModelTests(TestCase):
	def test_can_store_inbox_item_payload(self):
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

