import io

from apps.transformation.mergers.csv_merger import CsvMerger


class FakeStorage:
    def __init__(self, objects: dict):
        self._objects = objects

    def get_object(self, key):
        return io.BytesIO(self._objects[key])


class TestCsvMerger:
    def test_joins_chunks_and_dedupes_header(self):
        storage = FakeStorage(
            {
                "c1": b"Name,Area\nAcme,12.5",
                "c2": b"Name,Area\nBeta,8.0",
            }
        )
        merger = CsvMerger(storage)

        result = merger.merge(["c1", "c2"], metadata={})

        assert result == b"Name,Area\nAcme,12.5\nBeta,8.0"

    def test_single_chunk_keeps_header(self):
        storage = FakeStorage({"c1": b"Name,Area\nAcme,12.5"})
        merger = CsvMerger(storage)

        result = merger.merge(["c1"], metadata={})

        assert result == b"Name,Area\nAcme,12.5"

    def test_reads_chunks_in_given_order(self):
        storage = FakeStorage(
            {
                "c1": b"Name\nFirst",
                "c2": b"Name\nSecond",
                "c3": b"Name\nThird",
            }
        )
        merger = CsvMerger(storage)

        result = merger.merge(["c3", "c1", "c2"], metadata={})

        assert result == b"Name\nThird\nFirst\nSecond"
