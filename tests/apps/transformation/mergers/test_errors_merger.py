import io
import json

from apps.transformation.mergers.errors_merger import ErrorsMerger


class FakeStorage:
    def __init__(self, objects: dict):
        self._objects = objects

    def get_object(self, key):
        return io.BytesIO(self._objects[key])


class TestErrorsMerger:
    def test_concatenates_skip_entries_from_every_chunk(self):
        storage = FakeStorage(
            {
                "c1": json.dumps(
                    [{"position": 0, "error": "validation: required"}]
                ).encode("utf-8"),
                "c2": json.dumps(
                    [{"position": 5, "error": "conversion: boom"}]
                ).encode("utf-8"),
            }
        )
        merger = ErrorsMerger(storage)

        result = merger.merge(["c1", "c2"], metadata={})

        assert json.loads(result) == [
            {"position": 0, "error": "validation: required"},
            {"position": 5, "error": "conversion: boom"},
        ]

    def test_single_chunk_with_no_skips_merges_to_empty_list(self):
        storage = FakeStorage({"c1": b"[]"})
        merger = ErrorsMerger(storage)

        result = merger.merge(["c1"], metadata={})

        assert json.loads(result) == []

    def test_reads_chunks_in_given_order(self):
        storage = FakeStorage(
            {
                "c1": json.dumps([{"position": 0, "error": "first"}]).encode("utf-8"),
                "c2": json.dumps([{"position": 0, "error": "second"}]).encode("utf-8"),
                "c3": json.dumps([{"position": 0, "error": "third"}]).encode("utf-8"),
            }
        )
        merger = ErrorsMerger(storage)

        result = merger.merge(["c3", "c1", "c2"], metadata={})

        assert [e["error"] for e in json.loads(result)] == ["third", "first", "second"]
