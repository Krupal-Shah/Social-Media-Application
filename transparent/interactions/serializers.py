"""Serializer definitions for the interactions app."""

from rest_framework import serializers
from authors.serializers import AuthorSerializer
from core.fqid import api_to_web_url
from django.core.paginator import Paginator
from core.pagination import parse_pagination
from .models import Comment
from .models import Like


def build_comments_object(request, comments_qs, entry_fqid, comments_api_id):
    """Build comments object."""
    page_num, size = parse_pagination(request, default_size=5, max_size=50)
    paginator = Paginator(comments_qs, size)
    page = paginator.get_page(page_num)
    serialized = CommentSerializer(page.object_list, many=True).data

    return {
        "type": "comments",
        "web": api_to_web_url(entry_fqid),
        "id": comments_api_id,
        "page_number": page.number,
        "size": size,
        "count": paginator.count,
        "src": serialized,
    }


def build_likes_object(
    request,
    likes_qs,
    object_fqid,
    likes_api_id,
    include_src=True,
):
    """Build likes object."""
    likes_qs = likes_qs.order_by("-published")
    if request is not None:
        page_num, size = parse_pagination(
            request, default_size=50, max_size=100)
        paginator = Paginator(likes_qs, size)
        page = paginator.get_page(page_num)

        count = paginator.count
        page_number = page.number
        page_size = size
        objects = page.object_list
    else:
        count = likes_qs.count()
        page_number = 1
        page_size = count
        objects = likes_qs

    src = (
        LikeSerializer(objects, many=True).data
        if include_src else []
    )

    # Resolve correct web URL
    entry_web = api_to_web_url(object_fqid)
    comment = Comment.objects.filter(
        fqid=object_fqid).only("entry_fqid").first()
    if comment:
        entry_web = api_to_web_url(comment.entry_fqid)

    return {
        "type": "likes",
        "id": likes_api_id,
        "web": entry_web,
        "page_number": page_number,
        "size": page_size,
        "count": count,
        "src": src,
    }


class LikeSerializer(serializers.Serializer):
    """
    This Serial
    """
    type = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    published = serializers.DateTimeField()
    id = serializers.URLField(source="fqid")
    object = serializers.URLField(source="object_fqid")

    def get_type(self, obj):
        """Return type."""
        return "like"

    def get_author(self, obj):
        """Return author."""
        from authors.models import Author
        try:
            author = Author.objects.get(fqid=obj.author_fqid)
            return AuthorSerializer(author).data
        except Author.DoesNotExist:
            return {"type": "author", "id": obj.author_fqid}


class CommentSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    id = serializers.URLField(source="fqid", read_only=True)
    contentType = serializers.CharField(source="content_type", read_only=True)
    author = serializers.SerializerMethodField()
    entry = serializers.URLField(source="entry_fqid", read_only=True)
    web = serializers.SerializerMethodField()
    likes = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "type", "author", "comment", "contentType",
            "published", "id", "entry", "web", "likes",
        ]

    def get_type(self, obj):
        """Return type."""
        return "comment"

    def get_author(self, obj):
        """Return author."""
        from authors.models import Author
        try:
            author = Author.objects.get(fqid=obj.author_fqid)
            return AuthorSerializer(author).data
        except Author.DoesNotExist:
            return {"type": "author", "id": obj.author_fqid}

    def get_web(self, obj):
        """Return web."""
        return api_to_web_url(obj.entry_fqid)

    def get_likes(self, obj):
        """Return likes."""
        likes_qs = Like.objects.filter(object_fqid=obj.fqid)
        likes_api_id = f"{obj.fqid}/likes"

        return build_likes_object(
            None,
            likes_qs,
            obj.fqid,
            likes_api_id,
            include_src=True
        )
