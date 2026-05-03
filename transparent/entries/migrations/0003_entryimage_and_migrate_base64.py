"""Database migration 0003_entryimage_and_migrate_base64 for entries."""

import base64
import json
import uuid

from django.core.files.base import ContentFile
from django.db import migrations, models


def _ext_from_mime(mime_type: str) -> str:
    """Execute ext from mime."""
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }
    return mapping.get((mime_type or "").lower(), ".bin")


def _safe_b64decode(raw: str):
    """Execute safe b64decode."""
    try:
        return base64.b64decode(raw)
    except Exception:
        return None


def migrate_base64_to_files(apps, schema_editor):
    """Execute migrate base64 to files."""
    Entry = apps.get_model("entries", "Entry")
    EntryImage = apps.get_model("entries", "EntryImage")

    for entry in Entry.objects.all().iterator():
        ct = entry.content_type or ""
        if "image/" not in ct:
            continue

        text_content = ""
        text_content_type = "text/plain"

        if "text/markdown" in ct:
            text_content_type = "text/markdown"

        created_any = False

        if "image/gallery" in ct:
            try:
                payload = json.loads(entry.content or "[]")
            except Exception:
                payload = []

            if isinstance(payload, dict):
                gallery = payload.get("gallery", [])
                text_content = str(payload.get("text", ""))
            elif isinstance(payload, list):
                gallery = payload
                text_content = ""
            else:
                gallery = []

            for idx, item in enumerate(gallery):
                if not isinstance(item, dict):
                    continue
                mime_type = str(item.get("type", "")).strip()
                image_b64 = str(item.get("data", "")).strip()
                image_bytes = _safe_b64decode(image_b64)
                if not image_bytes:
                    continue

                ext = _ext_from_mime(mime_type)
                file_name = f"migrated/{entry.id}/{idx}-{uuid.uuid4().hex}{ext}"
                file_content = ContentFile(image_bytes, name=file_name)
                EntryImage.objects.create(
                    entry_id=entry.id,
                    image=file_content,
                    image_index=idx,
                )
                created_any = True

        elif "text/" in ct:
            try:
                payload = json.loads(entry.content or "{}")
            except Exception:
                payload = {}

            mime_type = ct.split("/text/")[0]
            image_b64 = str(payload.get("image", "")).strip()
            text_content = str(payload.get("text", ""))
            image_bytes = _safe_b64decode(image_b64)
            if image_bytes:
                ext = _ext_from_mime(mime_type)
                file_name = f"migrated/{entry.id}/0-{uuid.uuid4().hex}{ext}"
                file_content = ContentFile(image_bytes, name=file_name)
                EntryImage.objects.create(
                    entry_id=entry.id,
                    image=file_content,
                    image_index=0,
                )
                created_any = True

        else:
            mime_type = ct
            image_bytes = _safe_b64decode(entry.content or "")
            if image_bytes:
                ext = _ext_from_mime(mime_type)
                file_name = f"migrated/{entry.id}/0-{uuid.uuid4().hex}{ext}"
                file_content = ContentFile(image_bytes, name=file_name)
                EntryImage.objects.create(
                    entry_id=entry.id,
                    image=file_content,
                    image_index=0,
                )
                created_any = True

        if created_any:
            entry.content = text_content
            entry.content_type = text_content_type
            entry.save(update_fields=["content", "content_type"])


def noop_reverse(apps, schema_editor):
    """Execute noop reverse."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("entries", "0002_entry_updated_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="EntryImage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("image", models.FileField(upload_to="entries/%Y/%m/%d/")),
                ("image_index", models.PositiveIntegerField(default=0)),
                (
                    "entry",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="images",
                        to="entries.entry",
                    ),
                ),
            ],
            options={"ordering": ["image_index"],
                     "unique_together": {("entry", "image_index")}},
        ),
        migrations.RunPython(migrate_base64_to_files, noop_reverse),
    ]
