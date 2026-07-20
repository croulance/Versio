from apps.transformation.services.source_field_service import \
    SourceFieldService


class FakeTemplate:
    def __init__(self, id=1, status="DRAFT", supplier_id=1):
        self.id = id
        self.status = status
        self.supplier_id = supplier_id


class FakeSourceField:
    def __init__(
        self,
        id=1,
        name="producerName",
        template=None,
        has_mappings=False,
        field_type="string",
    ):
        self.id = id
        self.name = name
        self.field_type = field_type
        self.required = True
        self.nullable = False
        self.default_value = None
        self.max_length = None
        self.allowed_values = []
        self.min_value = None
        self.max_value = None
        self.date_format = ""
        self.description = ""
        self.order = 0
        self.template = template or FakeTemplate()
        self._has_mappings = has_mappings


class FakeSupplier:
    def __init__(self, id=1):
        self.id = id


class FakeSupplierRepository:
    def __init__(self, supplier=None):
        self._supplier = supplier

    def get_by_account_id(self, supplier_account_id):
        return self._supplier


class FakeTemplateRepository:
    def __init__(
        self,
        template=None,
        fields=None,
        field=None,
        has_mappings=False,
        parent_field=None,
        has_children=False,
    ):
        # Default the owning template to the field's own template so update/delete
        # editability checks (which re-fetch by template_id) see a consistent object.
        self._template = template if template is not None else (
            field.template if field else None
        )
        self._fields = fields or []
        self._field = field
        self._has_mappings = has_mappings
        self._parent_field = parent_field
        self._has_children = has_children
        self.is_editable_result = True
        self.create_calls = []
        self.update_calls = []
        self.delete_calls = []

    def get_source_fields(self, template_id):
        return self._fields

    def get_source_field_for_template(self, template_id, field_id):
        p = self._parent_field
        if p and p.id == field_id:
            return p
        return None

    def source_field_has_children(self, field_id):
        return self._has_children

    def get_owned_template(self, template_id, supplier_id):
        t = self._template
        if t and t.id == template_id and t.supplier_id == supplier_id:
            return t
        return None

    def is_editable(self, template):
        return self.is_editable_result

    def create_source_field(self, template_id, data):
        self.create_calls.append(data)
        return FakeSourceField(id=99, name=data.get("name", ""))

    def get_owned_source_field(self, template_id, field_id, supplier_id):
        f = self._field
        if f and f.id == field_id and f.template.supplier_id == supplier_id:
            return f
        return None

    def update_source_field(self, field_id, data):
        self.update_calls.append(data)
        f = self._field
        if not f or f.id != field_id:
            return None
        for k, v in data.items():
            setattr(f, k, v)
        return f

    def source_field_has_mappings(self, field_id):
        return self._has_mappings

    def delete_source_field(self, field_id):
        self.delete_calls.append(field_id)


def _service(supplier=None, **kwargs):
    if supplier is None:
        supplier = FakeSupplier(id=1)
    repo = FakeTemplateRepository(**kwargs)
    supplier_repo = FakeSupplierRepository(supplier)
    return SourceFieldService(repository=repo, supplier_repository=supplier_repo), repo


class TestList:
    def test_template_not_found(self):
        service, _ = _service(template=None)
        result = service.list(1, 199)
        assert result.ok is False
        assert result.not_found is True

    def test_not_found_when_owned_by_a_different_supplier(self):
        service, _ = _service(
            supplier=FakeSupplier(id=2), template=FakeTemplate(id=1, supplier_id=1)
        )
        result = service.list(1, 199)
        assert result.ok is False
        assert result.not_found is True

    def test_returns_all_fields(self):
        service, _ = _service(
            template=FakeTemplate(id=1),
            fields=[FakeSourceField(id=1), FakeSourceField(id=2)],
        )
        result = service.list(1, 199)
        assert result.ok is True
        assert [f.id for f in result.fields] == [1, 2]


class TestCreate:
    def test_template_not_found(self):
        service, repo = _service(template=None)
        result = service.create(1, 199, {"name": "x"})
        assert result.ok is False
        assert result.not_found is True
        assert repo.create_calls == []

    def test_rejected_when_template_not_editable(self):
        service, repo = _service(template=FakeTemplate(id=1, status="PUBLISHED"))
        repo.is_editable_result = False

        result = service.create(1, 199, {"name": "producerName"})

        assert result.ok is False
        assert result.conflict is True
        assert "PUBLISHED" in result.error
        assert repo.create_calls == []

    def test_created_when_template_is_draft(self):
        service, repo = _service(template=FakeTemplate(id=1, status="DRAFT"))

        result = service.create(1, 199, {"name": "producerName"})

        assert result.ok is True
        assert result.field_item.name == "producerName"

    def test_parent_field_not_found(self):
        service, repo = _service(template=FakeTemplate(id=1, status="DRAFT"))

        result = service.create(1, 199, {"name": "label", "parent_id": 99})

        assert result.ok is False
        assert result.not_found is True
        assert result.error == "Parent field not found"
        assert repo.create_calls == []

    def test_parent_field_must_be_object_type(self):
        parent = FakeSourceField(id=5, field_type="string")
        service, repo = _service(
            template=FakeTemplate(id=1, status="DRAFT"), parent_field=parent
        )

        result = service.create(1, 199, {"name": "label", "parent_id": 5})

        assert result.ok is False
        assert result.conflict is True
        assert "must be of type 'object'" in result.error
        assert repo.create_calls == []

    def test_created_with_valid_object_parent(self):
        parent = FakeSourceField(id=5, field_type="object")
        service, repo = _service(
            template=FakeTemplate(id=1, status="DRAFT"), parent_field=parent
        )

        result = service.create(1, 199, {"name": "label", "parent_id": 5})

        assert result.ok is True
        assert repo.create_calls[0]["parent_id"] == 5


