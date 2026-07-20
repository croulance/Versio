# Versio

A stateless data interoperability service. A supplier uploads one dataset in a fixed source schema; Versio transforms it into whatever target format (GeoJSON, CSV, XML, XLSX) each downstream platform needs, via field mappings the supplier configures themselves.

**Brief's three required goals**, all implemented: store the submitted data, handle large datasets efficiently, let the user pick the target format dynamically. **Both stretch goals**, also implemented: accept arbitrary input data (auto-detect the array of items in an uploaded file, no hardcoded path) and let suppliers edit their own target templates (the dashboard's mapping editor).

## How it works

1. Supplier uploads a file + picks a published template → `POST /transform`.
2. Versio streams the file straight to S3 (never fully in memory), creates a `TransformationJob`, and returns a `job_id` immediately.
3. The file is split into chunks (size scaled to the file) and processed async, in parallel, via Celery.
4. Each chunk is validated/converted item-by-item; a bad item is skipped and logged, not fatal to the chunk.
5. Once every chunk is done, chunk outputs are merged into one final file per format.
6. Supplier polls `GET /jobs/{job_id}/` for status, then downloads the result.

Three components share one database but deploy independently: **API** (business logic), **Auth** (supplier sessions), **Dashboard** (HTMX backoffice, no database of its own — proxies the other two).

## Key decisions

| Area | Problem | Solution |
|---|---|---|
| Architecture | Domain logic needs to stay testable with no DB/S3/HTTP, and infra needs to be swappable | Hexagonal: one interface + one adapter per external dependency (Redis, S3, converters, mergers, handlers), injected, never looked up |
| Ingestion | A large file can't be fully loaded into memory | Stream straight to S3, parse with `ijson` as a generator — memory is O(chunk size), not O(dataset) |
| Chunk sizing | One flat chunk size is wrong for both a 500-item and a 500,000-item file | Computed per job (~8 chunks, clamped min/max), calibrated against real stress-test timings |
| Splitting & dispatch | Splitting inline on the request path roughly doubled response latency | One Celery task does the split *and* dispatches every chunk task, off the request path |
| Coordination | Dedup, per-chunk locking, and caching all need one fast store | Redis for all three — accepted single point of coordination failure over running a second infra piece |
| Auth | Dashboard needs revocable sessions without OAuth/JWT overkill for the scope | Opaque database-backed token; cache-aside lookup (cached for ~10 seconds) inside the auth service |
| Mapping lifecycle | A batch shouldn't run against a mapping that's mid-edit | `DRAFT ⇄ PUBLISHED → DEPRECATED` — only `PUBLISHED` is submittable, and becomes read-only |
| Job status | Four call sites writing `job.status` directly caused a real bug (`PARTIAL` silently flipping back to `PROCESSING` on an unrelated chunk) | One `JobLifecycleService`, one method per event, no direct writes anywhere else |
| Item failures | One bad item shouldn't take down its whole chunk | Skip + record position/reason to a per-chunk file, merged at the end into a downloadable errors report |
| Ownership | A shared internal service token alone can't prove *which* supplier a request is acting for | Every read/write filters ownership into the query itself, never fetch-then-compare — identical `404` for "not yours" and "doesn't exist" |
| Dashboard | No need to duplicate business rules in a thin proxy layer | No database, no domain logic — pure proxy + form rendering |
| Nested source fields | An `object`-typed field needs a real schema, not just an opaque blob | Self-referential `parent` reference on `SourceFieldDefinition` — arbitrary nesting depth, addressable by dot-path |
| XLSX sheets | Sheet name lived in template metadata, decoupled from the column mapping — ambiguous which sheet a column belonged to | `sheet_name` moved onto `FieldMapping` itself, required per mapping on an xlsx template |
| Idempotency window | A large file's count/upload step can legitimately outlast the dedup reservation's expiry, letting a late genuine duplicate slip through | Refresh the reservation's expiry at each real checkpoint instead of guessing one duration upfront |

## Known limitations (by design, not oversight)

- No webhook on job completion — status is pull-only. Shelved: only useful for direct-API suppliers, not the dashboard flow, and needs more scoping.
- Job listing uses OFFSET/LIMIT pagination. An index on `(supplier, -created_at)` keeps the common case fast; keyset pagination would be needed if job history grows very large.

## Project structure

