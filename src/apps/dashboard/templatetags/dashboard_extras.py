from django import template

register = template.Library()

_TEMPLATE_STATUS_COLORS = {
    "PUBLISHED": "bg-green-50 text-green-700 border border-green-200",
    "DEPRECATED": "bg-gray-100 text-gray-500 border border-gray-200",
}
_TEMPLATE_STATUS_DEFAULT = "bg-amber-50 text-amber-600 border border-amber-200"  # DRAFT

_JOB_STATUS_COLORS = {
    "DONE": "bg-green-50 text-green-700",
    "FAILED": "bg-red-50 text-red-700",
    "PARTIAL": "bg-orange-50 text-orange-700",
}
_JOB_STATUS_DEFAULT = "bg-indigo-50 text-indigo-700"  # PENDING / PROCESSING

_JOB_PROGRESS_BAR_COLORS = {
    "DONE": "bg-green-500",
    "FAILED": "bg-red-400",
    "PARTIAL": "bg-orange-400",
}
_JOB_PROGRESS_BAR_DEFAULT = "bg-indigo-500"

_FORMAT_COLORS = {
    "json": "bg-blue-50 text-blue-600 border border-blue-200",
    "csv": "bg-green-50 text-green-600 border border-green-200",
    "xlsx": "bg-emerald-50 text-emerald-600 border border-emerald-200",
    "xml": "bg-orange-50 text-orange-600 border border-orange-200",
}
_FORMAT_DEFAULT = "bg-gray-100 text-gray-600"


@register.filter
def template_status_classes(status: str) -> str:
    """Color classes for a TargetTemplate status (DRAFT/PUBLISHED/DEPRECATED)."""
    return _TEMPLATE_STATUS_COLORS.get(status, _TEMPLATE_STATUS_DEFAULT)


@register.filter
def job_status_classes(status: str) -> str:
    """Color classes for a batch job status (PENDING/PROCESSING/DONE/FAILED/PARTIAL)."""
    return _JOB_STATUS_COLORS.get(status, _JOB_STATUS_DEFAULT)


@register.filter
def job_progress_bar_classes(status: str) -> str:
    """Fill color for a batch job's progress bar, keyed by the same statuses."""
    return _JOB_PROGRESS_BAR_COLORS.get(status, _JOB_PROGRESS_BAR_DEFAULT)


@register.filter
def format_classes(fmt: str) -> str:
    """Color classes for a template's data format (json/csv/xlsx/xml)."""
    return _FORMAT_COLORS.get(fmt, _FORMAT_DEFAULT)


@register.filter
def total_field_count(fields: list) -> int:
    """Recursive count of a source-fields tree — top-level fields plus every
    nested child at any depth, since `fields|length` only sees the top level."""
    return sum(1 + total_field_count(f.get("children") or []) for f in fields)
