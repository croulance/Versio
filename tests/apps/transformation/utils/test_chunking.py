from apps.transformation.utils.chunking import chunk_input_key, compute_chunk_size


def test_targets_roughly_target_chunks_for_mid_range_sizes():
    # 80,000 / 8 = 10,000 exactly -- no clamping in play.
    assert compute_chunk_size(80_000, target_chunks=8, min_size=1000, max_size=40_000) == 10_000


def test_clamps_to_min_for_small_jobs_instead_of_over_fragmenting():
    # 100 / 8 = 12.5 -> would be a near-useless 13-item chunk without a floor.
    assert compute_chunk_size(100, target_chunks=8, min_size=1000, max_size=40_000) == 1000


def test_clamps_to_max_for_huge_jobs_to_bound_retry_blast_radius():
    # 10,000,000 / 8 = 1,250,000 -- unbounded, that's a single-chunk-sized job.
    assert (
        compute_chunk_size(10_000_000, target_chunks=8, min_size=1000, max_size=40_000)
        == 40_000
    )


def test_zero_items_returns_min_size_without_dividing_by_target():
    assert compute_chunk_size(0, target_chunks=8, min_size=1000, max_size=40_000) == 1000


def test_rounds_up_so_every_item_is_covered_by_some_chunk():
    # 8001 / 8 = 1000.125 -- must round up, or the 8th chunk misses the last item.
    size = compute_chunk_size(8001, target_chunks=8, min_size=1, max_size=40_000)
    assert size == 1001
    import math

    assert math.ceil(8001 / size) == 8


def test_chunk_input_key_is_deterministic_from_job_id_start_end():
    # The split step (write) and dispatch/retry (read) must derive the exact
    # same key from the same three values with no other state involved.
    assert chunk_input_key("job-1", 0, 999) == "inputs/job-1/chunks/0_999.json"
    assert chunk_input_key("job-1", 0, 999) == chunk_input_key("job-1", 0, 999)


def test_chunk_input_key_differs_for_different_ranges_of_the_same_job():
    a = chunk_input_key("job-1", 0, 999)
    b = chunk_input_key("job-1", 1000, 1999)
    assert a != b
