from dataclasses import dataclass, field

from apps.transformation.dtos.mapping import MappingSnapshot
from apps.transformation.interfaces.repository import (
    SupplierRepositoryInterface, TemplateRepositoryInterface)
from apps.transformation.services.guards import editable_conflict


@dataclass
class MappingResult:
    ok: bool
    mapping: MappingSnapshot | None = None
    mappings: list = field(default_factory=list)
    not_found: bool = False
    conflict: bool = False
    error: str | None = None


class MappingService:
    """CRUD for FieldMapping, scoped to a template and gated by the
    template's DRAFT/PUBLISHED/DEPRECATED lock."""

    def __init__(
        self,
        repository: TemplateRepositoryInterface,
        supplier_repository: SupplierRepositoryInterface,
    ):
        self._repo = repository
        self._suppliers = supplier_repository

    def list(self, template_id: int, supplier_account_id: int) -> MappingResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        if not supplier or not self._repo.get_owned_template(template_id, supplier.id):
            return MappingResult(ok=False, not_found=True)
        mappings = self._repo.list_mappings(template_id)
        return MappingResult(ok=True, mappings=mappings)

    def create(
        self, template_id: int, supplier_account_id: int, data: dict
    ) -> MappingResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        template = (
            self._repo.get_owned_template(template_id, supplier.id)
            if supplier
            else None
        )
        if not template:
            return MappingResult(ok=False, not_found=True, error="Template not found")

        conflict = editable_conflict(self._repo, template)
        if conflict:
            return MappingResult(ok=False, conflict=True, error=conflict)

        source_field = self._repo.get_source_field_for_template(
            template_id, data.get("source_field_id")
        )
        if not source_field:
            return MappingResult(
                ok=False, not_found=True, error="Source field not found"
            )

        if template.format == "xlsx" and not data.get("sheet_name"):
            return MappingResult(
                ok=False,
                conflict=True,
                error="sheet_name is required for xlsx mappings",
            )

        # source_field.path (not .name) so a nested leaf's default handler_data
        # addresses it correctly, e.g. "complianceStatus.label" not just "label"
        # — resolve_path() makes a top-level field's path == its name, so this
        # is unchanged for every pre-existing, non-nested mapping.
        handler_data = data.get("handler_data", {"field": source_field.path})
        m = self._repo.create_mapping(
            template_id, source_field.id, {**data, "handler_data": handler_data}
        )
        return MappingResult(ok=True, mapping=m)

    def update(
        self, template_id: int, mapping_id: int, supplier_account_id: int, data: dict
    ) -> MappingResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        m = (
            self._repo.get_owned_mapping(template_id, mapping_id, supplier.id)
            if supplier
            else None
        )
        if not m:
            return MappingResult(ok=False, not_found=True)

        template = self._repo.get_owned_template(template_id, supplier.id)
        conflict = editable_conflict(self._repo, template)
        if conflict:
            return MappingResult(ok=False, conflict=True, error=conflict)

        if "source_field_id" in data:
            source_field = self._repo.get_source_field_for_template(
                template_id, data["source_field_id"]
            )
            if not source_field:
                return MappingResult(
                    ok=False, not_found=True, error="Source field not found"
                )

        resulting_sheet_name = data.get("sheet_name", m.sheet_name)
        if template.format == "xlsx" and not resulting_sheet_name:
            return MappingResult(
                ok=False,
                conflict=True,
                error="sheet_name is required for xlsx mappings",
            )

        updated = self._repo.update_mapping(mapping_id, data)
        return MappingResult(ok=True, mapping=updated)

    def delete(
        self, template_id: int, mapping_id: int, supplier_account_id: int
    ) -> MappingResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        m = (
            self._repo.get_owned_mapping(template_id, mapping_id, supplier.id)
            if supplier
            else None
        )
        if not m:
            return MappingResult(ok=False, not_found=True)

        template = self._repo.get_owned_template(template_id, supplier.id)
        conflict = editable_conflict(self._repo, template)
        if conflict:
            return MappingResult(ok=False, conflict=True, error=conflict)

        self._repo.delete_mapping(mapping_id)
        return MappingResult(ok=True)
