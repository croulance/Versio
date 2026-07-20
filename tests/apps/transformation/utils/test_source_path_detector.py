import io

from apps.transformation.utils.source_path_detector import detect_source_path


def _stream(raw: bytes) -> io.BytesIO:
    return io.BytesIO(raw)


def test_finds_the_first_array_of_objects():
    assert detect_source_path(_stream(b'{"data": {"items": [{"id": 1}]}}')) == "data.items.item"


def test_skips_primitive_arrays_in_favor_of_an_array_of_objects():
    assert (
        detect_source_path(_stream(b'{"tags": ["a", "b"], "rows": [{"id": 1}]}'))
        == "rows.item"
    )


def test_no_array_of_objects_returns_none():
    assert detect_source_path(_stream(b'{"tags": ["a", "b"]}')) is None


def test_malformed_json_returns_none_and_logs_a_warning(caplog):
    with caplog.at_level("WARNING"):
        result = detect_source_path(_stream(b'{"data": [invalid'))

    assert result is None
    assert "Source path detection failed" in caplog.text


def test_valid_input_does_not_log_a_warning(caplog):
    with caplog.at_level("WARNING"):
        detect_source_path(_stream(b'{"data": {"items": [{"id": 1}]}}'))

    assert caplog.text == ""
