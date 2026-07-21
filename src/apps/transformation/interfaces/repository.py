from abc import ABC, abstractmethod


class SupplierRepositoryInterface(ABC):
    @abstractmethod
    def get_all(self) -> list: ...

    @abstractmethod
    def get_by_account_id(self, supplier_account_id: int): ...

    @abstractmethod
    def get_or_create(self, supplier_account_id: int, name: str) -> tuple: ...


class TemplateRepositoryInterface(ABC):
    @abstractmethod
    def list_templates(
        self, supplier_id: int | None, status: str | None, ordering: str | None
    ) -> list:
        """Return a list of TemplateSnapshot, optionally filtered by supplier/status
        and sorted by `ordering` (a whitelisted field name, optionally prefixed with '-').
        """

    @abstractmethod
    def get_with_mappings_by_id(self, template_id: int):
        """Like get_template, but with field_mappings/source_fields prefetched, for chunk processing/merge."""

    @abstractmethod
    def get_or_create_template(
        self,
        supplier_id: int,
        format: str,
        version: int,
        name: str,
        metadata: dict,
        source_path: str = "",
    ) -> tuple: ...

    @abstractmethod
    def create_template(
        self,
        supplier_id: int,
        format: str,
        version: int,
        name: str,
        metadata: dict,
        source_path: str = "",
    ):
        """Create a genuinely new DRAFT template and return its TemplateSnapshot,
        or None if one already exists for this (supplier, format, version)."""

    @abstractmethod
    def replace_source_fields(self, template_id: int, fields: list[dict]) -> None:
        """
        Replace all SourceFieldDefinition rows for a template.
        Each dict must contain: name, field_type.
        Optional keys: required, nullable, default_value, max_length, allowed_values,
                       min_value, max_value, date_format, description, order.
        """

    @abstractmethod
    def get_source_fields(self, template_id: int) -> list:
        """Return top-level SourceFieldSnapshot only (parent is None), each with
        its nested schema (if any) in `.children`, ordered by `order` at every level."""

    @abstractmethod
    def serialize_source_fields(self, template) -> list:
        """Return top-level source field definitions as a list of plain dicts
        (cache-safe), each carrying its full dot-notation `path` and a nested
        `children` list of the same shape — mirrors SourceFieldSnapshot but as
        dicts, since this is what DynamicItemValidator consumes from cache."""

    @abstractmethod
    def replace_mappings(self, template_id: int, mappings: list[dict]) -> None:
        """
        Replace all FieldMapping rows for a template.
        Each dict must contain: source_field (name str), target_field, handler_method.
        Optional: handler_data, order.
        source_field is resolved to its SourceFieldDefinition FK internally.
        """

    @abstractmethod
    def serialize_mappings(self, template) -> list:
        """Return field mappings as a list of plain dicts (cache-safe)."""

    @abstractmethod
    def set_status(self, template_id: int, status: str):
        """Transition a template's lifecycle status (DRAFT/PUBLISHED/DEPRECATED) and
        return the updated TemplateSnapshot, or None if it no longer exists."""

    @abstractmethod
    def get_published_template_by_id(self, supplier_id: int, template_id: int):
        """Like get_with_mappings_by_id, but only returns the template if it belongs to
        supplier_id and its status is PUBLISHED — used to resolve a batch submission."""

    @abstractmethod
    def is_editable(self, template) -> bool:
        """True only when the template's status is DRAFT. Accepts anything with
        a `.status` attribute — a TemplateSnapshot in every current caller."""

    @abstractmethod
    def get_owned_template(self, template_id: int, supplier_id: int):
        """Fetch a single template by id, scoped to supplier_id, as a TemplateSnapshot —
        None if it doesn't exist or belongs to a different supplier. Callers must
        resolve supplier_account_id to supplier_id first (via SupplierRepository)."""

    @abstractmethod
    def get_owned_template_detail(self, template_id: int, supplier_id: int) -> tuple:
        """Like get_owned_template, plus its source fields/mappings serialized as
        plain dicts. Returns (TemplateSnapshot, list[dict], list[dict]), or
        (None, None, None) if it doesn't exist or belongs to a different supplier —
        the ORM instance never leaves this method."""

    @abstractmethod
    def update_template(self, template_id: int, data: dict):
        """Apply a partial update (name/source_path/metadata) and return the
        updated TemplateSnapshot, or None if it no longer exists."""

    @abstractmethod
    def get_owned_source_field(self, template_id: int, field_id: int, supplier_id: int):
        """Fetch a source field scoped to supplier_id via its owning template, as a
        SourceFieldSnapshot — None if it doesn't exist or its template belongs to a
        different supplier."""

    @abstractmethod
    def get_source_field_for_template(self, template_id: int, field_id: int):
        """Return a SourceFieldSnapshot, or None if it doesn't belong to template_id."""

    @abstractmethod
    def create_source_field(self, template_id: int, data: dict):
        """Return the created SourceFieldSnapshot. `data['parent_id']`, if present,
        nests this field under an existing 'object'-type field in the same template —
        callers must validate the parent's existence/type/template before calling this.
        """

    @abstractmethod
    def update_source_field(self, field_id: int, data: dict):
        """Return the updated SourceFieldSnapshot, or None if it no longer exists.
        `parent_id` is intentionally not editable here — reparenting isn't supported,
        only set at creation, to avoid cycle-detection complexity for no real use case.
        """

    @abstractmethod
    def delete_source_field(self, field_id: int) -> None:
        """Deletes this field and, via CASCADE, its entire subtree. Django's delete
        collector still enforces FieldMapping's PROTECT on every descendant first —
        the whole delete fails if any descendant (or the field itself) is mapped."""

    @abstractmethod
    def source_field_has_mappings(self, field_id: int) -> bool:
        """True if this field OR any descendant in its subtree has a FieldMapping —
        used to pre-empt the ProtectedError above with a clean 409 instead."""

    @abstractmethod
    def source_field_has_children(self, field_id: int) -> bool:
        """True if this field has at least one direct child — used to block changing
        field_type away from 'object' while a nested schema still depends on it."""

    @abstractmethod
    def list_mappings(self, template_id: int) -> list:
        """Return a list of MappingSnapshot, ordered by `order`."""

    @abstractmethod
    def get_owned_mapping(self, template_id: int, mapping_id: int, supplier_id: int):
        """Fetch a mapping scoped to supplier_id via its owning template, as a
        MappingSnapshot — None if it doesn't exist or its template belongs to a
        different supplier."""

    @abstractmethod
    def create_mapping(self, template_id: int, source_field_id: int, data: dict):
        """Return the created MappingSnapshot."""

    @abstractmethod
    def update_mapping(self, mapping_id: int, data: dict):
        """Return the updated MappingSnapshot, or None if it no longer exists."""

    @abstractmethod
    def delete_mapping(self, mapping_id: int) -> None: ...


