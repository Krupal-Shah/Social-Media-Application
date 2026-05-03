"""Data models for the inbox app."""

from django.db import models


class InboxItem(models.Model):
    author = models.ForeignKey("authors.Author", on_delete=models.CASCADE)

    type = models.CharField(max_length=20)
    payload = models.JSONField()

    received = models.DateTimeField(auto_now_add=True)
