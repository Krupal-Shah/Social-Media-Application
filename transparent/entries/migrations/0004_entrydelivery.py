"""Database migration 0004_entrydelivery for entries."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("nodes", "0002_remoteauthor"),
        ("entries", "0003_entryimage_and_migrate_base64"),
    ]

    operations = [
        migrations.CreateModel(
            name="EntryDelivery",
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
                ("recipient_fqid", models.URLField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_sent_at", models.DateTimeField(auto_now=True)),
                (
                    "entry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="entries.entry",
                    ),
                ),
                (
                    "recipient_node",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="entry_deliveries",
                        to="nodes.node",
                    ),
                ),
            ],
            options={
                "unique_together": {("entry", "recipient_fqid")},
            },
        ),
        migrations.AddIndex(
            model_name="entrydelivery",
            index=models.Index(fields=["recipient_fqid"], name="entries_ent_recipie_e043aa_idx"),
        ),
        migrations.AddIndex(
            model_name="entrydelivery",
            index=models.Index(fields=["last_sent_at"], name="entries_ent_last_se_bb1697_idx"),
        ),
    ]
