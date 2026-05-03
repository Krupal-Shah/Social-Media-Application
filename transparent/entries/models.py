"""Data models for the entries app."""

import uuid
from django.db import models


class Entry(models.Model):
    VISIBILITY = [
        ("PUBLIC", "Public"),
        ("FRIENDS", "Friends"),
        ("UNLISTED", "Unlisted"),
        ("DELETED", "Deleted"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fqid = models.URLField(unique=True)

    author = models.ForeignKey(
        "authors.Author", on_delete=models.CASCADE, related_name="entries")

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    content = models.TextField()
    content_type = models.CharField(max_length=100)

    visibility = models.CharField(max_length=10, choices=VISIBILITY)

    published = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    sent_to = models.ManyToManyField(
        "authors.Author", blank=True, related_name="received_entries")

    def save(self, *args, **kwargs):
        """Execute save."""
        if not self.fqid:
            self.fqid = f"{self.author.host}authors/{self.author.id}/entries/{self.id}"
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=["visibility"]),
            models.Index(fields=["published"]),
        ]


class EntryDelivery(models.Model):
    entry = models.ForeignKey(
        Entry, on_delete=models.CASCADE, related_name="deliveries"
    )
    recipient_fqid = models.URLField()
    recipient_node = models.ForeignKey(
        "nodes.Node",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entry_deliveries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("entry", "recipient_fqid")
        indexes = [
            models.Index(fields=["recipient_fqid"]),
            models.Index(fields=["last_sent_at"]),
        ]


class EntryImage(models.Model):
    entry = models.ForeignKey(
        Entry, on_delete=models.CASCADE, related_name="images"
    )
    image = models.FileField(upload_to="entries/%Y/%m/%d/")
    image_index = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["image_index"]
        unique_together = ("entry", "image_index")
