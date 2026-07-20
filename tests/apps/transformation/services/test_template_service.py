from apps.transformation.services.template_service import TemplateService


class FakeSupplierRef:
    def __init__(self, id=1, name="Peru Country 006"):
        self.id = id
        self.name = name


class FakeTemplate:
    def __init__(
        self, id=1, status="DRAFT", format="csv", version=1, name="CSV Export", supplier_id=1
    ):
        self.id = id
        self.name = name
        self.format = format
        self.version = version
        self.source_path = ""
        self.metadata = {}
        self.status = status
        self.supplier_id = supplier_id
        self.supplier = FakeSupplierRef(id=supplier_id)


class FakeSupplier:
    def __init__(self, id=1):
        self.id = id


class FakeSupplierRepository:
    def __init__(self, supplier=None):
        self._supplier = supplier

    def get_by_account_id(self, supplier_account_id):
        return self._supplier


class FakeTemplateRepository:
    """get_owned_* mimic the real repository: return None unless both the id
    and supplier_id match, same as the real `.get(pk=..., supplier_id=...)` query."""

    def __init__(
        self,
        templates=None,
        template=None,
        detail_template="use_template",
        create_returns="use_template",
    ):
        self._templates = templates or []
        self._template = template
        self._detail_template = (
            template if detail_template == "use_template" else detail_template
        )
        self._create_returns = create_returns
        self.update_calls = []
        self.create_calls = []

    def list_templates(self, supplier_id, status, ordering):
        return self._templates

    def get_owned_template_detail(self, template_id, supplier_id):
        t = self._detail_template
        if t and t.id == template_id and t.supplier_id == supplier_id:
            return (
                t,
                [{"name": "producerName"}],
                [{"target_field": "Producer Name"}],
            )
        return None, None, None

    def create_template(self, **kwargs):
        self.create_calls.append(kwargs)
        if self._create_returns == "use_template":
            return self._template
        return self._create_returns  # None to simulate a duplicate conflict

    def get_owned_template(self, template_id, supplier_id):
        t = self._template
        if t and t.id == template_id and t.supplier_id == supplier_id:
            return t
        return None

    def is_editable(self, template):
        return template.status == "DRAFT"

    def update_template(self, template_id, data):
        self.update_calls.append(data)
        t = self._template
        if not t or t.id != template_id:
            return None
        for k, v in data.items():
            setattr(t, k, v)
        return t


def _service(
    supplier=None,
    templates=None,
    template=None,
    detail_template="use_template",
    create_returns="use_template",
):
    supplier_repo = FakeSupplierRepository(supplier)
    template_repo = FakeTemplateRepository(
        templates, template, detail_template, create_returns
    )
    return (
        TemplateService(
            template_repository=template_repo, supplier_repository=supplier_repo
        ),
        template_repo,
    )


class TestList:
    def test_returns_snapshots_for_every_template(self):
        service, _ = _service(templates=[FakeTemplate(id=1), FakeTemplate(id=2)])
        result = service.list(supplier_id=None, status=None, ordering=None)
        assert [t.id for t in result] == [1, 2]

    def test_empty_list(self):
        service, _ = _service(templates=[])
        assert service.list(None, None, None) == []


class TestGetDetail:
    def test_not_found(self):
        service, _ = _service(
            supplier=FakeSupplier(id=1), template=None, detail_template=None
        )
        result = service.get_detail(1, 199)
        assert result.ok is False
        assert result.not_found is True

    def test_found_includes_source_fields_and_mappings(self):
        service, _ = _service(
            supplier=FakeSupplier(id=1), template=FakeTemplate(id=1, supplier_id=1)
        )
        result = service.get_detail(1, 199)
        assert result.ok is True
        assert result.template.id == 1
        assert result.source_fields == [{"name": "producerName"}]
        assert result.mappings == [{"target_field": "Producer Name"}]

    def test_not_found_when_owned_by_a_different_supplier(self):
        service, _ = _service(
            supplier=FakeSupplier(id=2),  # a different supplier than the template's
            template=FakeTemplate(id=1, supplier_id=1),
        )
        result = service.get_detail(1, 199)
        assert result.ok is False
        assert result.not_found is True

    def test_not_found_when_supplier_account_id_does_not_resolve(self):
        service, _ = _service(
            supplier=None, template=FakeTemplate(id=1, supplier_id=1)
        )
        result = service.get_detail(1, 999)
        assert result.ok is False
        assert result.not_found is True


class TestCreate:
    def test_supplier_not_found(self):
        service, repo = _service(supplier=None)
        result = service.create(199, "csv", 1, "My Template", "", {})
        assert result.ok is False
        assert result.not_found is True
        assert repo.create_calls == []

    def test_successful_create(self):
        template = FakeTemplate(id=5, format="csv", version=1)
        service, repo = _service(supplier=FakeSupplier(id=1), template=template)

        result = service.create(
            199, "csv", 1, "My Template", "data.items.item", {"headers": []}
        )

        assert result.ok is True
        assert result.template.id == 5
        assert repo.create_calls[0]["supplier_id"] == 1
        assert repo.create_calls[0]["format"] == "csv"
        assert repo.create_calls[0]["version"] == 1

    def test_duplicate_format_version_is_a_conflict(self):
        service, repo = _service(supplier=FakeSupplier(id=1), create_returns=None)

        result = service.create(199, "csv", 1, "My Template", "", {})

        assert result.ok is False
        assert result.conflict is True
        assert "csv" in result.error
        assert "version 1" in result.error


class TestUpdate:
    def test_not_found(self):
        service, _ = _service(supplier=FakeSupplier(id=1), template=None)
        result = service.update(1, 199, {"name": "New name"})
        assert result.ok is False
        assert result.not_found is True

    def test_not_found_when_owned_by_a_different_supplier(self):
        service, repo = _service(
            supplier=FakeSupplier(id=2), template=FakeTemplate(id=1, supplier_id=1)
        )
        result = service.update(1, 199, {"name": "New name"})
        assert result.ok is False
        assert result.not_found is True
        assert repo.update_calls == []

    def test_published_template_cannot_be_updated(self):
        service, repo = _service(
            supplier=FakeSupplier(id=1),
            template=FakeTemplate(id=1, supplier_id=1, status="PUBLISHED"),
        )
        result = service.update(1, 199, {"name": "New name"})
        assert result.ok is False
        assert result.conflict is True
        assert "PUBLISHED" in result.error
        assert repo.update_calls == []

    def test_draft_template_can_be_updated(self):
        service, repo = _service(
            supplier=FakeSupplier(id=1),
            template=FakeTemplate(id=1, supplier_id=1, status="DRAFT", name="Old name"),
        )
        result = service.update(1, 199, {"name": "New name"})
        assert result.ok is True
        assert result.template.name == "New name"
