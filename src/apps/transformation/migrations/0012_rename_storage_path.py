from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("transformation", "0011_alter_sourcefielddefinition_field_type"),
    ]

    operations = [
        migrations.RenameField(
            model_name="transformationjob",
            old_name="s3_path",
            new_name="storage_path",
        ),
        migrations.RenameField(
            model_name="transformationjob",
            old_name="output_s3_path",
            new_name="output_storage_path",
        ),
    ]