class JobRepositoryInterface(ABC):
    @abstractmethod
    def create(
        self,
        supplier_id: int,
        template_id: int,
        format: str,
        storage_path: str,
        source_path: str,
        total_chunks: int,
        chunk_size: int,
        total_items: int = 0,
    ): ...

    @abstractmethod
    def get(self, job_id: str): ...

    @abstractmethod
    def increment_processed_chunks(self, job_id: str): ...

    @abstractmethod
    def increment_skipped_items(self, job_id: str, count: int): ...

    @abstractmethod
    def mark_done(self, job_id: str, output_storage_path: str): ...

    @abstractmethod
    def append_failed_chunk(self, job_id: str, chunk: dict): ...

    @abstractmethod
    def clear_failed_chunk(self, job_id: str, start: int, end: int): ...

    @abstractmethod
    def set_status(self, job_id: str, status: str): ...

    @abstractmethod
    def start_processing(self, job_id: str): ...

    @abstractmethod
    def reset(self, job_id: str): ...

    @abstractmethod
    def is_complete(self, job_id: str) -> bool: ...

    @abstractmethod
    def list_for_supplier(
        self,
        supplier_id: int,
        status: str | None,
        page: int,
        page_size: int,
        ordering: str | None = None,
    ) -> tuple:
        """Return (jobs, total_count) for a supplier, newest first by default, optionally
        filtered by status and sorted by `ordering` (a whitelisted field name, optionally
        prefixed with '-' for descending)."""

    @abstractmethod
    def list_stuck_pending(self, older_than_minutes: int) -> list:
        """PENDING jobs created more than older_than_minutes ago — never picked up by
        a worker (dispatch failure, queue purge, or workers being down), oldest first.
        """

    @abstractmethod
    def list_stuck_processing(self, older_than_minutes: int) -> list:
        """PROCESSING jobs whose started_at is older than older_than_minutes, oldest
        first — includes jobs stuck below total_chunks (a chunk task was likely lost)
        and jobs stuck at exactly total_chunks (merge never completed); the caller
        distinguishes the two to pick the right recovery action."""

    @abstractmethod
    def list_stuck_partial(self, older_than_minutes: int) -> list:
        """PARTIAL jobs whose oldest failed_chunks entry is older than
        older_than_minutes, oldest first."""

    @abstractmethod
    def mark_failed(self, job_id: str): ...
