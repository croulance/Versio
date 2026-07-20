from django.urls import path

from apps.transformation.views.job import (JobDownloadErrorsView,
                                           JobDownloadResultView,
                                           JobDownloadSourceView, JobListView,
                                           JobView)
from apps.transformation.views.mappings import (HandlerListView,
                                                MappingDetailView,
                                                MappingListView)
from apps.transformation.views.retry import JobRetryView
from apps.transformation.views.source_fields import (SourceFieldDetailView,
                                                     SourceFieldListView)
from apps.transformation.views.suppliers import SupplierListView
from apps.transformation.views.templates import (TemplateDeprecateView,
                                                 TemplateDetailView,
                                                 TemplateListView,
                                                 TemplatePublishView,
                                                 TemplateRevertToDraftView)
from apps.transformation.views.transform import TransformView

urlpatterns = [
    # Transformation pipeline
    path("transform/", TransformView.as_view(), name="transform"),
    path("jobs/", JobListView.as_view(), name="job-list"),
    path("jobs/<str:job_id>/", JobView.as_view(), name="job-detail"),
    path("jobs/<str:job_id>/retry/", JobRetryView.as_view(), name="job-retry"),
    path(
        "jobs/<str:job_id>/download-source/",
        JobDownloadSourceView.as_view(),
        name="job-download-source",
    ),
    path(
        "jobs/<str:job_id>/download/",
        JobDownloadResultView.as_view(),
        name="job-download-result",
    ),
    path(
        "jobs/<str:job_id>/download-errors/",
        JobDownloadErrorsView.as_view(),
        name="job-download-errors",
    ),
    # Suppliers
    path("suppliers/", SupplierListView.as_view(), name="supplier-list"),
    # Templates
    path("templates/", TemplateListView.as_view(), name="template-list"),
    path(
        "templates/<int:template_id>/",
        TemplateDetailView.as_view(),
        name="template-detail",
    ),
    path(
        "templates/<int:template_id>/publish/",
        TemplatePublishView.as_view(),
        name="template-publish",
    ),
    path(
        "templates/<int:template_id>/deprecate/",
        TemplateDeprecateView.as_view(),
        name="template-deprecate",
    ),
    path(
        "templates/<int:template_id>/revert-to-draft/",
        TemplateRevertToDraftView.as_view(),
        name="template-revert-to-draft",
    ),
    # Source fields
    path(
        "templates/<int:template_id>/source-fields/",
        SourceFieldListView.as_view(),
        name="source-field-list",
    ),
    path(
        "templates/<int:template_id>/source-fields/<int:field_id>/",
        SourceFieldDetailView.as_view(),
        name="source-field-detail",
    ),
    # Mappings
    path(
        "templates/<int:template_id>/mappings/",
        MappingListView.as_view(),
        name="mapping-list",
    ),
    path(
        "templates/<int:template_id>/mappings/<int:mapping_id>/",
        MappingDetailView.as_view(),
        name="mapping-detail",
    ),
    # Handlers
    path("handlers/", HandlerListView.as_view(), name="handler-list"),
]
