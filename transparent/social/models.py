from django.db import models
from django.conf import settings


class Follow(models.Model):
    follower_fqid = models.URLField()
    following_fqid = models.URLField()

    accepted = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("follower_fqid", "following_fqid")
