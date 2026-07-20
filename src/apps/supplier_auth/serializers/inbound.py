from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=1)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class BearerTokenSerializer(serializers.Serializer):
    """
    Extracts a Bearer token from the Authorization header.
    `source` only remaps the *output* key in DRF — the input lookup always
    uses `field_name`, so a plain `CharField` can never read `HTTP_AUTHORIZATION`
    out of `request.META` this way. `to_internal_value` is overridden instead.
    """

    authorization = serializers.CharField(read_only=True)

    def to_internal_value(self, data):
        value = data.get("HTTP_AUTHORIZATION", "")
        if not value.startswith("Bearer "):
            raise serializers.ValidationError(
                {"authorization": "Expected 'Bearer <token>'."}
            )
        token = value[7:].strip()
        if not token:
            raise serializers.ValidationError(
                {"authorization": "Token must not be empty."}
            )
        return {"authorization": token}
