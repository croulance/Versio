import io

from apps.transformation.mergers.xml_merger import XmlMerger


class FakeStorage:
    def __init__(self, objects: dict):
        self._objects = objects

    def get_object(self, key):
        return io.BytesIO(self._objects[key])


class TestXmlMerger:
    def test_strips_per_chunk_root_and_wraps_once(self):
        storage = FakeStorage(
            {
                "c1": b'<?xml version="1.0" encoding="UTF-8"?>\n<records>\n  <record><a>1</a></record>\n</records>',
                "c2": b'<?xml version="1.0" encoding="UTF-8"?>\n<records>\n  <record><a>2</a></record>\n</records>',
            }
        )
        merger = XmlMerger(storage)

        result = merger.merge(["c1", "c2"], metadata={}).decode("utf-8")

        assert result.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<records>')
        assert result.endswith("</records>")
        assert result.count("<records>") == 1
        assert result.count("</records>") == 1
        assert "<record><a>1</a></record>" in result
        assert "<record><a>2</a></record>" in result

    def test_custom_root_element(self):
        storage = FakeStorage(
            {
                "c1": b'<?xml version="1.0" encoding="UTF-8"?>\n<plots>\n  <record><a>1</a></record>\n</plots>',
            }
        )
        merger = XmlMerger(storage)

        result = merger.merge(["c1"], metadata={"root_element": "plots"}).decode(
            "utf-8"
        )

        assert result.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<plots>')
        assert result.endswith("</plots>")
