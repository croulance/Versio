import math


def compute_chunk_size(
    total_items: int, target_chunks: int, min_size: int, max_size: int
) -> int:
    """
    Items per chunk for a job of this size, aimed at landing near
    `target_chunks` chunks — clamped to [min_size, max_size].

    Calibrated empirically against an earlier cost model, where every
    chunk task re-parsed the source file from the start up to its own offset
    — total wasted work grew with chunk *count*, so target_chunks=8 favored
    fewer, larger chunks. That redundant re-parse was later removed entirely
    (chunks now read their own pre-split file), which makes this calibration
    stale: per-chunk cost no longer depends on chunk count the same way, so
    target_chunks likely wants to be higher now (more, smaller chunks, for
    more parallelism) — not yet re-measured.
    """
    if total_items <= min_size:
        return min_size
    raw = math.ceil(total_items / target_chunks)
    return max(min_size, min(raw, max_size))


def chunk_input_key(job_id: str, start: int, end: int) -> str:
    """
    Deterministic storage key for one chunk's pre-split input file — never
    stored, always recomputed from (job_id, start, end) so the split step
    (write) and dispatch/retry (read) can never drift out of sync. Input
    chunk files are never deleted, same as this codebase's existing,
    unchanged behavior for output chunk files — so retry can always
    re-derive and re-read a chunk's original data, long after the job
    finished or failed.
    """
    return f"inputs/{job_id}/chunks/{start}_{end}.json"


def final_errors_key(job_id: str) -> str:
    """
    Deterministic storage key for a job's single merged skip-trace file
    — unlike the main output, whose key varies by format and is
    stored on the job (`output_storage_path`), this one is the same shape
    for every job regardless of target format, so it's cheaper to derive
    than to store. Shared between MergeService (writes it) and
    JobDownloadErrorsView (reads it) so the two can't drift apart.
    """
    return f"outputs/{job_id}/final.errors.json"
