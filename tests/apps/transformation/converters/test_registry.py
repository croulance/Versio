import pytest

import apps.transformation.converters  # noqa: F401 — registers all converters
import apps.transformation.handlers  # noqa: F401 — registers all handlers
from apps.transformation.converters.csv_converter import CSVConverter
from apps.transformation.converters.registry import (_registry, all_converters,
                                                     register_converter)
from apps.transformation.handlers.registry import all_handlers


class TestConverterRegistry:
    def test_all_converters_returns_one_fresh_map_each_call(self):
        handlers = all_handlers()
        first = all_converters(handlers)
        second = all_converters(handlers)
        assert isinstance(first["csv"], CSVConverter)
        assert first["csv"] is not second["csv"]  # each call builds new instances

    def test_register_converter_rejects_duplicate_format(self):
        class _Dummy:
            format = "__test_dummy_format__"

        register_converter(_Dummy)
        try:
            with pytest.raises(TypeError):
                register_converter(_Dummy)
        finally:
            _registry.pop("__test_dummy_format__", None)
