from dataclasses import dataclass, field

from apps.transformation.dtos.source_field import SourceFieldSnapshot
from apps.transformation.interfaces.repository import (
    SupplierRepositoryInterface, TemplateRepositoryInterface)
from apps.transformation.services.guards import editable_conflict


@dataclass
class SourceFieldResult:
    ok: bool
    field_item: SourceFieldSnapshot | None = None
    fields: list = field(default_factory=list)
    not_found: bool = False
    conflict: bool = False
    error: str | None = None


class SourceFieldService:
    """CRUD for SourceFieldDefinition, scoped to a template and gated by the
    template's DRAFT/PUBLISHED/DEPRECATED lock."""

    def __init__(
        self,
        repository: TemplateRepositoryInterface,
        supplier_repository: SupplierRepositoryInterface,
    ):
        self._repo = repository
        self._suppliers = supplier_repository

    def list(self, template_id: int, supplier_account_id: int) -> SourceFieldResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        if not supplier or not self._repo.get_owned_template(template_id, supplier.id):
            return SourceFieldResult(ok=False, not_found=True)
        fields = self._repo.get_source_fields(template_id)
        return SourceFieldResult(ok=True, fields=fields)

    def create(
        self, template_id: int, supplier_account_id: int, data: dict
    ) -> SourceFieldResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        template = (
            self._repo.get_owned_template(template_id, supplier.id)
            if supplier
            else None
        )
        if not template:
            return SourceFieldResult(
                ok=False, not_found=True, error="Template not found"
            )

        conflict = editable_conflict(self._repo, template)
        if conflict:
            return SourceFieldResult(ok=False, conflict=True, error=conflict)

        parent_id = data.get("parent_id")
        if parent_id is not None:
            parent = self._repo.get_source_field_for_template(template_id, parent_id)
            if not parent:
                return SourceFieldResult(
                    ok=False, not_found=True, error="Parent field not found"
                )
            if parent.field_type != "object":
                return SourceFieldResult(
                    ok=False,
                    conflict=True,
                    error="Parent field must be of type 'object'",
                )

        f = self._repo.create_source_field(template_id, data)
        return SourceFieldResult(ok=True, field_item=f)

    def update(
        self, template_id: int, field_id: int, supplier_account_id: int, data: dict
    ) -> SourceFieldResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        f = (
            self._repo.get_owned_source_field(template_id, field_id, supplier.id)
            if supplier
            else None
        )
        if not f:
            return SourceFieldResult(ok=False, not_found=True)

        template = self._repo.get_owned_template(template_id, supplier.id)
        conflict = editable_conflict(self._repo, template)
        if conflict:
            return SourceFieldResult(ok=False, conflict=True, error=conflict)

        if (
            "field_type" in data
            and data["field_type"] != "object"
            and f.field_type == "object"
            and self._repo.source_field_has_children(field_id)
        ):
            return SourceFieldResult(
                ok=False,
                conflict=True,
                error="Cannot change type: field has nested children — delete them first",
            )

        updated = self._repo.update_source_field(field_id, data)
        return SourceFieldResult(ok=True, field_item=updated)

    def delete(
        self, template_id: int, field_id: int, supplier_account_id: int
    ) -> SourceFieldResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        f = (
            self._repo.get_owned_source_field(template_id, field_id, supplier.id)
            if supplier
            else None
        )
        if not f:
            return SourceFieldResult(ok=False, not_found=True)

        template = self._repo.get_owned_template(template_id, supplier.id)
        conflict = editable_conflict(self._repo, template)
        if conflict:
            return SourceFieldResult(ok=False, conflict=True, error=conflict)

        if self._repo.source_field_has_children(field_id):
            return SourceFieldResult(
                ok=False,
                conflict=True,
                error="Cannot delete: field has nested children — delete them first",
            )

        if self._repo.source_field_has_mappings(field_id):
            return SourceFieldResult(
                ok=False,
                conflict=True,
                error="Cannot delete: field is referenced by a mapping",
            )

        self._repo.delete_source_field(field_id)
        return SourceFieldResult(ok=True)
