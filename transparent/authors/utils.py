"""Utilities and logic for utils."""

from core.utils import data_url_from_entry_content, is_base64_image_content_type
from .models import Author
from .serializers import AuthorSerializer
from nodes.models import RemoteAuthor


def annotate_profile_entry(entry):
    """Execute annotate profile entry."""
    entry.display_is_markdown = "text/markdown" in (entry.content_type or "")
    entry.display_has_image = is_base64_image_content_type(entry.content_type)
    entry.display_image_src = data_url_from_entry_content(
        entry.content_type, entry.content)
    entry.display_text = "" if entry.display_has_image else str(
        entry.content or "").lstrip()
    return entry


def resolve_author(fqid, context):
    """Execute resolve author."""
    try:
        author = Author.objects.get(fqid=fqid)
        return AuthorSerializer(author, context=context).data
    except Author.DoesNotExist:
        remote_author = RemoteAuthor.objects.filter(fqid=fqid).first()
        if remote_author:
            return {
                "type": "author",
                "id": remote_author.fqid,
                "host": remote_author.host or remote_author.node.web_base_url,
                "displayName": remote_author.display_name or remote_author.fqid,
                "web": remote_author.fqid.replace("/api/", "/", 1),
                "github": remote_author.github or "",
                "profileImage": remote_author.profile_image or "",
                "description": "",
            }
        return {"type": "author", "id": fqid}
