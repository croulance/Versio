from rest_framework import serializers


class TransformRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    supplier_account_id = serializers.IntegerField()
    template_id = serializers.IntegerField()
