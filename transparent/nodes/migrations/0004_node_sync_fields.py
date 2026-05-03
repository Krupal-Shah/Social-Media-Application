"""Database migration 0004_node_sync_fields for nodes."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nodes", "0003_alter_node_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="node",
            name="last_sync_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="node",
            name="last_sync_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="node",
            name="last_sync_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="node",
            name="last_sync_success_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
