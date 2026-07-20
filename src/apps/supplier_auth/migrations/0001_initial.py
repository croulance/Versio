from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Permission",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
                ),
                ("codename", models.CharField(max_length=100, unique=True)),
                ("label", models.CharField(max_length=255)),
            ],
            options={"db_table": "supplier_permission", "ordering": ["codename"]},
        ),
        migrations.CreateModel(
            name="SupplierGroup",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=150, unique=True)),
                (
                    "permissions",
                    models.ManyToManyField(
                        blank=True,
                        related_name="groups",
                        to="supplier_auth.permission",
                    ),
                ),
            ],
            options={"db_table": "supplier_group", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="SupplierAuth",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
                ),
                ("supplier_id", models.IntegerField(db_index=True)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("password", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("last_login", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "groups",
                    models.ManyToManyField(
                        blank=True,
                        related_name="members",
                        to="supplier_auth.suppliergroup",
                    ),
                ),
            ],
            options={"db_table": "supplier_auth"},
        ),
    ]