```
src/apps/transformation/   Core domain
  interfaces/                 Ports: cache, storage, converter, merger, handler, repository
  services/                   TransformationService, ChunkProcessingService, MergeService, template/mapping create-read-update-delete
  converters/, mergers/, handlers/   One class per format/handler, decorator registry, wired in by the factory
  cache/, storage/             Adapters over infrastructure/ clients (RedisClient, S3Client)
  repositories/, models.py     Database access, confined here only
  factories/                   The only place concrete adapters meet the services/registries that consume them
  dtos/, validators/, views/, tasks/
src/infrastructure/        Generic technology clients (RedisClient, S3Client) — no domain knowledge
src/apps/supplier_auth/    Independent auth service (opaque session tokens, permissions)
src/apps/dashboard/        Thin HTMX proxy layer — no database, proxies the two APIs above
tests/                     Mirrors src/ — pytest, run inside Docker (see "Run the tests")
```

## How to develop / maintain this project

### Run it locally

Requires Docker and Docker Compose.

```bash
cp .env.example .env
make build
make dev   # starts everything, migrates, seeds demo data, prints URLs + test login
```

This starts:

| Service | URL | Purpose |
|---------|-----|---------|
| `api` | http://localhost:8000 | Transformation API (submit batches, poll job status) |
| `auth` | http://localhost:8002 | Supplier authentication service |
| `dashboard` | http://localhost:8001 | Mapping editor + batch submission user UI |
| `db` (Postgres) | localhost:5432 | `versio` / `versio` / `versio` (db/user/password) |
| RabbitMQ management | http://localhost:15672 | `versio` / `versio` |
| MinIO console | http://localhost:9001 | `versio` / `versio123` (S3-compatible storage) |

Each of the three HTTP services runs under gunicorn with its own isolated WSGI entrypoint and settings module — never Django's dev server, never a shared entrypoint.

`./src` is bind-mounted, so edits show up immediately — but gunicorn/Celery don't hot-reload. After changing code:

```bash
docker compose restart api                     # view/service/serializer changes
docker compose restart worker worker-default   # anything the Celery tasks import
```

`make api/bash` / `make api/shell` (Django `shell_plus`) for a REPL; `make logs`, `make api/logs`, `make worker/logs`, `make worker-default/logs` to tail output. `make help` lists everything.

A supplier account is created via the auth service's Django admin (`http://localhost:8002/admin/`) — no self-registration, by design.

### Run the tests

Targets Python 3.12 (uses `match`/`case`); tests run inside the `shell` container to avoid a host version mismatch:

```bash
make test
```

| Area | What's covered |
|------|-----------------|
| Handlers | All 5 field handlers, dot-path walking, the handler registry |
| Converters | CSV/GeoJSON/XML/XLSX `convert_item` + stream framing, converter registry |
| Mergers | Each merger's `merge()` against a fake storage, including `ErrorsMerger` (per-item skip-trace files), merger registry |
| Validator | Absence/default/nullability handling, type coercion, constraints, recursive nested-object validation |
| Services | Every service, every branch (not-found, conflicts, lifecycle transitions, idempotency, cross-supplier ownership) against hand-written fakes — no DB or network |
| Tasks | `process_chunk`/`merge_output` Celery tasks via `.apply(throw=True)` against a stubbed factory — retry-vs-no-retry decisions |
| Security | Internal-service auth and per-job ownership checks, against fakes |
| Architecture | Parses each service file's source code (without running it) to forbid `django.*`/`rest_framework.*` imports or direct model access inside `services/` |

### Format code

```bash
make format   # black + isort, run inside the api container
```

### Extending the system

- **New output format** — `converters/<format>_converter.py` (`ConverterInterface`, `@register_converter`) + `mergers/<format>_merger.py` (`MergerInterface`, `@register_merger`) + add the choice to `TargetTemplate.Format` + migrate. Nothing else changes — new formats plug into the existing registries without modifying any of them.
- **New field handler** — `handlers/<name>_handler.py` implementing `FieldHandler.apply()`, decorated `@register_handler`. Immediately usable as a `FieldMapping.handler_method` value.
- **Swap storage or cache backend** — implement `StorageInterface` or `CacheAdapterInterface` against the new backend, point the factory at it. No service/view changes.
- **New source field type** — add the choice to `SourceFieldDefinition.FieldType` + migrate, add a case to `DynamicItemValidator._coerce`/`_check_constraints`. For nested shapes on an `object` field, no new type needed — just child rows with `parent_id` set.
- **New API endpoint** — plain `Serializer` → service method (repositories passed in as constructor arguments, returns a plain data object) → factory → `InternalAPIView` (zero business logic). Ownership-scoped resources go through `get_owned_*` repository methods, never an unscoped lookup.
