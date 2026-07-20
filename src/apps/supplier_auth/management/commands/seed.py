from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.supplier_auth.models import SupplierAuth, TransformationSupplier

DEMO_EMAIL = "demo@versio.test"
DEMO_PASSWORD = "versio-demo-2026"
DEMO_SUPPLIER_ACCOUNT_ID = 199

ADMIN_USERNAME = "demo_admin"
ADMIN_EMAIL = "demo-admin@versio.test"
ADMIN_PASSWORD = "versio-admin-2026"


class Command(BaseCommand):
    help = (
        "Seed a demo dashboard login and a Django admin superuser for the auth service."
    )

    def handle(self, *args, **options):
        self._seed_superuser()

        try:
            supplier = TransformationSupplier.objects.get(
                supplier_account_id=DEMO_SUPPLIER_ACCOUNT_ID
            )
        except TransformationSupplier.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(
                    f"No supplier with supplier_account_id={DEMO_SUPPLIER_ACCOUNT_ID} "
                    "found — run `docker compose exec api python manage.py seed` first."
                )
            )
            return

        _, created = SupplierAuth.objects.get_or_create(
            email=DEMO_EMAIL,
            defaults={
                "supplier_id": supplier.id,
                "password": make_password(DEMO_PASSWORD),
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Demo login created: {DEMO_EMAIL}"))
        else:
            self.stdout.write(f"Demo login already exists: {DEMO_EMAIL}")

    # ------------------------------------------------------------------
    # Django admin superuser (django.contrib.auth — separate from
    # SupplierAuth, which has no admin-site access)
    # ------------------------------------------------------------------

    def _seed_superuser(self):
        user, created = User.objects.get_or_create(
            username=ADMIN_USERNAME,
            defaults={"email": ADMIN_EMAIL, "is_staff": True, "is_superuser": True},
        )
        if created:
            user.set_password(ADMIN_PASSWORD)
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f"Superuser created: {ADMIN_USERNAME}")
            )
        else:
            self.stdout.write(f"Superuser already exists: {ADMIN_USERNAME}")
