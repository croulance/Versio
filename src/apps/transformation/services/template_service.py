from dataclasses import dataclass, field

from apps.transformation.dtos.template import TemplateSnapshot
from apps.transformation.interfaces.repository import (
    SupplierRepositoryInterface, TemplateRepositoryInterface)


@dataclass
class TemplateResult:
    ok: bool
    template: TemplateSnapshot | None = None
    not_found: bool = False
    conflict: bool = False
    error: str | None = None


@dataclass
class TemplateDetailResult:
    ok: bool
    template: TemplateSnapshot | None = None
    source_fields: list = field(default_factory=list)
    mappings: list = field(default_factory=list)
    not_found: bool = False


class TemplateService:
    """CRUD + read operations for TargetTemplate, kept behind the repository
    interface so views never touch the ORM or a concrete repository class."""

    def __init__(
        self,
        template_repository: TemplateRepositoryInterface,
        supplier_repository: SupplierRepositoryInterface,
    ):
        self._templates = template_repository
        self._suppliers = supplier_repository

    def list(
        self, supplier_id: int | None, status: str | None, ordering: str | None
    ) -> list[TemplateSnapshot]:
        return self._templates.list_templates(supplier_id, status, ordering)

    def get_detail(
        self, template_id: int, supplier_account_id: int
    ) -> TemplateDetailResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        if not supplier:
            return TemplateDetailResult(ok=False, not_found=True)
        template, source_fields, mappings = self._templates.get_owned_template_detail(
            template_id, supplier.id
        )
        if not template:
            return TemplateDetailResult(ok=False, not_found=True)
        return TemplateDetailResult(
            ok=True,
            template=template,
            source_fields=source_fields,
            mappings=mappings,
        )

    def create(
        self,
        supplier_account_id: int,
        format: str,
        version: int,
        name: str,
        source_path: str,
        metadata: dict,
    ) -> TemplateResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        if not supplier:
            return TemplateResult(ok=False, not_found=True, error="Supplier not found")

        template = self._templates.create_template(
            supplier_id=supplier.id,
            format=format,
            version=version,
            name=name,
            metadata=metadata,
            source_path=source_path,
        )
        if template is None:
            return TemplateResult(
                ok=False,
                conflict=True,
                error=f"A {format} template already exists at version {version} for this supplier",
            )
        return TemplateResult(ok=True, template=template)

    def update(
        self, template_id: int, supplier_account_id: int, data: dict
    ) -> TemplateResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        if not supplier:
            return TemplateResult(ok=False, not_found=True)
        t = self._templates.get_owned_template(template_id, supplier.id)
        if not t:
            return TemplateResult(ok=False, not_found=True)
        if not self._templates.is_editable(t):
            return TemplateResult(
                ok=False,
                conflict=True,
                error=f"Template is {t.status} and cannot be edited",
            )

        updated = self._templates.update_template(template_id, data)
        return TemplateResult(ok=True, template=updated)
