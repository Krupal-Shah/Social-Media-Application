"""Serializer definitions for the authors app."""

from rest_framework import serializers
from .models import Author


class AuthorSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    # "id" in the spec is the FQID (full API URL), not the UUID primary key
    id = serializers.URLField(source="fqid", read_only=True)
    # Writable display name (mapped from the "displayName" JSON key)
    displayName = serializers.CharField(source="display_name")
    web = serializers.SerializerMethodField()
    # Writable profile image and github urls
    profileImage = serializers.URLField(
        source="profile_image", allow_blank=True, required=False
    )
    github = serializers.URLField(allow_blank=True, required=False)
    description = serializers.CharField(allow_blank=True, required=False)

    class Meta:
        model = Author
        fields = [
            "type", "id", "host", "displayName",
            "web", "github", "profileImage", "description",
        ]
        # id and host are computed/fixed — not settable via PUT
        read_only_fields = ["id", "host"]

    def get_type(self, obj):
        """Return type."""
        return "author"

    def get_web(self, obj):
        """Return the HTML frontend profile URL (no /api/ in path)."""
        return obj.web

    def update(self, instance, validated_data):
        """Execute update."""
        instance.display_name = validated_data.get(
            "display_name", instance.display_name
        )
        instance.github = validated_data.get("github", instance.github)
        instance.profile_image = validated_data.get(
            "profile_image", instance.profile_image
        )
        instance.description = validated_data.get(
            "description", instance.description
        )
        instance.save()
        return instance
