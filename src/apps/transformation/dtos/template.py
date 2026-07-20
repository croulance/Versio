from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateSupplierRef:
    id: int
    name: str


@dataclass(frozen=True)
class TemplateSnapshot:
    """Read-only, framework-free view of a TargetTemplate for service/view
    consumption — lets services report on a template without importing the
    Django model."""

    id: int
    name: str
    format: str
    version: int
    source_path: str
    metadata: dict
    status: str
    supplier_id: int
    supplier: TemplateSupplierRef

    @classmethod
    def from_model(cls, template) -> "TemplateSnapshot":
        return cls(
            id=template.id,
            name=template.name,
            format=template.format,
            version=template.version,
            source_path=template.source_path,
            metadata=template.metadata,
            status=template.status,
            supplier_id=template.supplier_id,
            supplier=TemplateSupplierRef(
                id=template.supplier.id, name=template.supplier.name
            ),
        )
