"""Django admin registration for the social app."""

from django.contrib import admin
from .models import Follow

admin.site.register(Follow)
