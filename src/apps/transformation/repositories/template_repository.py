from django.db import IntegrityError, transaction

from apps.transformation.dtos.mapping import MappingSnapshot
from apps.transformation.dtos.source_field import SourceFieldSnapshot
from apps.transformation.dtos.template import TemplateSnapshot
from apps.transformation.interfaces.repository import \
    TemplateRepositoryInterface
from apps.transformation.models import (FieldMapping, SourceFieldDefinition,
                                        TargetTemplate)


class TemplateRepository(TemplateRepositoryInterface):

    ORDERABLE_FIELDS = {"name", "format", "version", "status"}

    def list_templates(
        self,
        supplier_id: int | None = None,
        status: str | None = None,
        ordering: str | None = None,
    ) -> list:
        qs = TargetTemplate.objects.select_related("supplier")
        if supplier_id:
            qs = qs.filter(supplier_id=supplier_id)
        if status:
            qs = qs.filter(status=status)

        field = (ordering or "").lstrip("-")
        if field in self.ORDERABLE_FIELDS:
            qs = qs.order_by(ordering, "supplier__name")
        else:
            qs = qs.order_by("supplier__name", "format", "version")

        return [TemplateSnapshot.from_model(t) for t in qs]

    def get_with_mappings_by_id(self, template_id: int) -> TargetTemplate | None:
        try:
            return TargetTemplate.objects.prefetch_related(
                "field_mappings__source_field", "source_fields"
            ).get(pk=template_id)
        except TargetTemplate.DoesNotExist:
            return None

    def get_published_template_by_id(
        self, supplier_id: int, template_id: int
    ) -> TargetTemplate | None:
        try:
            return TargetTemplate.objects.prefetch_related(
                "field_mappings__source_field", "source_fields"
            ).get(
                pk=template_id,
                supplier_id=supplier_id,
                status=TargetTemplate.Status.PUBLISHED,
            )
        except TargetTemplate.DoesNotExist:
            return None

    def set_status(self, template_id: int, status: str) -> TemplateSnapshot | None:
        try:
            template = TargetTemplate.objects.select_related("supplier").get(
                pk=template_id
            )
        except TargetTemplate.DoesNotExist:
            return None
        template.status = status
        template.save(update_fields=["status", "updated_at"])
        return TemplateSnapshot.from_model(template)

    def is_editable(self, template) -> bool:
        return template.status == TargetTemplate.Status.DRAFT

    def get_or_create_template(
        self,
        supplier_id: int,
        format: str,
        version: int,
        name: str,
        metadata: dict,
        source_path: str = "",
    ) -> tuple:
        return TargetTemplate.objects.get_or_create(
            supplier_id=supplier_id,
            format=format,
            version=version,
            name=name,
            defaults={"metadata": metadata, "source_path": source_path},
        )

    def create_template(
        self,
        supplier_id: int,
        format: str,
        version: int,
        name: str,
        metadata: dict,
        source_path: str = "",
    ) -> TemplateSnapshot | None:
        try:
            with transaction.atomic():
                template = TargetTemplate.objects.create(
                    supplier_id=supplier_id,
                    format=format,
                    version=version,
                    name=name,
                    metadata=metadata,
                    source_path=source_path,
                )
        except IntegrityError:
            return None
        return TemplateSnapshot.from_model(template)

    # ------------------------------------------------------------------
    # Source field definitions
    # ------------------------------------------------------------------

    def replace_source_fields(self, template_id: int, fields: list[dict]) -> None:
        # Mappings reference source fields via PROTECT FK — must go first
        FieldMapping.objects.filter(template_id=template_id).delete()
        SourceFieldDefinition.objects.filter(template_id=template_id).delete()
        SourceFieldDefinition.objects.bulk_create(
            [
                SourceFieldDefinition(
                    template_id=template_id,
                    name=f["name"],
                    field_type=f.get(
                        "field_type", SourceFieldDefinition.FieldType.STRING
                    ),
                    required=f.get("required", True),
                    nullable=f.get("nullable", False),
                    default_value=f.get("default_value"),
                    max_length=f.get("max_length"),
                    allowed_values=f.get("allowed_values", []),
                    min_value=f.get("min_value"),
                    max_value=f.get("max_value"),
                    date_format=f.get("date_format", ""),
                    description=f.get("description", ""),
                    order=f.get("order", i),
                )
                for i, f in enumerate(fields)
            ]
        )
        # Keep the counter in sync so a later single create_source_field() call
        # continues the sequence instead of colliding with these orders.
        TargetTemplate.objects.filter(pk=template_id).update(
            next_source_field_order=len(fields)
        )

    def get_source_fields(self, template_id: int) -> list:
        rows = list(
            SourceFieldDefinition.objects.filter(template_id=template_id).order_by(
                "order"
            )
        )
        return self._build_source_field_tree(rows)

    def _build_source_field_tree(self, rows: list) -> list:
        """Group a flat list of SourceFieldDefinition rows (any depth) into a
        top-level list of SourceFieldSnapshot with nested `.children` — one
        query total regardless of nesting depth, no per-node N+1."""
        by_parent: dict = {}
        for f in rows:
            by_parent.setdefault(f.parent_id, []).append(f)

        def snapshot(f, parent_path: str = "") -> SourceFieldSnapshot:
            path = f"{parent_path}.{f.name}" if parent_path else f.name
            return SourceFieldSnapshot.from_model(
                f,
                path=path,
                children=[snapshot(c, path) for c in by_parent.get(f.id, [])],
            )

        return [snapshot(f) for f in by_parent.get(None, [])]

    def serialize_source_fields(self, template: TargetTemplate) -> list:
        by_parent: dict = {}
        for f in template.source_fields.all():
            by_parent.setdefault(f.parent_id, []).append(f)

        def serialize(f, parent_path: str = "") -> dict:
            path = f"{parent_path}.{f.name}" if parent_path else f.name
            return {
                "name": f.name,
                "field_type": f.field_type,
                "required": f.required,
                "nullable": f.nullable,
                "default_value": f.default_value,
                "max_length": f.max_length,
                "allowed_values": f.allowed_values or [],
                "min_value": f.min_value,
                "max_value": f.max_value,
                "date_format": f.date_format,
                "description": f.description,
                "order": f.order,
                "path": path,
                "children": [serialize(c, path) for c in by_parent.get(f.id, [])],
            }

        return [serialize(f) for f in by_parent.get(None, [])]

    # ------------------------------------------------------------------
    # Field mappings
    # ------------------------------------------------------------------

    def replace_mappings(self, template_id: int, mappings: list[dict]) -> None:
        field_defs = {
            fd.name: fd
            for fd in SourceFieldDefinition.objects.filter(template_id=template_id)
        }
        FieldMapping.objects.filter(template_id=template_id).delete()
        FieldMapping.objects.bulk_create(
            [
                FieldMapping(
                    template_id=template_id,
                    source_field=field_defs[m["source_field"]],
                    target_field=m["target_field"],
                    handler_method=m.get("handler_method", "direct"),
                    handler_data=m.get("handler_data", {}),
                    order=m.get("order", i),
                    sheet_name=m.get("sheet_name"),
                )
                for i, m in enumerate(mappings)
            ]
        )
        # Keep the counter in sync so a later single create_mapping() call
        # continues the sequence instead of colliding with these orders.
        TargetTemplate.objects.filter(pk=template_id).update(
            next_mapping_order=len(mappings)
        )

    def serialize_mappings(self, template: TargetTemplate) -> list:
        return [
            {
                "source_field": m.source_field.name,
                "target_field": m.target_field,
                "handler_method": m.handler_method,
                "handler_data": m.handler_data,
                "order": m.order,
                "sheet_name": m.sheet_name,
            }
            for m in template.field_mappings.all()
        ]

    # ------------------------------------------------------------------
    # Individual source field CRUD
    # ------------------------------------------------------------------

    def get_owned_template(
        self, template_id: int, supplier_id: int
    ) -> TemplateSnapshot | None:
        try:
            template = TargetTemplate.objects.select_related("supplier").get(
                pk=template_id, supplier_id=supplier_id
            )
        except TargetTemplate.DoesNotExist:
            return None
        return TemplateSnapshot.from_model(template)

    def get_owned_template_detail(self, template_id: int, supplier_id: int) -> tuple:
        try:
            template = (
                TargetTemplate.objects.select_related("supplier")
                .prefetch_related("source_fields", "field_mappings__source_field")
                .get(pk=template_id, supplier_id=supplier_id)
            )
        except TargetTemplate.DoesNotExist:
            return None, None, None
        return (
            TemplateSnapshot.from_model(template),
            self.serialize_source_fields(template),
            self.serialize_mappings(template),
        )

    def update_template(self, template_id: int, data: dict) -> TemplateSnapshot | None:
        try:
            template = TargetTemplate.objects.select_related("supplier").get(
                pk=template_id
            )
        except TargetTemplate.DoesNotExist:
            return None
        for attr in ("name", "source_path", "metadata"):
            if attr in data:
                setattr(template, attr, data[attr])
        template.save()
        return TemplateSnapshot.from_model(template)

    def _next_order(self, template_id: int, counter_field: str) -> int:
        """Atomically claims the next order value from a per-template counter —
        a single locked PK lookup + update (O(1)), instead of COUNT()-ing the
        child rows (O(r)) on every create."""
        with transaction.atomic():
            locked = TargetTemplate.objects.select_for_update().get(pk=template_id)
            order = getattr(locked, counter_field)
            setattr(locked, counter_field, order + 1)
            locked.save(update_fields=[counter_field])
        return order

    def get_owned_source_field(
        self, template_id: int, field_id: int, supplier_id: int
    ) -> SourceFieldSnapshot | None:
        try:
            f = SourceFieldDefinition.objects.get(
                pk=field_id, template_id=template_id, template__supplier_id=supplier_id
            )
        except SourceFieldDefinition.DoesNotExist:
            return None
        return SourceFieldSnapshot.from_model(f)

    def create_source_field(self, template_id: int, data: dict) -> SourceFieldSnapshot:
        order = self._next_order(template_id, "next_source_field_order")
        f = SourceFieldDefinition.objects.create(
            template_id=template_id,
            parent_id=data.get("parent_id"),
            name=data.get("name", ""),
            field_type=data.get("field_type", SourceFieldDefinition.FieldType.STRING),
            required=data.get("required", True),
            nullable=data.get("nullable", False),
            default_value=data.get("default_value"),
            max_length=data.get("max_length"),
            allowed_values=data.get("allowed_values", []),
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            date_format=data.get("date_format", ""),
            description=data.get("description", ""),
            order=order,
        )
        return SourceFieldSnapshot.from_model(f)

    def update_source_field(
        self, field_id: int, data: dict
    ) -> SourceFieldSnapshot | None:
        try:
            f = SourceFieldDefinition.objects.get(pk=field_id)
        except SourceFieldDefinition.DoesNotExist:
            return None
        for attr in (
            "name",
            "field_type",
            "required",
            "nullable",
            "default_value",
            "max_length",
            "allowed_values",
            "min_value",
            "max_value",
            "date_format",
            "description",
            "order",
        ):
            if attr in data:
                setattr(f, attr, data[attr])
        f.save()
        return SourceFieldSnapshot.from_model(f)

    def delete_source_field(self, field_id: int) -> None:
        SourceFieldDefinition.objects.filter(pk=field_id).delete()

    def source_field_has_mappings(self, field_id: int) -> bool:
        return FieldMapping.objects.filter(
            source_field_id__in=self._collect_subtree_ids([field_id])
        ).exists()

    def source_field_has_children(self, field_id: int) -> bool:
        return SourceFieldDefinition.objects.filter(parent_id=field_id).exists()

    def _collect_subtree_ids(self, ids: list) -> list:
        """BFS over parent_id, one query per depth level (not per node) — ids
        plus every descendant, for operations that must consider a whole subtree."""
        all_ids = list(ids)
        frontier = ids
        while frontier:
            children = list(
                SourceFieldDefinition.objects.filter(
                    parent_id__in=frontier
                ).values_list("id", flat=True)
            )
            if not children:
                break
            all_ids.extend(children)
            frontier = children
        return all_ids

    # ------------------------------------------------------------------
    # Individual mapping CRUD
    # ------------------------------------------------------------------

    def list_mappings(self, template_id: int) -> list:
        return [
            MappingSnapshot.from_model(m)
            for m in FieldMapping.objects.filter(template_id=template_id)
            .select_related("source_field")
            .order_by("order")
        ]

    def get_owned_mapping(
        self, template_id: int, mapping_id: int, supplier_id: int
    ) -> MappingSnapshot | None:
        try:
            m = FieldMapping.objects.select_related("source_field").get(
                pk=mapping_id,
                template_id=template_id,
                template__supplier_id=supplier_id,
            )
        except FieldMapping.DoesNotExist:
            return None
        return MappingSnapshot.from_model(m)

    def get_source_field_for_template(
        self, template_id: int, field_id: int
    ) -> SourceFieldSnapshot | None:
        try:
            f = SourceFieldDefinition.objects.get(pk=field_id, template_id=template_id)
        except SourceFieldDefinition.DoesNotExist:
            return None
        return SourceFieldSnapshot.from_model(f)

    def create_mapping(
        self,
        template_id: int,
        source_field_id: int,
        data: dict,
    ) -> MappingSnapshot:
        order = self._next_order(template_id, "next_mapping_order")
        m = FieldMapping.objects.create(
            template_id=template_id,
            source_field_id=source_field_id,
            target_field=data.get("target_field", ""),
            handler_method=data.get("handler_method", "direct"),
            handler_data=data.get("handler_data", {}),
            order=order,
            sheet_name=data.get("sheet_name"),
        )
        m = FieldMapping.objects.select_related("source_field").get(pk=m.pk)
        return MappingSnapshot.from_model(m)

    def update_mapping(self, mapping_id: int, data: dict) -> MappingSnapshot | None:
        try:
            m = FieldMapping.objects.get(pk=mapping_id)
        except FieldMapping.DoesNotExist:
            return None
        for attr in (
            "source_field_id",
            "target_field",
            "handler_method",
            "handler_data",
            "order",
            "sheet_name",
        ):
            if attr in data:
                setattr(m, attr, data[attr])
        m.save()
        m = FieldMapping.objects.select_related("source_field").get(pk=mapping_id)
        return MappingSnapshot.from_model(m)

    def delete_mapping(self, mapping_id: int) -> None:
        FieldMapping.objects.filter(pk=mapping_id).delete()
