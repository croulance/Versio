from apps.transformation.services.guards import editable_conflict


class FakeTemplate:
    def __init__(self, status="DRAFT", supplier_id=1):
        self.status = status
        self.supplier_id = supplier_id


class FakeRepo:
    def __init__(self, is_editable):
        self._is_editable = is_editable

    def is_editable(self, template):
        return self._is_editable


class TestEditableConflict:
    def test_returns_none_when_template_is_editable(self):
        assert editable_conflict(FakeRepo(True), FakeTemplate("DRAFT")) is None

    def test_returns_error_message_naming_the_current_status_when_not_editable(self):
        error = editable_conflict(FakeRepo(False), FakeTemplate("PUBLISHED"))
        assert error == "Template is PUBLISHED and cannot be edited"
