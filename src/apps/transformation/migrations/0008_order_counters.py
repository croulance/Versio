from django.db import migrations, models
from django.db.models import Count


def backfill_order_counters(apps, schema_editor):
    """Existing templates already have source fields / mappings created via the
    old COUNT()-based ordering — seed each counter to the current row count so
    the next single-item create continues the sequence without collisions."""
    TargetTemplate = apps.get_model("transformation", "TargetTemplate")
    for t in TargetTemplate.objects.annotate(
        field_count=Count("source_fields", distinct=True),
        mapping_count=Count("field_mappings", distinct=True),
    ):
        t.next_source_field_order = t.field_count
        t.next_mapping_order = t.mapping_count
        t.save(update_fields=["next_source_field_order", "next_mapping_order"])


class Migration(migrations.Migration):

    dependencies = [
        ("transformation", "0007_target_template_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="targettemplate",
            name="next_source_field_order",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Next order value to assign on create_source_field; avoids a COUNT query per create.",
            ),
        ),
        migrations.AddField(
            model_name="targettemplate",
            name="next_mapping_order",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Next order value to assign on create_mapping; avoids a COUNT query per create.",
            ),
        ),
        migrations.RunPython(backfill_order_counters, migrations.RunPython.noop),
    ]
