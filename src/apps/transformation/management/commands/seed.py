from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.transformation.models import TargetTemplate
from apps.transformation.repositories.supplier_repository import \
    SupplierRepository
from apps.transformation.repositories.template_repository import \
    TemplateRepository

ADMIN_USERNAME = "demo_admin"
ADMIN_EMAIL = "demo-admin@versio.test"
ADMIN_PASSWORD = "versio-admin-2026"


class Command(BaseCommand):
    help = "Seed database with sample supplier, templates, source schema and field mappings for testing"

    def handle(self, *args, **options):
        supplier_repo = SupplierRepository()
        template_repo = TemplateRepository()

        self._seed_geojson(supplier_repo, template_repo)
        self._seed_csv(supplier_repo, template_repo)
        self._seed_xlsx(supplier_repo, template_repo)
        self._seed_superuser()
        self.stdout.write(self.style.SUCCESS("Seed complete."))

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

    # ------------------------------------------------------------------
    # GeoJSON template
    # ------------------------------------------------------------------

    def _seed_geojson(
        self, supplier_repo: SupplierRepository, template_repo: TemplateRepository
    ):
        supplier, _ = supplier_repo.get_or_create(
            supplier_account_id=199,
            name="Peru Country 006",
        )

        template, _ = template_repo.get_or_create_template(
            supplier_id=supplier.id,
            format="geojson",
            version=1,
            name="GeoJSON Elgon",
            source_path="data.items.item",
            metadata={
                "name": "Versio GeoJSON Export",
                "crs": {
                    "type": "name",
                    "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
                },
            },
        )
        template_repo.set_status(template.id, TargetTemplate.Status.PUBLISHED)

        # Source schema — 3 most relevant fields
        template_repo.replace_source_fields(
            template.id,
            [
                {
                    "name": "plotName",
                    "field_type": "string",
                    "required": True,
                    "nullable": False,
                    "max_length": 512,
                    "description": "Unique plot identifier (maps to External_ID in Tract template)",
                    "order": 0,
                },
                {
                    "name": "area",
                    "field_type": "number",
                    "required": True,
                    "nullable": False,
                    "min_value": 0.0,
                    "description": "Cultivated area in hectares",
                    "order": 1,
                },
                {
                    "name": "plotGeoJson",
                    "field_type": "geojson",
                    "required": True,
                    "nullable": False,
                    "description": "Plot boundary as GeoJSON geometry string",
                    "order": 2,
                },
            ],
        )

        template_repo.replace_mappings(
            template.id,
            [
                {
                    "source_field": "plotName",
                    "target_field": "External_ID",
                    "handler_method": "direct",
                    "handler_data": {"field": "plotName"},
                    "order": 0,
                },
                {
                    "source_field": "area",
                    "target_field": "Total_Cultivated_Area",
                    "handler_method": "direct",
                    "handler_data": {"field": "area"},
                    "order": 1,
                },
                {
                    "source_field": "plotGeoJson",
                    "target_field": "__geometry__",
                    "handler_method": "parse_geojson_geometry",
                    "handler_data": {},
                    "order": 2,
                },
            ],
        )

        self.stdout.write(f"  GeoJSON template v1 seeded for supplier {supplier.name}")

    # ------------------------------------------------------------------
    # CSV template
    # ------------------------------------------------------------------

    def _seed_csv(
        self, supplier_repo: SupplierRepository, template_repo: TemplateRepository
    ):
        supplier, _ = supplier_repo.get_or_create(
            supplier_account_id=199,
            name="Peru Country 006",
        )

        template, _ = template_repo.get_or_create_template(
            supplier_id=supplier.id,
            format="csv",
            version=1,
            name="CSV Tract Export",
            source_path="data.items.item",
            metadata={
                "headers": [
                    "Producer Name",
                    "Total_Cultivated_Area",
                    "Deforestation Risk",
                ]
            },
        )
        template_repo.set_status(template.id, TargetTemplate.Status.PUBLISHED)

        # Source schema — 3 most relevant fields
        template_repo.replace_source_fields(
            template.id,
            [
                {
                    "name": "producerName",
                    "field_type": "string",
                    "required": True,
                    "nullable": False,
                    "max_length": 255,
                    "description": "Producer or farmer full name",
                    "order": 0,
                },
                {
                    "name": "area",
                    "field_type": "number",
                    "required": True,
                    "nullable": False,
                    "min_value": 0.0,
                    "description": "Cultivated area in hectares",
                    "order": 1,
                },
                {
                    "name": "deforestationRisk",
                    "field_type": "object",
                    "required": False,
                    "nullable": True,
                    "description": "Deforestation risk object (nested — code extracted by handler)",
                    "order": 2,
                },
            ],
        )

        template_repo.replace_mappings(
            template.id,
            [
                {
                    "source_field": "producerName",
                    "target_field": "Producer Name",
                    "handler_method": "direct",
                    "handler_data": {"field": "producerName"},
                    "order": 0,
                },
                {
                    "source_field": "area",
                    "target_field": "Total_Cultivated_Area",
                    "handler_method": "direct",
                    "handler_data": {"field": "area"},
                    "order": 1,
                },
                {
                    "source_field": "deforestationRisk",
                    "target_field": "Deforestation Risk",
                    "handler_method": "nested_code",
                    "handler_data": {
                        "field": "deforestationRisk",
                        "code_key": "deforestationRiskCode",
                    },
                    "order": 2,
                },
            ],
        )

        self.stdout.write(f"  CSV template v1 seeded for supplier {supplier.name}")

    # ------------------------------------------------------------------
    # XLSX template — mirrors Tract template column structure
    # ------------------------------------------------------------------

    def _seed_xlsx(
        self, supplier_repo: SupplierRepository, template_repo: TemplateRepository
    ):
        supplier, _ = supplier_repo.get_or_create(
            supplier_account_id=199,
            name="Peru Country 006",
        )

        template, _ = template_repo.get_or_create_template(
            supplier_id=supplier.id,
            format="xlsx",
            version=1,
            name="XLSX Tract Export",
            source_path="data.items.item",
            metadata={
                "sheet_name": "Farms_Template",
                "columns": ["External_ID", "Producer Name", "Total_Cultivated_Area"],
            },
        )
        template_repo.set_status(template.id, TargetTemplate.Status.PUBLISHED)

        # Source schema — 3 fields matching Tract template columns
        template_repo.replace_source_fields(
            template.id,
            [
                {
                    "name": "plotName",
                    "field_type": "string",
                    "required": True,
                    "nullable": False,
                    "max_length": 512,
                    "description": "Unique plot identifier — maps to External_ID in Tract template",
                    "order": 0,
                },
                {
                    "name": "producerName",
                    "field_type": "string",
                    "required": True,
                    "nullable": False,
                    "max_length": 255,
                    "description": "Producer or farmer full name",
                    "order": 1,
                },
                {
                    "name": "area",
                    "field_type": "number",
                    "required": True,
                    "nullable": False,
                    "min_value": 0.0,
                    "description": "Cultivated area in hectares — maps to Total_Cultivated_Area",
                    "order": 2,
                },
            ],
        )

        # Mappings → target_field names become XLSX column headers
        template_repo.replace_mappings(
            template.id,
            [
                {
                    "source_field": "plotName",
                    "target_field": "External_ID",
                    "handler_method": "direct",
                    "handler_data": {"field": "plotName"},
                    "order": 0,
                },
                {
                    "source_field": "producerName",
                    "target_field": "Producer Name",
                    "handler_method": "direct",
                    "handler_data": {"field": "producerName"},
                    "order": 1,
                },
                {
                    "source_field": "area",
                    "target_field": "Total_Cultivated_Area",
                    "handler_method": "direct",
                    "handler_data": {"field": "area"},
                    "order": 2,
                },
            ],
        )

        self.stdout.write(f"  XLSX template v1 seeded for supplier {supplier.name}")
