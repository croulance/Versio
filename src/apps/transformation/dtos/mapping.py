from dataclasses import dataclass


@dataclass(frozen=True)
class MappingSourceFieldRef:
    id: int
    name: str
    field_type: str
    path: str


@dataclass(frozen=True)
class MappingSnapshot:
    """Read-only, framework-free view of a FieldMapping."""

    id: int
    source_field: MappingSourceFieldRef
    target_field: str
    handler_method: str
    handler_data: dict
    order: int
    sheet_name: str | None = None

    @classmethod
    def from_model(cls, mapping) -> "MappingSnapshot":
        return cls(
            id=mapping.id,
            source_field=MappingSourceFieldRef(
                id=mapping.source_field_id,
                name=mapping.source_field.name,
                field_type=mapping.source_field.field_type,
                path=mapping.source_field.path,
            ),
            target_field=mapping.target_field,
            handler_method=mapping.handler_method,
            handler_data=mapping.handler_data,
            order=mapping.order,
            sheet_name=mapping.sheet_name,
        )
