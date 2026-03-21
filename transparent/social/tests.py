from django.test import TestCase

from django.db import IntegrityError

from social.models import Follow


class FollowModelTests(TestCase):
	def test_unique_together_enforced(self):
		Follow.objects.create(
			follower_fqid="https://example.com/api/authors/a",
			following_fqid="https://example.com/api/authors/b",
			accepted=False,
		)
		with self.assertRaises(IntegrityError):
			Follow.objects.create(
				follower_fqid="https://example.com/api/authors/a",
				following_fqid="https://example.com/api/authors/b",
				accepted=True,
			)

