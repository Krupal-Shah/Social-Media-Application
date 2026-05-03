"""Application configuration for the inbox app."""

from django.apps import AppConfig


class InboxConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inbox'
