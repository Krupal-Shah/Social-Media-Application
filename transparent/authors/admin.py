from django.contrib import admin
from .models import Author
from django.contrib.auth.admin import UserAdmin

class AuthorAdmin(UserAdmin):
    model = Author
    # Add our custom fields to the admin detail view
    fieldsets = UserAdmin.fieldsets + (
        ('Social Distribution Profile', {
            'fields': ('id', 'host', 'fqid', 'display_name', 'github', 'profile_image', 'approved')
        }),
    )
    # Define what columns show up in the main list view
    list_display = ('username', 'display_name', 'email', 'host', 'approved', 'is_staff')
    # Add filters to easily find unapproved users
    list_filter = ('approved', 'is_staff', 'is_active')
    search_fields = ('username', 'display_name', 'email')
    # Keep ID and FQID read-only so admins don't accidentally break federation links
    readonly_fields = ('id', 'fqid')

admin.site.register(Author, AuthorAdmin)

