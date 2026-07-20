import apps.transformation.views.job as job_module
from apps.transformation.views.job import owns_job


class FakeJob:
    def __init__(self, supplier_id=1):
        self.supplier_id = supplier_id


class FakeSupplier:
    def __init__(self, id):
        self.id = id


class FakeSupplierRepository:
    def __init__(self, supplier=None):
        self._supplier = supplier

    def get_by_account_id(self, supplier_account_id):
        return self._supplier


def _patch_supplier_repository(monkeypatch, supplier):
    """owns_job constructs SupplierRepository() itself rather than taking it
    via DI (it's a module-level view helper, not a service) — patch the name
    job.py imported so the real ORM/DB is never touched."""
    monkeypatch.setattr(job_module, "SupplierRepository", lambda: FakeSupplierRepository(supplier))


class TestOwnsJob:
    def test_true_when_account_id_resolves_to_the_owning_supplier(self, monkeypatch):
        _patch_supplier_repository(monkeypatch, FakeSupplier(id=1))
        assert owns_job(FakeJob(supplier_id=1), 199) is True

    def test_false_when_account_id_resolves_to_a_different_supplier(self, monkeypatch):
        _patch_supplier_repository(monkeypatch, FakeSupplier(id=2))
        assert owns_job(FakeJob(supplier_id=1), 199) is False

    def test_false_when_supplier_account_id_is_missing(self, monkeypatch):
        _patch_supplier_repository(monkeypatch, FakeSupplier(id=1))
        assert owns_job(FakeJob(supplier_id=1), None) is False
        assert owns_job(FakeJob(supplier_id=1), "") is False

    def test_false_when_supplier_account_id_is_not_numeric(self, monkeypatch):
        _patch_supplier_repository(monkeypatch, FakeSupplier(id=1))
        assert owns_job(FakeJob(supplier_id=1), "not-a-number") is False

    def test_false_when_account_id_does_not_resolve_to_any_supplier(self, monkeypatch):
        _patch_supplier_repository(monkeypatch, None)
        assert owns_job(FakeJob(supplier_id=1), 199) is False

    def test_string_account_id_matching_a_real_query_param_still_works(self, monkeypatch):
        # request.query_params.get(...) always returns a str, never an int
        _patch_supplier_repository(monkeypatch, FakeSupplier(id=1))
        assert owns_job(FakeJob(supplier_id=1), "199") is True