class TestUpdate:
    def test_field_not_found(self):
        service, repo = _service(field=None)
        result = service.update(1, 1, 199, {"name": "x"})
        assert result.ok is False
        assert result.not_found is True

    def test_not_found_when_owned_by_a_different_supplier(self):
        field = FakeSourceField(template=FakeTemplate(supplier_id=1))
        service, repo = _service(supplier=FakeSupplier(id=2), field=field)
        result = service.update(1, 1, 199, {"name": "x"})
        assert result.ok is False
        assert result.not_found is True
        assert repo.update_calls == []

    def test_rejected_when_owning_template_not_editable(self):
        field = FakeSourceField(template=FakeTemplate(status="PUBLISHED"))
        service, repo = _service(field=field)
        repo.is_editable_result = False

        result = service.update(1, 1, 199, {"name": "newName"})

        assert result.ok is False
        assert result.conflict is True
        assert repo.update_calls == []

    def test_updated_when_editable(self):
        field = FakeSourceField(template=FakeTemplate(status="DRAFT"))
        service, repo = _service(field=field)

        result = service.update(1, 1, 199, {"name": "newName"})

        assert result.ok is True
        assert result.field_item.name == "newName"

    def test_rejected_when_changing_type_away_from_object_with_children(self):
        field = FakeSourceField(
            field_type="object", template=FakeTemplate(status="DRAFT")
        )
        service, repo = _service(field=field, has_children=True)

        result = service.update(1, 1, 199, {"field_type": "string"})

        assert result.ok is False
        assert result.conflict is True
        assert "nested children" in result.error
        assert repo.update_calls == []

    def test_allowed_changing_type_away_from_object_without_children(self):
        field = FakeSourceField(
            field_type="object", template=FakeTemplate(status="DRAFT")
        )
        service, repo = _service(field=field, has_children=False)

        result = service.update(1, 1, 199, {"field_type": "string"})

        assert result.ok is True
        assert result.field_item.field_type == "string"

    def test_editing_other_attrs_on_object_field_with_children_is_unaffected(self):
        field = FakeSourceField(
            field_type="object", template=FakeTemplate(status="DRAFT")
        )
        service, repo = _service(field=field, has_children=True)

        result = service.update(1, 1, 199, {"description": "new description"})

        assert result.ok is True
        assert result.field_item.description == "new description"


class TestDelete:
    def test_field_not_found(self):
        service, repo = _service(field=None)
        result = service.delete(1, 1, 199)
        assert result.ok is False
        assert result.not_found is True

    def test_rejected_when_owning_template_not_editable(self):
        field = FakeSourceField(template=FakeTemplate(status="PUBLISHED"))
        service, repo = _service(field=field)
        repo.is_editable_result = False

        result = service.delete(1, 1, 199)

        assert result.ok is False
        assert result.conflict is True
        assert repo.delete_calls == []

    def test_rejected_when_has_children(self):
        field = FakeSourceField(
            id=7, field_type="object", template=FakeTemplate(status="DRAFT")
        )
        service, repo = _service(field=field, has_children=True)

        result = service.delete(1, 7, 199)

        assert result.ok is False
        assert result.conflict is True
        assert "nested children" in result.error
        assert repo.delete_calls == []

    def test_rejected_when_referenced_by_a_mapping(self):
        field = FakeSourceField(id=7, template=FakeTemplate(status="DRAFT"))
        service, repo = _service(field=field, has_mappings=True)

        result = service.delete(1, 7, 199)

        assert result.ok is False
        assert result.conflict is True
        assert "referenced by a mapping" in result.error
        assert repo.delete_calls == []

    def test_deleted_when_editable_and_unreferenced(self):
        field = FakeSourceField(id=7, template=FakeTemplate(status="DRAFT"))
        service, repo = _service(field=field, has_mappings=False)

        result = service.delete(1, 7, 199)

        assert result.ok is True
        assert repo.delete_calls == [7]
