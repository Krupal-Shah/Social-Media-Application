"""Serializer definitions for the entries app."""

from rest_framework import serializers
from authors.serializers import AuthorSerializer
from .models import Entry
from interactions.models import Comment
from core.fqid import api_to_web_url
from interactions.models import Like
from interactions.serializers import CommentSerializer, build_likes_object

class EntrySerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    id = serializers.URLField(source="fqid", read_only=True)
    web = serializers.SerializerMethodField()
    contentType = serializers.CharField(source="content_type")
    author = AuthorSerializer(read_only=True)
    comments = serializers.SerializerMethodField()
    likes = serializers.SerializerMethodField()

    class Meta:
        model = Entry
        fields = [
            "type", "title", "id", "web", "description",
            "contentType", "content", "author",
            "comments", "likes", "published", "visibility",
        ]

    def get_type(self, obj):
        """Return type."""
        return "entry"

    def get_web(self, obj):
        """HTML frontend URL – identical to the API FQID but without /api/."""
        return api_to_web_url(obj.fqid)

    def get_comments(self, obj):
        """Return a nested comments object with ~ 5 newest comments in src."""
        comments_id = f"{obj.fqid}/comments"
        comments_web = api_to_web_url(obj.fqid)

        comment_qs = Comment.objects.filter(
            entry_fqid=obj.fqid
        ).order_by("-published")
        page_size = 5
        count = comment_qs.count()
        # Include src for all non-deleted entries (visibility check done in view)
        src = CommentSerializer(comment_qs[:page_size], many=True).data

        return {
            "type": "comments",
            "web": comments_web,
            "id": comments_id,
            "page_number": 1,
            "size": page_size,
            "count": count,
            "src": src,
        }
    
    def get_likes(self, obj):
        """Return likes."""
        likes_qs = Like.objects.filter(object_fqid=obj.fqid)
        likes_api_id = f"{obj.fqid}/likes"
        include_src = obj.visibility in ("PUBLIC", "UNLISTED", "FRIENDS")
        return build_likes_object(
            None,
            likes_qs,
            obj.fqid,
            likes_api_id,
            include_src
        )

    def update(self, instance, validated_data):
        """Execute update."""
        # DRF maps the serializer source "content_type" back from "contentType"
        if "content_type" in validated_data:
            instance.content_type = validated_data.pop("content_type")
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
