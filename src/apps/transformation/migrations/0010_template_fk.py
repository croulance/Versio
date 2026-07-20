import django.db.models.deletion
from django.db import migrations, models


def backfill_job_template(apps, schema_editor):
    TransformationJob = apps.get_model("transformation", "TransformationJob")
    TargetTemplate = apps.get_model("transformation", "TargetTemplate")
    for job in TransformationJob.objects.all():
        template = TargetTemplate.objects.filter(
            supplier_id=job.supplier_id,
            format=job.format,
            version=job.template_version,
        ).first()
        if template:
            job.template_id = template.id
            job.save(update_fields=["template"])


class Migration(migrations.Migration):

    dependencies = [
        ("transformation", "0009_transformationjob_job_supplier_created_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="transformationjob",
            name="template",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="jobs",
                to="transformation.targettemplate",
            ),
        ),
        migrations.RunPython(backfill_job_template, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="transformationjob",
            name="template",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="jobs",
                to="transformation.targettemplate",
            ),
        ),
        migrations.RemoveField(
            model_name="transformationjob",
            name="template_version",
        ),
        migrations.AlterUniqueTogether(
            name="targettemplate",
            unique_together={("supplier", "name", "format", "version")},
        ),
    ]
