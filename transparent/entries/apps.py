"""Application configuration for the entries app."""

from django.apps import AppConfig


class EntriesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'entries'
