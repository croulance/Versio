from enum import StrEnum


class JobStatus(StrEnum):
    """Mirrors TransformationJob.Status's values without requiring a Django
    import. Services can't import Django models (enforced by
    tests/architecture/test_services_no_framework_dependencies.py) but still
    need real status comparisons instead of raw string literals — StrEnum
    (not a plain Enum) so a member compares equal to the plain str Django's
    ORM actually returns from job.status at runtime (choices don't cast the
    field value to an enum type, only validate/label it)."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PARTIAL = "PARTIAL"
    DONE = "DONE"
    FAILED = "FAILED"


class TemplateStatus(StrEnum):
    """Mirrors TargetTemplate.Status's values — same reasoning as JobStatus."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
