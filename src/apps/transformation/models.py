import uuid

from django.db import models

from apps.transformation.enums import JobStatus, TemplateStatus


class Supplier(models.Model):
    supplier_account_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "supplier"

    def __str__(self):
        return f"{self.name} ({self.supplier_account_id})"


class TargetTemplate(models.Model):
    class Format(models.TextChoices):
        GEOJSON = "geojson", "GeoJSON"
        CSV = "csv", "CSV"
        XML = "xml", "XML"
        XLSX = "xlsx", "XLSX"

    class Status(models.TextChoices):
        DRAFT = TemplateStatus.DRAFT.value, "Draft"
        PUBLISHED = TemplateStatus.PUBLISHED.value, "Published"
        DEPRECATED = TemplateStatus.DEPRECATED.value, "Deprecated"

    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, related_name="templates"
    )
    format = models.CharField(max_length=16, choices=Format.choices)
    version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    source_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ijson path to source items (e.g. 'data.items.item'). Auto-detected if blank.",
    )
    metadata = models.JSONField(default=dict, blank=True)
    next_source_field_order = models.PositiveIntegerField(
        default=0,
        help_text="Next order value to assign on create_source_field; avoids a COUNT query per create.",
    )
    next_mapping_order = models.PositiveIntegerField(
        default=0,
        help_text="Next order value to assign on create_mapping; avoids a COUNT query per create.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "target_template"
        unique_together = ("supplier", "name", "format", "version")

    def __str__(self):
        return f"{self.name} [{self.format}] — {self.supplier.name}"


class SourceFieldDefinition(models.Model):
    """
    Describes one field of the source schema for a given TargetTemplate.
    Drives dynamic validation of incoming items before transformation.
    """

    class FieldType(models.TextChoices):
        STRING = "string", "String"
        NUMBER = "number", "Number (float)"
        INTEGER = "integer", "Integer"
        BOOLEAN = "boolean", "Boolean"
        DATE = "date", "Date"
        DATETIME = "datetime", "Datetime"
        GEOJSON = "geojson", "GeoJSON geometry"
        OBJECT = "object", "Nested object"
        EMAIL = "email", "Email"
        URL = "url", "URL"

    template = models.ForeignKey(
        TargetTemplate, on_delete=models.CASCADE, related_name="source_fields"
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        help_text="Set only when this field describes a key nested inside an "
        "'object'-type field. The parent must itself be field_type=object.",
    )
    name = models.CharField(
        max_length=255, help_text="Field name as it appears in the source data."
    )
    field_type = models.CharField(
        max_length=16, choices=FieldType.choices, default=FieldType.STRING
    )
    required = models.BooleanField(
        default=True, help_text="Item is rejected if this field is absent."
    )
    nullable = models.BooleanField(
        default=False, help_text="Value may be null/empty even when field is present."
    )
    default_value = models.JSONField(
        null=True, blank=True, help_text="Used when field is absent and not required."
    )

    # String / enum constraints
    max_length = models.PositiveIntegerField(null=True, blank=True)
    allowed_values = models.JSONField(
        default=list,
        blank=True,
        help_text="Non-empty list = enum; value must be in list.",
    )

    # Numeric constraints
    min_value = models.FloatField(null=True, blank=True)
    max_value = models.FloatField(null=True, blank=True)

    # Date / datetime constraints
    date_format = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="strptime format; blank = ISO 8601.",
    )

    description = models.CharField(max_length=512, blank=True, default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "source_field_definition"
        unique_together = ("template", "parent", "name")
        ordering = ["order"]

    @property
    def path(self) -> str:
        """Dot-notation address into the raw item, e.g. 'complianceStatus.label'
        for a child of an 'object'-type field. Equals `name` for top-level fields."""
        return f"{self.parent.path}.{self.name}" if self.parent_id else self.name

    def __str__(self):
        flags = []
        if self.required:
            flags.append("required")
        if self.nullable:
            flags.append("nullable")
        suffix = f" ({', '.join(flags)})" if flags else " (optional)"
        return f"{self.path} [{self.field_type}]{suffix}"


class FieldMapping(models.Model):
    template = models.ForeignKey(
        TargetTemplate, on_delete=models.CASCADE, related_name="field_mappings"
    )
    source_field = models.ForeignKey(
        SourceFieldDefinition, on_delete=models.PROTECT, related_name="mappings"
    )
    target_field = models.CharField(max_length=255)
    handler_method = models.CharField(max_length=64, default="direct")
    handler_data = models.JSONField(default=dict, blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    # Only meaningful when the owning template's format is "xlsx" -- which
    # sheet this column belongs to in the generated workbook. Enforced as
    # required at the service layer for xlsx mappings (MappingService),
    # nullable here since it's noise for every other format -- same
    # nullable-and-type-conditional pattern as SourceFieldDefinition's
    # date_format/allowed_values/max_length.
    sheet_name = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "field_mapping"
        ordering = ["order"]

    def __str__(self):
        return f"{self.source_field.name} → {self.target_field} [{self.handler_method}]"


class TransformationJob(models.Model):
    class Status(models.TextChoices):
        PENDING = JobStatus.PENDING.value, "Pending"
        PROCESSING = JobStatus.PROCESSING.value, "Processing"
        PARTIAL = JobStatus.PARTIAL.value, "Partial"
        DONE = JobStatus.DONE.value, "Done"
        FAILED = JobStatus.FAILED.value, "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="jobs"
    )
    template = models.ForeignKey(
        TargetTemplate, on_delete=models.PROTECT, related_name="jobs"
    )
    format = models.CharField(max_length=16)
    storage_path = models.CharField(max_length=1024)
    source_path = models.CharField(max_length=512, default="data.items.item")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    total_chunks = models.IntegerField(default=0)
    # Total item count this job should process -- computed once at submission
    # time (the same ijson pass that decides chunk_size) but, until now, never
    # actually stored anywhere: job details had total_chunks/processed_chunks
    # but no baseline to say how many *items* the job represents, so a
    # supplier had no way to tell "3 skipped" apart from "3 skipped out of 10"
    # vs "3 skipped out of 40,000".
    total_items = models.IntegerField(default=0)
    # Items per chunk, computed once at submission time from total_items via the
    # dynamic chunk-size heuristic (see utils/chunking.py) and fixed for this job's
    # lifetime — retry must reconstruct the exact same [start, end] ranges it
    # originally dispatched, so this can't be recomputed from a global setting.
    chunk_size = models.IntegerField(default=5000)
    processed_chunks = models.IntegerField(default=0)
    # Items skipped during conversion (failed validation, or a handler/converter
    # raised on that specific item's data) -- never blocks the chunk, but the
    # count matters: a job that's DONE with a high skip rate silently converted
    # far less than it ingested. The trace itself (position + reason per skip)
    # lives in storage, not here -- there can be many entries per
    # chunk, unbounded by design, unlike failed_chunks which is one entry per
    # chunk range at most.
    skipped_items = models.IntegerField(default=0)
    failed_chunks = models.JSONField(default=list, blank=True)
    output_storage_path = models.CharField(max_length=1024, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # No updated_at: every write in JobRepository goes through .filter().update(),
    # which never triggers auto_now -- the field existed but was frozen at
    # creation time forever, never reflecting a real update. Removed rather than
    # fixed: the timestamps that actually matter (started_at for
    # PROCESSING staleness, failed_chunks[].failed_at for PARTIAL staleness) are
    # already purpose-built and more precise than a generic "last touched" would be.

    class Meta:
        db_table = "transformation_job"
        indexes = [
            # Covers list_for_supplier's default ordering (supplier + newest-first)
            # directly, instead of a per-supplier sort with no supporting index.
            models.Index(
                fields=["supplier", "-created_at"], name="job_supplier_created_idx"
            ),
            # Supports the admin's global status filter and any future
            # stuck-PARTIAL-jobs monitoring query (see README "Known limitations").
            models.Index(fields=["status"], name="job_status_idx"),
        ]

    @property
    def processing_duration(self) -> str | None:
        if not self.completed_at or not self.started_at:
            return None
        delta = (self.completed_at - self.started_at).total_seconds()
        if delta < 1:
            return f"{int(delta * 1000)}ms"
        total = int(delta)
        if total < 60:
            return f"{total}s"
        m, s = divmod(total, 60)
        if m < 60:
            return f"{m}m {s}s"
        h, m = divmod(m, 60)
        return f"{h}h {m}m {s}s"

    def __str__(self):
        return f"Job {self.id} [{self.status}] — {self.supplier.name} / {self.format}"
