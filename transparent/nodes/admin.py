from django.contrib import admin
from .models import Node

@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ('base_url', 'username', 'active')
    list_filter = ('active',)
    search_fields = ('base_url', 'username')