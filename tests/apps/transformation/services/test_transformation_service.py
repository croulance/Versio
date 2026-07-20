import io
import json

from django.conf import settings

from apps.transformation.services.transformation_service import \
    TransformationService


class FakeSupplier:
    def __init__(self, id):
        self.id = id


class FakeTemplate:
    def __init__(self, id, format, source_path=""):
        self.id = id
        self.format = format
        self.source_path = source_path


class FakeJob:
    def __init__(self, id):
        self.id = id


class FakeSupplierRepository:
    def __init__(self, supplier=None):
        self._supplier = supplier
        self.calls = []

    def get_by_account_id(self, supplier_account_id):
        self.calls.append(supplier_account_id)
        return self._supplier


class FakeTemplateRepository:
    def __init__(self, template=None):
        self._template = template
        self.calls = []

    def get_published_template_by_id(self, supplier_id, template_id):
        self.calls.append((supplier_id, template_id))
        return self._template


class FakeJobRepository:
    def __init__(self):
        self.created_with = None

    def create(self, **kwargs):
        self.created_with = kwargs
        return FakeJob(id="job-123")


class FakeCache:
    """reserve_idempotency mimics real SET-NX semantics: True only the first
    time it's called for a given key. A resolved job_id only becomes visible
    via get_idempotency_job_id after resolve_idempotency runs — mirrors the
    real adapter hiding its pending-placeholder sentinel."""

    def __init__(self, existing_job_id=None, already_reserved=False):
        self._job_id = existing_job_id
        self._reserved = already_reserved or existing_job_id is not None
        self.resolve_idempotency_calls = []
        self.release_idempotency_calls = []
        self.touch_idempotency_reservation_calls = []

    def build_idempotency_key(self, supplier_account_id, template_id, file_stream):
        return f"{supplier_account_id}:{template_id}"

    def get_idempotency_job_id(self, key):
        return self._job_id

    def reserve_idempotency(self, key, ttl):
        if self._reserved:
            return False
        self._reserved = True
        return True

    def touch_idempotency_reservation(self, key, ttl):
        self.touch_idempotency_reservation_calls.append((key, ttl))

    def resolve_idempotency(self, key, job_id, ttl):
        self.resolve_idempotency_calls.append((key, job_id, ttl))
        self._job_id = job_id

    def release_idempotency(self, key):
        self.release_idempotency_calls.append(key)
        self._reserved = False


class FakeStorage:
    def __init__(self):
        self.uploaded = []
        self.put_objects = {}  # key -> decoded items list, mirrors real put_object(key, bytes)
        self._objects = {}  # key -> raw bytes, so get_object() can serve back what was written

    def upload_stream(self, key, file_stream):
        self.uploaded.append(key)
        file_stream.seek(0)
        self._objects[key] = file_stream.read()

    def put_object(self, key, body):
        self.put_objects[key] = json.loads(body)
        self._objects[key] = body

    def get_object(self, key):
        return io.BytesIO(self._objects[key])


def _file(data: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(data).encode("utf-8"))


def _service(
    supplier=None, template=None, existing_job_id=None, already_reserved=False
):
    supplier_repo = FakeSupplierRepository(supplier)
    template_repo = FakeTemplateRepository(template)
    job_repo = FakeJobRepository()
    cache = FakeCache(existing_job_id, already_reserved)
    storage = FakeStorage()
    service = TransformationService(
        supplier_repository=supplier_repo,
        template_repository=template_repo,
        job_repository=job_repo,
        cache=cache,
        storage=storage,
    )
    return service, supplier_repo, template_repo, job_repo, cache, storage


