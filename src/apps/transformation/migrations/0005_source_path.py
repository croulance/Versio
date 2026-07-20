from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transformation", "0004_versioning"),
    ]

    operations = [
        migrations.AddField(
            model_name="targettemplate",
            name="source_path",
            field=models.CharField(
                blank=True,
                default="",
                help_text="ijson path to source items (e.g. 'data.items.item'). Auto-detected if blank.",
                max_length=512,
            ),
        ),
        migrations.AddField(
            model_name="transformationjob",
            name="source_path",
            field=models.CharField(default="data.items.item", max_length=512),
        ),
    ]
