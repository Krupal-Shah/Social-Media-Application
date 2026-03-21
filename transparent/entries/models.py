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
        if not self.fqid:
            self.fqid = f"{self.author.host}authors/{self.author.id}/entries/{self.id}"
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=["visibility"]),
            models.Index(fields=["published"]),
        ]
