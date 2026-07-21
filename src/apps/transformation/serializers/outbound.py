from rest_framework import serializers


class FailedChunkSerializer(serializers.Serializer):
    start = serializers.IntegerField()
    end = serializers.IntegerField()
    error = serializers.CharField(allow_null=True)
    failed_at = serializers.CharField(allow_null=True)
    retry_count = serializers.IntegerField()
    # default=True: entries written before this field existed
    # have no `retryable` key at all — treat them as retryable, matching
    # JobLifecycleService.retryable_failed_chunks()'s own fallback.
    retryable = serializers.BooleanField(default=True)


class JobListItemSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    status = serializers.CharField()
    format = serializers.CharField()
    template_id = serializers.IntegerField(allow_null=True)
    template_version = serializers.IntegerField()
    total_chunks = serializers.IntegerField()
    processed_chunks = serializers.IntegerField()
    progress_pct = serializers.IntegerField()
    processing_duration = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    has_source_file = serializers.BooleanField()
    has_output_file = serializers.BooleanField()
    skipped_items = serializers.IntegerField()


class JobReportSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    status = serializers.CharField()
    supplier = serializers.CharField()
    supplier_account_id = serializers.IntegerField()
    format = serializers.CharField()
    template_id = serializers.IntegerField(allow_null=True)
    template_name = serializers.CharField(allow_null=True)
    template_version = serializers.IntegerField()
    source_path = serializers.CharField(allow_blank=True)
    total_items = serializers.IntegerField()
    total_chunks = serializers.IntegerField()
    chunk_size = serializers.IntegerField()
    processed_chunks = serializers.IntegerField()
    progress_pct = serializers.IntegerField()
    failed_chunks = FailedChunkSerializer(many=True)
    skipped_items = serializers.IntegerField()
    has_source_file = serializers.BooleanField()
    has_output_file = serializers.BooleanField()
    has_errors_file = serializers.BooleanField()
    output_storage_path = serializers.CharField(allow_blank=True)
    processing_duration = serializers.CharField(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class TemplateSupplierRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class TemplateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    format = serializers.CharField()
    version = serializers.IntegerField()
    source_path = serializers.CharField(allow_blank=True)
    metadata = serializers.JSONField()
    status = serializers.CharField()
    supplier = TemplateSupplierRefSerializer()


class SourceFieldSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    field_type = serializers.CharField()
    required = serializers.BooleanField()
    nullable = serializers.BooleanField()
    default_value = serializers.JSONField(allow_null=True)
    max_length = serializers.IntegerField(allow_null=True)
    allowed_values = serializers.ListField()
    min_value = serializers.FloatField(allow_null=True)
    max_value = serializers.FloatField(allow_null=True)
    date_format = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    order = serializers.IntegerField()
    parent_id = serializers.IntegerField(allow_null=True)
    path = serializers.CharField()
    children = serializers.SerializerMethodField()

    def get_children(self, obj):
        # Recurse manually (nested `SourceFieldSerializer(many=True)` can't
        # reference its own not-yet-defined class) — same shape at every depth.
        children = obj.children if hasattr(obj, "children") else obj.get("children", [])
        return SourceFieldSerializer(children, many=True).data


class MappingSourceFieldRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    field_type = serializers.CharField()
    path = serializers.CharField()


class MappingSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    source_field = MappingSourceFieldRefSerializer()
    target_field = serializers.CharField()
    handler_method = serializers.CharField()
    handler_data = serializers.JSONField()
    order = serializers.IntegerField()
    sheet_name = serializers.CharField(allow_null=True, required=False)
