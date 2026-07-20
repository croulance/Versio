import pytest

import apps.transformation.mergers  # noqa: F401 — registers all mergers
from apps.transformation.mergers.csv_merger import CsvMerger
from apps.transformation.mergers.registry import (_registry, all_mergers,
                                                  register_merger)


class _FakeStorage:
    def get_object(self, key):
        raise AssertionError("not used in these tests")


class TestMergerRegistry:
    def test_all_mergers_injects_storage_and_returns_fresh_instances(self):
        storage = _FakeStorage()

        first = all_mergers(storage)
        second = all_mergers(storage)

        assert isinstance(first["csv"], CsvMerger)
        assert first["csv"] is not second["csv"]  # each call builds new instances
        assert first["csv"]._storage is storage  # the same storage instance is injected

    def test_all_formats_are_registered(self):
        storage = _FakeStorage()
        mergers = all_mergers(storage)
        assert set(mergers.keys()) == {"csv", "geojson", "xml", "xlsx", "errors"}

    def test_register_merger_rejects_duplicate_format(self):
        class _Dummy:
            format = "__test_dummy_format__"

        register_merger(_Dummy)
        try:
            with pytest.raises(TypeError):
                register_merger(_Dummy)
        finally:
            _registry.pop("__test_dummy_format__", None)
