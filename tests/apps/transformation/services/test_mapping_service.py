from apps.transformation.services.mapping_service import MappingService


class FakeTemplate:
    def __init__(self, id=1, status="DRAFT", supplier_id=1, format="csv"):
        self.id = id
        self.status = status
        self.supplier_id = supplier_id
        self.format = format


class FakeSourceField:
    def __init__(self, id=1, name="producerName", field_type="string", path=None):
        self.id = id
        self.name = name
        self.field_type = field_type
        self.path = path if path is not None else name


class FakeMapping:
    """source_field is a property, not a plain attribute, so that assigning
    it (as the real Django FK descriptor does) keeps source_field_id in sync —
    MappingSnapshot.from_model reads source_field_id, not source_field.id."""

    def __init__(
        self,
        id=1,
        template=None,
        source_field=None,
        target_field="Producer Name",
        sheet_name=None,
    ):
        self.id = id
        self.template = template or FakeTemplate()
        self.source_field = source_field or FakeSourceField()
        self.target_field = target_field
        self.handler_method = "direct"
        self.handler_data = {}
        self.order = 0
        self.sheet_name = sheet_name

    @property
    def source_field(self):
        return self._source_field

    @source_field.setter
    def source_field(self, value):
        self._source_field = value
        self.source_field_id = value.id


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
        mappings=None,
        mapping=None,
        source_field=None,
    ):
        # Default the owning template to the mapping's own template so update/delete
        # editability checks (which re-fetch by template_id) see a consistent object.
        self._template = template if template is not None else (
            mapping.template if mapping else None
        )
        self._mappings = mappings or []
        self._mapping = mapping
        self._source_field = source_field
        self.is_editable_result = True
        self.create_calls = []
        self.update_calls = []
        self.delete_calls = []

    def list_mappings(self, template_id):
        return self._mappings

    def get_owned_template(self, template_id, supplier_id):
        t = self._template
        if t and t.id == template_id and t.supplier_id == supplier_id:
            return t
        return None

    def is_editable(self, template):
        return self.is_editable_result

    def get_source_field_for_template(self, template_id, field_id):
        return self._source_field

    def create_mapping(self, template_id, source_field_id, data):
        self.create_calls.append(data)
        return FakeMapping(
            id=99,
            source_field=self._source_field,
            target_field=data.get("target_field", ""),
            sheet_name=data.get("sheet_name"),
        )

    def get_owned_mapping(self, template_id, mapping_id, supplier_id):
        m = self._mapping
        if m and m.id == mapping_id and m.template.supplier_id == supplier_id:
            return m
        return None

    def update_mapping(self, mapping_id, data):
        self.update_calls.append(data)
        m = self._mapping
        if not m or m.id != mapping_id:
            return None
        for k, v in data.items():
            if k == "source_field_id":
                m.source_field = self._source_field
            else:
                setattr(m, k, v)
        return m

    def delete_mapping(self, mapping_id):
        self.delete_calls.append(mapping_id)


def _service(supplier=None, **kwargs):
    if supplier is None:
        supplier = FakeSupplier(id=1)
    repo = FakeTemplateRepository(**kwargs)
    supplier_repo = FakeSupplierRepository(supplier)
    return MappingService(repository=repo, supplier_repository=supplier_repo), repo


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

    def test_returns_all_mappings(self):
        service, _ = _service(
            template=FakeTemplate(id=1),
            mappings=[FakeMapping(id=1), FakeMapping(id=2)],
        )
        result = service.list(1, 199)
        assert result.ok is True
        assert [m.id for m in result.mappings] == [1, 2]


class TestCreate:
    def test_template_not_found(self):
        service, repo = _service(template=None)
        result = service.create(1, 199, {"source_field_id": 1, "target_field": "x"})
        assert result.ok is False
        assert result.not_found is True
        assert repo.create_calls == []

    def test_rejected_when_template_not_editable(self):
        service, repo = _service(template=FakeTemplate(id=1, status="PUBLISHED"))
        repo.is_editable_result = False

        result = service.create(1, 199, {"source_field_id": 1, "target_field": "x"})

        assert result.ok is False
        assert result.conflict is True
        assert repo.create_calls == []

    def test_source_field_not_found(self):
        service, repo = _service(
            template=FakeTemplate(id=1, status="DRAFT"), source_field=None
        )

        result = service.create(1, 199, {"source_field_id": 999, "target_field": "x"})

        assert result.ok is False
        assert result.not_found is True
        assert result.error == "Source field not found"
        assert repo.create_calls == []

    def test_created_when_editable_and_source_field_exists(self):
        service, repo = _service(
            template=FakeTemplate(id=1, status="DRAFT"),
            source_field=FakeSourceField(id=1),
        )

        result = service.create(
            1, 199, {"source_field_id": 1, "target_field": "Producer Name"}
        )

        assert result.ok is True
        assert result.mapping.target_field == "Producer Name"

    def test_default_handler_data_uses_source_field_path_not_name(self):
        # A top-level field's path == its name, so this is unchanged for every
        # pre-existing, non-nested mapping — but a nested leaf's default must
        # address it by full dot-path (e.g. "complianceStatus.label").
        service, repo = _service(
            template=FakeTemplate(id=1, status="DRAFT"),
            source_field=FakeSourceField(
                id=1, name="label", path="complianceStatus.label"
            ),
        )

        service.create(1, 199, {"source_field_id": 1, "target_field": "Label"})

        assert repo.create_calls[0]["handler_data"] == {
            "field": "complianceStatus.label"
        }

    def test_explicit_handler_data_is_not_overridden(self):
        service, repo = _service(
            template=FakeTemplate(id=1, status="DRAFT"),
            source_field=FakeSourceField(id=1, path="complianceStatus.code"),
        )

        service.create(
            1,
            199,
            {
                "source_field_id": 1,
                "target_field": "Code",
                "handler_data": {"field": "customOverride"},
            },
        )

        assert repo.create_calls[0]["handler_data"] == {"field": "customOverride"}

    def test_xlsx_template_requires_sheet_name(self):
        service, repo = _service(
            template=FakeTemplate(id=1, status="DRAFT", format="xlsx"),
            source_field=FakeSourceField(id=1),
        )

        result = service.create(
            1, 199, {"source_field_id": 1, "target_field": "Producer Name"}
        )

        assert result.ok is False
        assert result.conflict is True
        assert "sheet_name" in result.error
        assert repo.create_calls == []

    def test_xlsx_template_with_sheet_name_is_created(self):
        service, repo = _service(
            template=FakeTemplate(id=1, status="DRAFT", format="xlsx"),
            source_field=FakeSourceField(id=1),
        )

        result = service.create(
            1,
            199,
            {
                "source_field_id": 1,
                "target_field": "Producer Name",
                "sheet_name": "Identity",
            },
        )

        assert result.ok is True
        assert result.mapping.sheet_name == "Identity"

    def test_non_xlsx_template_does_not_require_sheet_name(self):
        service, repo = _service(
            template=FakeTemplate(id=1, status="DRAFT", format="csv"),
            source_field=FakeSourceField(id=1),
        )

        result = service.create(
            1, 199, {"source_field_id": 1, "target_field": "Producer Name"}
        )

        assert result.ok is True


