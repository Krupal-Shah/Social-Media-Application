"""Django admin registration for the entries app."""

from django.contrib import admin
from .models import Entry

admin.site.register(Entry)