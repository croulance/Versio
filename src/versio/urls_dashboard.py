from django.urls import path

from apps.dashboard.views.auth import LoginView, LogoutView
from apps.dashboard.views.batches import (BatchDetailView,
                                          BatchDownloadErrorsView,
                                          BatchDownloadResultView,
                                          BatchDownloadSourceView,
                                          BatchErrorsView, BatchListView,
                                          BatchStatusView, BatchSubmitView)
from apps.dashboard.views.mappings import (MappingAddView, MappingDeleteView,
                                           MappingEditView, MappingRowView)
from apps.dashboard.views.source_fields import (SourceFieldAddView,
                                                SourceFieldDeleteView,
                                                SourceFieldEditView,
                                                SourceFieldRowView)
from apps.dashboard.views.templates import (TemplateCreateView,
                                            TemplateDashboardView,
                                            TemplateDeprecateView,
                                            TemplateEditorView,
                                            TemplateMetadataView,
                                            TemplateNameView,
                                            TemplatePublishView,
                                            TemplateRevertToDraftView,
                                            TemplateSourcePathView)

urlpatterns = [
    # Auth
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    # Dashboard
    path("", TemplateDashboardView.as_view(), name="dashboard-index"),
    path("templates/", TemplateDashboardView.as_view(), name="template-dashboard"),
    path("templates/new/", TemplateCreateView.as_view(), name="template-create"),
    # Template editor fragment
    path(
        "templates/<int:template_id>/",
        TemplateEditorView.as_view(),
        name="template-editor",
    ),
    # Template lifecycle
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
    # Template name
    path(
        "templates/<int:template_id>/name/",
        TemplateNameView.as_view(),
        name="template-name",
    ),
    # Template source path
    path(
        "templates/<int:template_id>/source-path/",
        TemplateSourcePathView.as_view(),
        name="template-source-path",
    ),
    # Template metadata
    path(
        "templates/<int:template_id>/metadata/",
        TemplateMetadataView.as_view(),
        name="template-metadata",
    ),
    # Source fields
    path(
        "templates/<int:template_id>/fields/add/",
        SourceFieldAddView.as_view(),
        name="field-add",
    ),
    path(
        "templates/<int:template_id>/fields/<int:field_id>/",
        SourceFieldRowView.as_view(),
        name="field-row",
    ),
    path(
        "templates/<int:template_id>/fields/<int:field_id>/edit/",
        SourceFieldEditView.as_view(),
        name="field-edit",
    ),
    path(
        "templates/<int:template_id>/fields/<int:field_id>/delete/",
        SourceFieldDeleteView.as_view(),
        name="field-delete",
    ),
    # Batches
    path("batches/", BatchListView.as_view(), name="batches"),
    path("batches/submit/", BatchSubmitView.as_view(), name="batch-submit"),
    path("batches/<str:job_id>/", BatchDetailView.as_view(), name="batch-detail"),
    path(
        "batches/<str:job_id>/status/", BatchStatusView.as_view(), name="batch-status"
    ),
    path(
        "batches/<str:job_id>/download-source/",
        BatchDownloadSourceView.as_view(),
        name="batch-download-source",
    ),
    path(
        "batches/<str:job_id>/download/",
        BatchDownloadResultView.as_view(),
        name="batch-download-result",
    ),
    path(
        "batches/<str:job_id>/download-errors/",
        BatchDownloadErrorsView.as_view(),
        name="batch-download-errors",
    ),
    path(
        "batches/<str:job_id>/errors/",
        BatchErrorsView.as_view(),
        name="batch-errors",
    ),
    # Mappings
    path(
        "templates/<int:template_id>/mappings/add/",
        MappingAddView.as_view(),
        name="mapping-add",
    ),
    path(
        "templates/<int:template_id>/mappings/<int:mapping_id>/",
        MappingRowView.as_view(),
        name="mapping-row",
    ),
    path(
        "templates/<int:template_id>/mappings/<int:mapping_id>/edit/",
        MappingEditView.as_view(),
        name="mapping-edit",
    ),
    path(
        "templates/<int:template_id>/mappings/<int:mapping_id>/delete/",
        MappingDeleteView.as_view(),
        name="mapping-delete",
    ),
]
