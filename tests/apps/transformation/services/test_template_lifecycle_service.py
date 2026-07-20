from apps.transformation.services.template_lifecycle_service import \
    TemplateLifecycleService


class FakeSupplierRef:
    id = 1
    name = "Peru Country 006"


class FakeTemplate:
    def __init__(self, id=1, status="DRAFT", supplier_id=1):
        self.id = id
        self.name = "CSV Export"
        self.format = "csv"
        self.version = 1
        self.source_path = ""
        self.metadata = {}
        self.status = status
        self.supplier_id = supplier_id
        self.supplier = FakeSupplierRef()


class FakeSupplier:
    def __init__(self, id=1):
        self.id = id


class FakeSupplierRepository:
    def __init__(self, supplier=None):
        self._supplier = supplier

    def get_by_account_id(self, supplier_account_id):
        return self._supplier


class FakeTemplateRepository:
    def __init__(self, template=None):
        self._template = template
        self.set_status_calls = []

    def get_owned_template(self, template_id, supplier_id):
        t = self._template
        if t and t.id == template_id and t.supplier_id == supplier_id:
            return t
        return None

    def set_status(self, template_id, status):
        self.set_status_calls.append(status)
        t = self._template
        if not t or t.id != template_id:
            return None
        t.status = status
        return t


def _service(template=None, supplier=None):
    if supplier is None and template is not None:
        supplier = FakeSupplier(id=template.supplier_id)
    repo = FakeTemplateRepository(template)
    supplier_repo = FakeSupplierRepository(supplier)
    return TemplateLifecycleService(repository=repo, supplier_repository=supplier_repo), repo


class TestPublish:
    def test_not_found(self):
        service, repo = _service(template=None, supplier=FakeSupplier(id=1))
        result = service.publish(1, 199)
        assert result.ok is False
        assert result.not_found is True

    def test_not_found_when_owned_by_a_different_supplier(self):
        service, repo = _service(
            template=FakeTemplate(status="DRAFT", supplier_id=1),
            supplier=FakeSupplier(id=2),
        )
        result = service.publish(1, 199)
        assert result.ok is False
        assert result.not_found is True
        assert repo.set_status_calls == []

    def test_draft_can_be_published(self):
        service, repo = _service(template=FakeTemplate(status="DRAFT"))
        result = service.publish(1, 199)
        assert result.ok is True
        assert result.template.status == "PUBLISHED"
        assert repo.set_status_calls == ["PUBLISHED"]

    def test_already_published_cannot_be_republished(self):
        service, repo = _service(template=FakeTemplate(status="PUBLISHED"))
        result = service.publish(1, 199)
        assert result.ok is False
        assert "DRAFT" in result.error
        assert "PUBLISHED" in result.error
        assert repo.set_status_calls == []

    def test_deprecated_cannot_be_published(self):
        service, repo = _service(template=FakeTemplate(status="DEPRECATED"))
        result = service.publish(1, 199)
        assert result.ok is False
        assert repo.set_status_calls == []


class TestDeprecate:
    def test_published_can_be_deprecated(self):
        service, repo = _service(template=FakeTemplate(status="PUBLISHED"))
        result = service.deprecate(1, 199)
        assert result.ok is True
        assert result.template.status == "DEPRECATED"

    def test_draft_cannot_be_deprecated(self):
        service, repo = _service(template=FakeTemplate(status="DRAFT"))
        result = service.deprecate(1, 199)
        assert result.ok is False
        assert repo.set_status_calls == []

    def test_deprecated_cannot_be_deprecated_again(self):
        service, repo = _service(template=FakeTemplate(status="DEPRECATED"))
        result = service.deprecate(1, 199)
        assert result.ok is False


class TestRevertToDraft:
    def test_published_can_be_reverted(self):
        service, repo = _service(template=FakeTemplate(status="PUBLISHED"))
        result = service.revert_to_draft(1, 199)
        assert result.ok is True
        assert result.template.status == "DRAFT"

    def test_draft_cannot_be_reverted(self):
        service, repo = _service(template=FakeTemplate(status="DRAFT"))
        result = service.revert_to_draft(1, 199)
        assert result.ok is False

    def test_deprecated_is_terminal_and_cannot_be_reverted(self):
        service, repo = _service(template=FakeTemplate(status="DEPRECATED"))
        result = service.revert_to_draft(1, 199)
        assert result.ok is False
        assert repo.set_status_calls == []
