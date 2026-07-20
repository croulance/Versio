from dataclasses import dataclass

from apps.transformation.dtos.template import TemplateSnapshot
from apps.transformation.enums import TemplateStatus
from apps.transformation.interfaces.repository import (
    SupplierRepositoryInterface, TemplateRepositoryInterface)


@dataclass(frozen=True)
class _Transition:
    required_status: TemplateStatus
    target_status: TemplateStatus
    verb: str


_TRANSITIONS = {
    "publish": _Transition(TemplateStatus.DRAFT, TemplateStatus.PUBLISHED, "published"),
    "deprecate": _Transition(
        TemplateStatus.PUBLISHED, TemplateStatus.DEPRECATED, "deprecated"
    ),
    "revert_to_draft": _Transition(
        TemplateStatus.PUBLISHED, TemplateStatus.DRAFT, "reverted to draft"
    ),
}


@dataclass
class LifecycleResult:
    ok: bool
    template: TemplateSnapshot | None = None
    not_found: bool = False
    error: str | None = None


class TemplateLifecycleService:
    """Enforces the DRAFT ⇄ PUBLISHED → DEPRECATED transition table."""

    def __init__(
        self,
        repository: TemplateRepositoryInterface,
        supplier_repository: SupplierRepositoryInterface,
    ):
        self._repo = repository
        self._suppliers = supplier_repository

    def publish(self, template_id: int, supplier_account_id: int) -> LifecycleResult:
        return self._transition(template_id, supplier_account_id, "publish")

    def deprecate(self, template_id: int, supplier_account_id: int) -> LifecycleResult:
        return self._transition(template_id, supplier_account_id, "deprecate")

    def revert_to_draft(
        self, template_id: int, supplier_account_id: int
    ) -> LifecycleResult:
        return self._transition(template_id, supplier_account_id, "revert_to_draft")

    def _transition(
        self, template_id: int, supplier_account_id: int, action: str
    ) -> LifecycleResult:
        supplier = self._suppliers.get_by_account_id(supplier_account_id)
        if not supplier:
            return LifecycleResult(ok=False, not_found=True)
        template = self._repo.get_owned_template(template_id, supplier.id)
        if not template:
            return LifecycleResult(ok=False, not_found=True)

        transition = _TRANSITIONS[action]
        if template.status != transition.required_status:
            return LifecycleResult(
                ok=False,
                error=(
                    f"Only {transition.required_status} templates can be "
                    f"{transition.verb} (current status: {template.status})"
                ),
            )

        updated = self._repo.set_status(template_id, transition.target_status)
        return LifecycleResult(ok=True, template=updated)
