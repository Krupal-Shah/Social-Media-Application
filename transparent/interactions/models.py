"""Data models for the interactions app."""

from django.db import models
import uuid


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fqid = models.URLField(unique=True)

    author_fqid = models.URLField()
    entry_fqid = models.URLField()

    comment = models.TextField()
    content_type = models.CharField(max_length=100)

    published = models.DateTimeField(auto_now_add=True)


class Like(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fqid = models.URLField(unique=True)

    author_fqid = models.URLField()
    object_fqid = models.URLField()

    published = models.DateTimeField(auto_now_add=True)