class TestUpdate:
    def test_mapping_not_found(self):
        service, repo = _service(mapping=None)
        result = service.update(1, 1, 199, {"target_field": "x"})
        assert result.ok is False
        assert result.not_found is True

    def test_not_found_when_owned_by_a_different_supplier(self):
        mapping = FakeMapping(template=FakeTemplate(supplier_id=1))
        service, repo = _service(supplier=FakeSupplier(id=2), mapping=mapping)
        result = service.update(1, 1, 199, {"target_field": "x"})
        assert result.ok is False
        assert result.not_found is True
        assert repo.update_calls == []

    def test_rejected_when_owning_template_not_editable(self):
        mapping = FakeMapping(template=FakeTemplate(status="PUBLISHED"))
        service, repo = _service(mapping=mapping)
        repo.is_editable_result = False

        result = service.update(1, 1, 199, {"target_field": "y"})

        assert result.ok is False
        assert result.conflict is True
        assert repo.update_calls == []

    def test_changing_source_field_to_an_unknown_id_is_not_found(self):
        mapping = FakeMapping(template=FakeTemplate(status="DRAFT"))
        service, repo = _service(mapping=mapping, source_field=None)

        result = service.update(1, 1, 199, {"source_field_id": 999})

        assert result.ok is False
        assert result.not_found is True

    def test_updated_when_editable(self):
        mapping = FakeMapping(template=FakeTemplate(status="DRAFT"), target_field="Old")
        service, repo = _service(mapping=mapping)

        result = service.update(1, 1, 199, {"target_field": "New"})

        assert result.ok is True
        assert result.mapping.target_field == "New"

    def test_updated_source_field_reference_is_swapped(self):
        mapping = FakeMapping(
            template=FakeTemplate(status="DRAFT"), source_field=FakeSourceField(id=1)
        )
        new_field = FakeSourceField(id=2, name="area")
        service, repo = _service(mapping=mapping, source_field=new_field)

        result = service.update(1, 1, 199, {"source_field_id": 2})

        assert result.ok is True
        assert result.mapping.source_field.id == 2

    def test_xlsx_mapping_cannot_be_updated_to_drop_its_sheet_name(self):
        mapping = FakeMapping(
            template=FakeTemplate(status="DRAFT", format="xlsx"),
            sheet_name="Identity",
        )
        service, repo = _service(mapping=mapping)

        result = service.update(1, 1, 199, {"sheet_name": ""})

        assert result.ok is False
        assert result.conflict is True
        assert repo.update_calls == []

    def test_xlsx_mapping_update_keeps_its_existing_sheet_name_if_untouched(self):
        # Updating an unrelated field must not require re-sending sheet_name
        # -- the existing stored value is what gets validated.
        mapping = FakeMapping(
            template=FakeTemplate(status="DRAFT", format="xlsx"),
            sheet_name="Identity",
            target_field="Old",
        )
        service, repo = _service(mapping=mapping)

        result = service.update(1, 1, 199, {"target_field": "New"})

        assert result.ok is True
        assert repo.update_calls == [{"target_field": "New"}]


class TestDelete:
    def test_mapping_not_found(self):
        service, repo = _service(mapping=None)
        result = service.delete(1, 1, 199)
        assert result.ok is False
        assert result.not_found is True

    def test_rejected_when_owning_template_not_editable(self):
        mapping = FakeMapping(id=5, template=FakeTemplate(status="PUBLISHED"))
        service, repo = _service(mapping=mapping)
        repo.is_editable_result = False

        result = service.delete(1, 5, 199)

        assert result.ok is False
        assert result.conflict is True
        assert repo.delete_calls == []

    def test_deleted_when_editable(self):
        mapping = FakeMapping(id=5, template=FakeTemplate(status="DRAFT"))
        service, repo = _service(mapping=mapping)

        result = service.delete(1, 5, 199)

        assert result.ok is True
        assert repo.delete_calls == [5]