class TestTransformationServiceSubmit:
    def test_duplicate_submission_short_circuits_before_any_lookup(self):
        service, supplier_repo, template_repo, job_repo, cache, storage = _service(
            existing_job_id="existing-job-1"
        )

        result = service.submit(199, 3, "batch.json", _file({"data": {"items": []}}))

        assert result.is_duplicate
        assert result.job_id == "existing-job-1"
        assert supplier_repo.calls == []
        assert job_repo.created_with is None
        assert storage.uploaded == []

    def test_concurrent_identical_submission_still_processing_is_not_a_duplicate_yet(
        self, monkeypatch
    ):
        # reserve_idempotency lost the race (already_reserved=True) but the
        # winner hasn't resolved it to a real job_id yet — must not hang past
        # IDEMPOTENCY_WAIT_TIMEOUT, and must not silently create a second job.
        monkeypatch.setattr(settings, "IDEMPOTENCY_WAIT_TIMEOUT", 0.05, raising=False)
        monkeypatch.setattr(
            settings, "IDEMPOTENCY_WAIT_POLL_INTERVAL", 0.01, raising=False
        )
        service, supplier_repo, template_repo, job_repo, cache, storage = _service(
            already_reserved=True
        )

        result = service.submit(199, 3, "batch.json", _file({"data": {"items": []}}))

        assert result.status.value == "invalid"
        assert supplier_repo.calls == []
        assert job_repo.created_with is None

    def test_concurrent_identical_submission_returns_winner_job_id_once_resolved(
        self, monkeypatch
    ):
        # Simulates the winner resolving the key mid-wait: get_idempotency_job_id
        # starts as None (pending) and flips to a real id on the second poll.
        supplier_repo = FakeSupplierRepository(None)
        template_repo = FakeTemplateRepository(None)
        job_repo = FakeJobRepository()
        cache = FakeCache(already_reserved=True)
        storage = FakeStorage()
        calls = {"n": 0}

        def flaky_get(key):
            calls["n"] += 1
            return "winner-job-1" if calls["n"] >= 2 else None

        monkeypatch.setattr(cache, "get_idempotency_job_id", flaky_get)
        monkeypatch.setattr(
            settings, "IDEMPOTENCY_WAIT_POLL_INTERVAL", 0.01, raising=False
        )
        service = TransformationService(
            supplier_repository=supplier_repo,
            template_repository=template_repo,
            job_repository=job_repo,
            cache=cache,
            storage=storage,
        )

        result = service.submit(199, 3, "batch.json", _file({"data": {"items": []}}))

        assert result.is_duplicate
        assert result.job_id == "winner-job-1"
        assert supplier_repo.calls == []

    def test_supplier_not_found(self):
        service, *_ = _service(supplier=None)

        result = service.submit(199, 3, "batch.json", _file({"data": {"items": []}}))

        assert not result.is_success
        assert result.status.value == "not_found"

    def test_supplier_not_found_releases_the_reservation(self):
        service, *_, cache, _ = _service(supplier=None)

        service.submit(199, 3, "batch.json", _file({"data": {"items": []}}))

        assert cache.release_idempotency_calls == ["199:3"]
        assert cache.resolve_idempotency_calls == []

    def test_template_not_found(self):
        service, *_ = _service(supplier=FakeSupplier(id=1), template=None)

        result = service.submit(199, 3, "batch.json", _file({"data": {"items": []}}))

        assert result.status.value == "not_found"

    def test_no_items_at_source_path_is_invalid(self):
        supplier = FakeSupplier(id=1)
        template = FakeTemplate(id=3, format="csv", source_path="data.items.item")
        service, *_ = _service(supplier=supplier, template=template)

        result = service.submit(199, 3, "batch.json", _file({"data": {"items": []}}))

        assert result.status.value == "invalid"

    def test_no_items_at_source_path_releases_the_reservation(self):
        supplier = FakeSupplier(id=1)
        template = FakeTemplate(id=3, format="csv", source_path="data.items.item")
        service, *_, cache, _ = _service(supplier=supplier, template=template)

        service.submit(199, 3, "batch.json", _file({"data": {"items": []}}))

        assert cache.release_idempotency_calls == ["199:3"]
        assert cache.resolve_idempotency_calls == []

    def test_successful_submission_creates_job_and_dispatches_split(self, monkeypatch):
        # submit() no longer splits/dispatches chunks itself -- that's
        # too slow to do inside the request, so it dispatches ONE async task
        # (split_and_dispatch_chunks) that does the split + per-chunk dispatch
        # in the background. See test_split_and_dispatch_chunks below for
        # coverage of what that task actually does.
        import apps.transformation.tasks.transform as transform_task

        dispatched = []
        monkeypatch.setattr(
            transform_task.split_and_dispatch_chunks,
            "apply_async",
            lambda args, queue: dispatched.append({"args": args, "queue": queue}),
        )

        supplier = FakeSupplier(id=1)
        template = FakeTemplate(id=3, format="csv", source_path="data.items.item")
        service, supplier_repo, template_repo, job_repo, cache, storage = _service(
            supplier=supplier, template=template
        )

        items = [{"producerName": f"P{i}"} for i in range(3)]
        result = service.submit(199, 3, "batch.json", _file({"data": {"items": items}}))

        assert result.is_success
        assert result.job_id == "job-123"
        assert job_repo.created_with["supplier_id"] == 1
        assert job_repo.created_with["template_id"] == 3
        assert job_repo.created_with["format"] == "csv"
        assert job_repo.created_with["source_path"] == "data.items.item"
        assert job_repo.created_with["total_chunks"] == 1  # 3 items << CHUNK_SIZE_MIN
        assert storage.uploaded  # source file was uploaded
        assert cache.resolve_idempotency_calls  # idempotency key resolved after success
        assert cache.release_idempotency_calls == []  # never released on success
        assert len(dispatched) == 1
        job_id, storage_path, source_path, chunk_size, template_id, format_ = dispatched[
            0
        ]["args"]
        assert job_id == "job-123"
        assert storage_path in storage.uploaded
        assert source_path == "data.items.item"
        assert chunk_size == settings.CHUNK_SIZE_MIN
        assert template_id == 3
        assert format_ == "csv"
        assert dispatched[0]["queue"] == settings.CELERY_MERGE_QUEUE

    def test_successful_submission_refreshes_the_reservation_at_both_slow_checkpoints(
        self, monkeypatch
    ):
        # Counting items and uploading the source file are the two steps
        # that can genuinely take a while for a large file -- the reservation
        # must be refreshed after each, not just relied on to survive from
        # the initial reserve_idempotency call, or a large enough file could
        # outlive IDEMPOTENCY_RESERVATION_TTL while still legitimately in
        # progress, letting a late-arriving duplicate slip past reserve_idempotency's
        # own SET NX once the stale key expires.
        import apps.transformation.tasks.transform as transform_task

        monkeypatch.setattr(
            transform_task.split_and_dispatch_chunks, "apply_async", lambda args, queue: None
        )

        supplier = FakeSupplier(id=1)
        template = FakeTemplate(id=3, format="csv", source_path="data.items.item")
        service, *_, cache, storage = _service(supplier=supplier, template=template)

        items = [{"producerName": f"P{i}"} for i in range(3)]
        service.submit(199, 3, "batch.json", _file({"data": {"items": items}}))

        assert cache.touch_idempotency_reservation_calls == [
            ("199:3", settings.IDEMPOTENCY_RESERVATION_TTL),
            ("199:3", settings.IDEMPOTENCY_RESERVATION_TTL),
        ]

    def test_split_and_dispatch_chunks_writes_and_dispatches_each_chunk(
        self, monkeypatch
    ):
        import apps.transformation.tasks.transform as transform_task

        dispatched = []
        monkeypatch.setattr(
            transform_task.process_chunk,
            "apply_async",
            lambda args, queue: dispatched.append({"args": args, "queue": queue}),
        )

        service, *_, storage = _service()
        storage._objects["src"] = _file(
            {"data": {"items": [{"producerName": f"P{i}"} for i in range(3)]}}
        ).read()

        service.split_and_dispatch_chunks(
            "job-123", "src", "data.items.item", 3, 3, "csv"
        )

        assert len(dispatched) == 1
        assert dispatched[0]["args"] == [
            "job-123",
            "inputs/job-123/chunks/0_2.json",
            0,
            2,
            3,
            "csv",
        ]
        assert dispatched[0]["queue"] == settings.CELERY_CHUNK_QUEUE
        assert storage.put_objects["inputs/job-123/chunks/0_2.json"] == [
            {"producerName": f"P{i}"} for i in range(3)
        ]

    def test_split_and_dispatch_chunks_handles_decimal_valued_fields(self, monkeypatch):
        # Regression test: ijson parses non-integer JSON numbers as
        # decimal.Decimal, not float -- json.dumps() chokes on that with a
        # TypeError unless split_and_dispatch_chunks explicitly handles it.
        # This bug doesn't show up with Fakes that skip real ijson parsing,
        # only with an actual float value flowing through the real parser.
        import apps.transformation.tasks.transform as transform_task

        monkeypatch.setattr(
            transform_task.process_chunk, "apply_async", lambda args, queue: None
        )

        service, *_, storage = _service()
        items = [{"producerName": "P1", "area": 12.75}]
        storage._objects["src"] = _file({"data": {"items": items}}).read()

        service.split_and_dispatch_chunks(
            "job-123", "src", "data.items.item", 1000, 3, "csv"
        )

        [written] = storage.put_objects.values()
        assert written == items

    def test_split_and_dispatch_chunks_one_task_per_chunk_size_boundary(
        self, monkeypatch
    ):
        import apps.transformation.tasks.transform as transform_task

        dispatched = []
        monkeypatch.setattr(
            transform_task.process_chunk,
            "apply_async",
            lambda args, queue: dispatched.append(args),
        )

        service, *_, storage = _service()
        total_items = settings.CHUNK_SIZE_MIN + 1
        items = [{"producerName": f"P{i}"} for i in range(total_items)]
        storage._objects["src"] = _file({"data": {"items": items}}).read()

        service.split_and_dispatch_chunks(
            "job-123", "src", "data.items.item", settings.CHUNK_SIZE_MIN, 3, "csv"
        )

        assert len(dispatched) == 2
        assert tuple(dispatched[0][2:4]) == (0, settings.CHUNK_SIZE_MIN - 1)
        assert tuple(dispatched[1][2:4]) == (settings.CHUNK_SIZE_MIN, total_items - 1)

    def test_configured_source_path_used_when_it_yields_items(self, monkeypatch):
        import apps.transformation.tasks.transform as transform_task

        monkeypatch.setattr(
            transform_task.process_chunk, "apply_async", lambda args, queue: None
        )

        supplier = FakeSupplier(id=1)
        template = FakeTemplate(id=3, format="csv", source_path="data.rows.item")
        service, _, _, job_repo, *_ = _service(supplier=supplier, template=template)

        result = service.submit(
            199,
            3,
            "batch.json",
            _file({"data": {"rows": [{"a": 1}], "items": []}}),
        )

        # configured path 'data.rows.item' has 1 item -> must not fall back to 'data.items.item' (0 items)
        assert result.is_success
        assert job_repo.created_with["source_path"] == "data.rows.item"

    def test_configured_source_path_is_only_counted_once(self, monkeypatch):
        # _resolve_source_path already does a full count pass to validate a
        # configured path yields items -- submit() must reuse that count
        # rather than paying for a second full parse of the same file.
        import apps.transformation.tasks.transform as transform_task

        monkeypatch.setattr(
            transform_task.process_chunk, "apply_async", lambda args, queue: None
        )

        supplier = FakeSupplier(id=1)
        template = FakeTemplate(id=3, format="csv", source_path="data.rows.item")
        service, _, _, job_repo, *_ = _service(supplier=supplier, template=template)

        original_count_items = service._count_items
        calls = []

        def counting_count_items(file_stream, source_path):
            calls.append(source_path)
            return original_count_items(file_stream, source_path)

        monkeypatch.setattr(service, "_count_items", counting_count_items)

        result = service.submit(
            199,
            3,
            "batch.json",
            _file({"data": {"rows": [{"a": 1}], "items": []}}),
        )

        assert result.is_success
        assert calls == ["data.rows.item"]

    def test_falls_back_to_auto_detection_when_configured_path_yields_nothing(
        self, monkeypatch
    ):
        import apps.transformation.tasks.transform as transform_task

        monkeypatch.setattr(
            transform_task.process_chunk, "apply_async", lambda args, queue: None
        )

        supplier = FakeSupplier(id=1)
        template = FakeTemplate(id=3, format="csv", source_path="data.wrong_key.item")
        service, _, _, job_repo, *_ = _service(supplier=supplier, template=template)

        result = service.submit(
            199,
            3,
            "batch.json",
            _file({"results": [{"a": 1}]}),
        )

        assert result.is_success
        assert job_repo.created_with["source_path"] == "results.item"


class TestCountItems:
    def test_malformed_json_returns_zero_and_logs_a_warning(self, caplog):
        service, *_ = _service()
        broken_stream = io.BytesIO(b'{"data": [invalid')

        with caplog.at_level("WARNING"):
            count = service._count_items(broken_stream, "data.item")

        assert count == 0
        assert "Item count failed" in caplog.text

    def test_valid_source_path_counts_without_logging(self, caplog):
        service, *_ = _service()

        with caplog.at_level("WARNING"):
            count = service._count_items(_file({"data": [{"a": 1}, {"a": 2}]}), "data.item")

        assert count == 2
        assert caplog.text == ""
