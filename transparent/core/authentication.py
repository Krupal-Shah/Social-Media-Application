"""Utilities and logic for authentication."""

from rest_framework.authentication import BasicAuthentication
from rest_framework.exceptions import AuthenticationFailed


class NonStrictBasicAuthentication(BasicAuthentication):
    """
    Allow Django-user basic auth when valid, but do not fail early when the
    credentials are actually node-to-node Basic Auth handled by view logic.
    """

    def authenticate(self, request):
        """Execute authenticate."""
        try:
            return super().authenticate(request)
        except AuthenticationFailed:
            return None
