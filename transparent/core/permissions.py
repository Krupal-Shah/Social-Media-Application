"""
Reusable DRF permission classes for the social distribution API.
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsApprovedAuthor(BasePermission):
    """Allows access only to locally authenticated *and* approved authors."""

    message = "Authentication as an approved local author is required."

    def has_permission(self, request, view):
        """Return whether this has permission."""
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "approved", False)
        )


class IsEntryAuthor(BasePermission):
    """
    Object-level permission: the requesting user must be the author
    of the Entry object being acted upon.
    """

    message = "You must be the author of this entry."

    def has_object_permission(self, request, view, obj):
        """Return whether this has object permission."""
        return bool(
            request.user
            and request.user.is_authenticated
            and obj.author == request.user
        )


class IsOwnerOrReadOnly(BasePermission):
    """
    Generic object-level permission: allow GET/HEAD/OPTIONS to anyone,
    but write access only to the object's owner.

    The object must expose an ``author`` attribute for ownership checks.
    """

    def has_object_permission(self, request, view, obj):
        """Return whether this has object permission."""
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user
            and request.user.is_authenticated
            and obj.author == request.user
        )
