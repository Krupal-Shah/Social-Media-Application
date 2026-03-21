from rest_framework import serializers
from authors.serializers import AuthorSerializer
from .models import Entry
from interactions.models import Comment, Like
from core.fqid import api_to_web_url


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
        return "like"

    def get_author(self, obj):
        from authors.models import Author
        try:
            author = Author.objects.get(fqid=obj.author_fqid)
            return AuthorSerializer(author).data
        except Author.DoesNotExist:
            return {"type": "author", "id": obj.author_fqid}


def _build_likes_object(object_fqid: str, include_src: bool = True) -> dict:
    """
    Build the nested 'likes' object for an entry or comment FQID.
    Returns ~ 50 newest likes in ``src`` when *include_src* is True.
    """
    like_qs = Like.objects.filter(
        object_fqid=object_fqid).order_by("-published")
    page_size = 50
    count = like_qs.count()
    src = LikeSerializer(like_qs[:page_size],
                         many=True).data if include_src else []
    return {
        "type": "likes",
        "id": f"{object_fqid}/likes",
        "web": api_to_web_url(object_fqid) + "/likes",
        "page_number": 1,
        "size": page_size,
        "count": count,
        "src": src,
    }


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
        return "comment"

    def get_author(self, obj):
        from authors.models import Author
        try:
            author = Author.objects.get(fqid=obj.author_fqid)
            return AuthorSerializer(author).data
        except Author.DoesNotExist:
            return {"type": "author", "id": obj.author_fqid}

    def get_web(self, obj):
        return api_to_web_url(obj.entry_fqid)

    def get_likes(self, obj):
        return _build_likes_object(obj.fqid, include_src=True)


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
        return "entry"

    def get_web(self, obj):
        """HTML frontend URL – identical to the API FQID but without /api/."""
        return api_to_web_url(obj.fqid)

    def get_comments(self, obj):
        """Return a nested comments object with ~ 5 newest comments in src."""
        comments_id = f"{obj.fqid}/comments"
        comments_web = api_to_web_url(obj.fqid) + "/comments"

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
        """Return a nested likes object with ~ 50 newest likes in src."""
        include_src = obj.visibility in ("PUBLIC", "UNLISTED", "FRIENDS")
        return _build_likes_object(obj.fqid, include_src=include_src)

    def update(self, instance, validated_data):
        # DRF maps the serializer source "content_type" back from "contentType"
        if "content_type" in validated_data:
            instance.content_type = validated_data.pop("content_type")
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
