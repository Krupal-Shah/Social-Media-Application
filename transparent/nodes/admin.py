"""Django admin registration for the nodes app."""

from django.contrib import admin
from .models import Node, RemoteAuthor


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = (
        "base_url",
        "username",
        "active",
        "last_sync_success_at",
        "last_sync_count",
    )
    readonly_fields = (
        "last_sync_attempt_at",
        "last_sync_success_at",
        "last_sync_error",
        "last_sync_count",
    )
    list_filter = ('active',)
    search_fields = ('base_url', 'username')


@admin.register(RemoteAuthor)
class RemoteAuthorAdmin(admin.ModelAdmin):
    list_display = ("display_name", "fqid", "node", "updated_at")
    list_filter = ("node",)
    search_fields = ("display_name", "fqid", "username", "host")
