from dataclasses import dataclass
from dataclasses import field as dataclass_field


@dataclass(frozen=True)
class SourceFieldSnapshot:
    """Read-only, framework-free view of a SourceFieldDefinition. `children` is
    populated only for 'object'-type fields that describe their nested keys —
    empty for every leaf field and for opaque 'object'/'geojson' fields with
    no declared schema (backward compatible with pre-nesting templates)."""

    id: int
    name: str
    field_type: str
    required: bool
    nullable: bool
    default_value: object
    max_length: int | None
    allowed_values: list
    min_value: float | None
    max_value: float | None
    date_format: str
    description: str
    order: int
    parent_id: int | None
    path: str
    children: list["SourceFieldSnapshot"] = dataclass_field(default_factory=list)

    @classmethod
    def from_model(
        cls, field, children: list | None = None, path: str | None = None
    ) -> "SourceFieldSnapshot":
        """`children`/`path` let bulk callers (repository tree-builders) pass
        pre-computed values from a single flat query instead of triggering a
        lazy `.children.all()`/`.parent` walk per node (N+1 avoidance). Omit
        both for a simple single-row fetch — they fall back to the ORM relation."""
        return cls(
            id=field.id,
            name=field.name,
            field_type=field.field_type,
            required=field.required,
            nullable=field.nullable,
            default_value=field.default_value,
            max_length=field.max_length,
            allowed_values=field.allowed_values or [],
            min_value=field.min_value,
            max_value=field.max_value,
            date_format=field.date_format,
            description=field.description,
            order=field.order,
            parent_id=field.parent_id,
            path=path if path is not None else field.path,
            children=(
                children
                if children is not None
                else [cls.from_model(c) for c in field.children.all()]
            ),
        )
