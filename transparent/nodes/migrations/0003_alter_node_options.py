"""Database migration 0003_alter_node_options for nodes."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("nodes", "0002_remoteauthor"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="node",
            options={"ordering": ["base_url"]},
        ),
    ]
