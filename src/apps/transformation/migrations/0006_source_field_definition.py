from collections import defaultdict

import django.db.models.deletion
from django.db import migrations, models


def create_source_fields_from_mappings(apps, schema_editor):
    """
    For each existing FieldMapping, derive a SourceFieldDefinition from the
    source_field CharField value (defaulting to type=string), then link the
    mapping to the new FK.
    """
    FieldMapping = apps.get_model("transformation", "FieldMapping")
    SourceFieldDefinition = apps.get_model("transformation", "SourceFieldDefinition")

    # Collect distinct (template_id, source_field name) pairs, preserving order
    seen = defaultdict(dict)  # template_id → {name: order_index}
    for mapping in FieldMapping.objects.order_by("template_id", "order"):
        name = mapping.source_field_name
        if name not in seen[mapping.template_id]:
            seen[mapping.template_id][name] = len(seen[mapping.template_id])

    # Create SourceFieldDefinition rows (type=string, required=True — defaults)
    field_def_map = {}
    for template_id, fields in seen.items():
        for name, order in fields.items():
            fd = SourceFieldDefinition.objects.create(
                template_id=template_id,
                name=name,
                field_type="string",
                required=True,
                nullable=False,
                order=order,
            )
            field_def_map[(template_id, name)] = fd

    # Wire each FieldMapping to its SourceFieldDefinition
    for mapping in FieldMapping.objects.all():
        fd = field_def_map.get((mapping.template_id, mapping.source_field_name))
        if fd:
            mapping.source_field_def = fd
            mapping.save(update_fields=["source_field_def"])


class Migration(migrations.Migration):

    dependencies = [
        ("transformation", "0005_source_path"),
    ]

    operations = [
        # 1 — Create SourceFieldDefinition table
        migrations.CreateModel(
            name="SourceFieldDefinition",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="source_fields",
                        to="transformation.targettemplate",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "field_type",
                    models.CharField(
                        choices=[
                            ("string", "String"),
                            ("number", "Number (float)"),
                            ("integer", "Integer"),
                            ("boolean", "Boolean"),
                            ("date", "Date"),
                            ("datetime", "Datetime"),
                            ("geojson", "GeoJSON geometry"),
                            ("email", "Email"),
                            ("url", "URL"),
                        ],
                        default="string",
                        max_length=16,
                    ),
                ),
                ("required", models.BooleanField(default=True)),
                ("nullable", models.BooleanField(default=False)),
                ("default_value", models.JSONField(blank=True, null=True)),
                ("max_length", models.PositiveIntegerField(blank=True, null=True)),
                ("allowed_values", models.JSONField(blank=True, default=list)),
                ("min_value", models.FloatField(blank=True, null=True)),
                ("max_value", models.FloatField(blank=True, null=True)),
                (
                    "date_format",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "description",
                    models.CharField(blank=True, default="", max_length=512),
                ),
                ("order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "db_table": "source_field_definition",
                "ordering": ["order"],
                "unique_together": {("template", "name")},
            },
        ),
        # 2 — Rename old source_field CharField to source_field_name (temporary)
        migrations.RenameField(
            model_name="fieldmapping",
            old_name="source_field",
            new_name="source_field_name",
        ),
        # 3 — Add nullable FK source_field_def
        migrations.AddField(
            model_name="fieldmapping",
            name="source_field_def",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="mappings",
                to="transformation.SourceFieldDefinition",
            ),
        ),
        # 4 — Data migration: create SourceFieldDefinition rows + wire FK
        migrations.RunPython(
            create_source_fields_from_mappings,
            reverse_code=migrations.RunPython.noop,
        ),
        # 5 — Make FK non-nullable
        migrations.AlterField(
            model_name="fieldmapping",
            name="source_field_def",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="mappings",
                to="transformation.SourceFieldDefinition",
            ),
        ),
        # 6 — Remove old CharField
        migrations.RemoveField(model_name="fieldmapping", name="source_field_name"),
        # 7 — Rename FK field to source_field
        migrations.RenameField(
            model_name="fieldmapping",
            old_name="source_field_def",
            new_name="source_field",
        ),
    ]
