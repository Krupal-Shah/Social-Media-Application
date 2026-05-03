"""Data models for the nodes app."""

from django.db import models

from core.utils import normalize_api_base


class NodeQuerySet(models.QuerySet):
    def active(self):
        """Execute active."""
        return self.filter(active=True).exclude(base_url__isnull=True).exclude(base_url="")


class Node(models.Model):
    base_url = models.URLField(unique=True, blank=True, null=True)

    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)

    active = models.BooleanField(default=True)
    last_sync_attempt_at = models.DateTimeField(null=True, blank=True)
    last_sync_success_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True, default="")
    last_sync_count = models.PositiveIntegerField(default=0)

    objects = NodeQuerySet.as_manager()

    class Meta:
        ordering = ["base_url"]

    def save(self, *args, **kwargs):
        """Execute save."""
        normalized_base_url = normalize_api_base(self.base_url)
        self.base_url = normalized_base_url or None
        super().save(*args, **kwargs)

    def __str__(self):
        """Return the string representation of this object."""
        return self.base_url or ""

    @property
    def api_base_url(self):
        """Execute api base url."""
        return normalize_api_base(self.base_url)

    @property
    def web_base_url(self):
        """Execute web base url."""
        api_base = self.api_base_url
        return api_base[:-4] if api_base.endswith("/api") else api_base

    @property
    def scope_variants(self):
        """Execute scope variants."""
        return [scope for scope in {self.api_base_url, self.web_base_url} if scope]

    def matches_url(self, value):
        """Execute matches url."""
        candidate = str(value or "").strip().rstrip("/")
        if not candidate:
            return False
        return any(
            candidate == scope.rstrip("/") or candidate.startswith(f"{scope.rstrip('/')}/")
            for scope in self.scope_variants
        )

    @property
    def sync_ok(self):
        """Execute sync ok."""
        return not self.last_sync_error


class RemoteAuthor(models.Model):
    node = models.ForeignKey(
        "nodes.Node",
        on_delete=models.CASCADE,
        related_name="remote_authors",
    )
    fqid = models.URLField(unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    username = models.CharField(max_length=255, blank=True)
    host = models.URLField(blank=True)
    github = models.URLField(blank=True)
    profile_image = models.URLField(blank=True)
    raw = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name", "fqid"]
