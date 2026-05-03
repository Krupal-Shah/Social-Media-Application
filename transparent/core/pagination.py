"""
Custom DRF pagination for the social distribution API.

Response shape::

    {
        "type":        "entries",   # or "comments", "likes" - set by the view
        "page_number": 1,
        "size":        10,
        "count":       9001,
        "src":         [ ... ]
    }

Query parameters accepted by clients:
    ?page=<int>  - 1-based page index  (default 1)
    ?size=<int>  - items per page      (default PAGE_SIZE, max MAX_PAGE_SIZE)
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class EntriesPagination(PageNumberPagination):
    """Paginator for entry lists."""

    page_query_param = "page"
    page_size = 10
    page_size_query_param = "size"
    max_page_size = 50

    #: Override in a subclass to change the "type" field in the response.
    response_type = "entries"

    def get_paginated_response(self, data):
        """Return paginated response."""
        return Response(
            {
                "type": self.response_type,
                "page_number": self.page.number,
                "size": self.get_page_size(self.request),
                "count": self.page.paginator.count,
                "src": data,
            }
        )

    # for DRF spectacular / docs
    def get_paginated_response_schema(self, schema):
        """Return paginated response schema."""
        return {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "page_number": {"type": "integer"},
                "size": {"type": "integer"},
                "count": {"type": "integer"},
                "src": schema,
            },
        }


class CommentsPagination(EntriesPagination):
    """Paginator for comment lists."""

    response_type = "comments"
    page_size = 5
    max_page_size = 50


class LikesPagination(EntriesPagination):
    """Paginator for like lists."""

    response_type = "likes"
    page_size = 50
    max_page_size = 100


class AuthorsPagination(EntriesPagination):
    """Paginator for author lists.

    Response shape::

        {
            "type":        "authors",
            "page_number": 1,
            "size":        10,
            "count":       42,
            "authors":     [ ... ]
        }
    """

    response_type = "authors"
    page_size = 10
    page_size_query_param = "size"
    max_page_size = 50

    def get_paginated_response(self, data):
        """Return paginated response."""
        return Response(
            {
                "type": self.response_type,
                "page_number": self.page.number,
                "size": self.get_page_size(self.request),
                "count": self.page.paginator.count,
                "authors": data,
            }
        )

def parse_pagination(request, default_size, max_size):
    """Execute parse pagination."""
    try:
        page_num = max(1, int(request.GET.get("page", 1)))
    except (TypeError, ValueError):
        page_num = 1

    try:
        requested_size = int(request.GET.get("size", default_size))
    except (TypeError, ValueError):
        requested_size = default_size

    size = min(max(1, requested_size), max_size)
    return page_num, size
