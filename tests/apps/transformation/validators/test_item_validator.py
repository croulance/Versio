from apps.transformation.validators.item_validator import DynamicItemValidator


def _field(name, field_type="string", required=True, nullable=False, **extra):
    return {
        "name": name,
        "field_type": field_type,
        "required": required,
        "nullable": nullable,
        **extra,
    }


class TestAbsence:
    def test_required_field_absent_is_an_error(self):
        result, errors = DynamicItemValidator().validate(
            {}, [_field("name", required=True)]
        )
        assert result == {}
        assert errors == {"name": "required field is absent"}

    def test_optional_field_absent_with_default_uses_default(self):
        field = _field("name", required=False, default_value="fallback")
        result, errors = DynamicItemValidator().validate({}, [field])
        assert result == {"name": "fallback"}
        assert errors == {}

    def test_optional_field_absent_without_default_is_skipped(self):
        field = _field("name", required=False)
        result, errors = DynamicItemValidator().validate({}, [field])
        assert result == {}
        assert errors == {}


class TestEmptyValue:
    def test_empty_string_non_nullable_is_an_error(self):
        field = _field("name", nullable=False)
        result, errors = DynamicItemValidator().validate({"name": ""}, [field])
        assert result == {}
        assert errors == {"name": "non-nullable field received empty value"}

    def test_empty_string_nullable_becomes_none(self):
        field = _field("name", nullable=True)
        result, errors = DynamicItemValidator().validate({"name": ""}, [field])
        assert result == {"name": None}
        assert errors == {}


class TestCoercion:
    def test_string_type(self):
        result, errors = DynamicItemValidator().validate(
            {"name": 42}, [_field("name", "string")]
        )
        assert result == {"name": "42"}
        assert errors == {}

    def test_email_and_url_types_behave_like_string(self):
        fields = [_field("email", "email"), _field("url", "url")]
        result, errors = DynamicItemValidator().validate(
            {"email": "a@b.com", "url": "http://x"}, fields
        )
        assert result == {"email": "a@b.com", "url": "http://x"}
        assert errors == {}

    def test_number_type(self):
        result, errors = DynamicItemValidator().validate(
            {"area": "12.5"}, [_field("area", "number")]
        )
        assert result == {"area": 12.5}
        assert errors == {}

    def test_integer_type(self):
        result, errors = DynamicItemValidator().validate(
            {"count": "7"}, [_field("count", "integer")]
        )
        assert result == {"count": 7}
        assert errors == {}

    def test_boolean_type_from_string(self):
        fields = [_field("a", "boolean"), _field("b", "boolean")]
        result, errors = DynamicItemValidator().validate(
            {"a": "yes", "b": "no"}, fields
        )
        assert result == {"a": True, "b": False}
        assert errors == {}

    def test_boolean_type_already_bool_passes_through(self):
        result, errors = DynamicItemValidator().validate(
            {"a": True}, [_field("a", "boolean")]
        )
        assert result == {"a": True}
        assert errors == {}

    def test_geojson_type_from_json_string(self):
        field = _field("geo", "geojson")
        result, errors = DynamicItemValidator().validate(
            {"geo": '{"type": "Point"}'}, [field]
        )
        assert result == {"geo": {"type": "Point"}}
        assert errors == {}

    def test_geojson_type_already_parsed_passes_through(self):
        field = _field("geo", "geojson")
        result, errors = DynamicItemValidator().validate(
            {"geo": {"type": "Point"}}, [field]
        )
        assert result == {"geo": {"type": "Point"}}
        assert errors == {}

    def test_date_type_without_format_uses_iso(self):
        field = _field("d", "date")
        result, errors = DynamicItemValidator().validate({"d": "2026-07-08"}, [field])
        assert result["d"].isoformat() == "2026-07-08"
        assert errors == {}

    def test_date_type_with_custom_format(self):
        field = _field("d", "date", date_format="%d/%m/%Y")
        result, errors = DynamicItemValidator().validate({"d": "08/07/2026"}, [field])
        assert result["d"].isoformat() == "2026-07-08"
        assert errors == {}

    def test_datetime_type(self):
        field = _field("ts", "datetime")
        result, errors = DynamicItemValidator().validate(
            {"ts": "2026-07-08T10:00:00"}, [field]
        )
        assert result["ts"].isoformat() == "2026-07-08T10:00:00"
        assert errors == {}

    def test_unknown_field_type_passes_through_unchanged(self):
        field = _field("raw", "unknown_type")
        result, errors = DynamicItemValidator().validate(
            {"raw": {"anything": 1}}, [field]
        )
        assert result == {"raw": {"anything": 1}}
        assert errors == {}

    def test_coercion_failure_produces_type_error_message(self):
        field = _field("count", "integer")
        result, errors = DynamicItemValidator().validate(
            {"count": "not-a-number"}, [field]
        )
        assert result == {}
        assert "type error (integer):" in errors["count"]


class TestConstraints:
    def test_max_length_violation(self):
        field = _field("name", "string", max_length=3)
        result, errors = DynamicItemValidator().validate({"name": "abcd"}, [field])
        assert result == {}
        assert "exceeds max_length=3" in errors["name"]

    def test_allowed_values_violation(self):
        field = _field("status", "string", allowed_values=["OK", "KO"])
        result, errors = DynamicItemValidator().validate({"status": "MAYBE"}, [field])
        assert result == {}
        assert "not in allowed values" in errors["status"]

    def test_min_value_violation(self):
        field = _field("area", "number", min_value=10)
        result, errors = DynamicItemValidator().validate({"area": "5"}, [field])
        assert result == {}
        assert "below min_value=10" in errors["area"]

    def test_max_value_violation(self):
        field = _field("area", "number", max_value=10)
        result, errors = DynamicItemValidator().validate({"area": "15"}, [field])
        assert result == {}
        assert "above max_value=10" in errors["area"]

    def test_constraints_pass_within_bounds(self):
        field = _field("area", "number", min_value=0, max_value=100)
        result, errors = DynamicItemValidator().validate({"area": "50"}, [field])
        assert result == {"area": 50.0}
        assert errors == {}


class TestNestedObject:
    def test_object_without_children_is_opaque_passthrough(self):
        # Backward compatible: no declared schema = no validation, same as before.
        field = _field("meta", "object")
        result, errors = DynamicItemValidator().validate(
            {"meta": {"anything": "goes", "here": 1}}, [field]
        )
        assert result == {"meta": {"anything": "goes", "here": 1}}
        assert errors == {}

    def test_object_with_children_validates_and_coerces_each_nested_field(self):
        field = _field(
            "complianceStatus",
            "object",
            children=[
                _field("code", "string", allowed_values=["PENDING", "APPROVED"]),
                _field("label", "string"),
            ],
        )
        result, errors = DynamicItemValidator().validate(
            {"complianceStatus": {"code": "PENDING", "label": "Pending"}}, [field]
        )
        assert result == {
            "complianceStatus": {"code": "PENDING", "label": "Pending"}
        }
        assert errors == {}

    def test_nested_field_error_uses_dot_path_key(self):
        field = _field(
            "complianceStatus",
            "object",
            children=[_field("code", "string", allowed_values=["PENDING", "APPROVED"])],
        )
        result, errors = DynamicItemValidator().validate(
            {"complianceStatus": {"code": "UNKNOWN"}}, [field]
        )
        assert result == {}
        assert "not in allowed values" in errors["complianceStatus.code"]

    def test_nested_required_field_missing_uses_dot_path_key(self):
        field = _field(
            "complianceStatus",
            "object",
            children=[_field("code", "string", required=True)],
        )
        result, errors = DynamicItemValidator().validate(
            {"complianceStatus": {}}, [field]
        )
        assert result == {}
        assert errors == {"complianceStatus.code": "required field is absent"}

    def test_object_value_that_is_not_a_dict_is_an_error(self):
        # A raw list isn't run through json.loads (only strings are) — reaches
        # the "expected an object" guard cleanly, past _coerce's type error path.
        field = _field(
            "complianceStatus", "object", children=[_field("code", "string")]
        )
        result, errors = DynamicItemValidator().validate(
            {"complianceStatus": [1, 2, 3]}, [field]
        )
        assert result == {}
        assert errors == {"complianceStatus": "expected an object"}

    def test_recursion_handles_doubly_nested_objects(self):
        field = _field(
            "a",
            "object",
            children=[
                _field(
                    "b",
                    "object",
                    children=[_field("c", "string", required=True)],
                )
            ],
        )
        result, errors = DynamicItemValidator().validate({"a": {"b": {}}}, [field])
        assert result == {}
        assert errors == {"a.b.c": "required field is absent"}

    def test_json_string_object_with_children_is_parsed_then_validated(self):
        field = _field(
            "complianceStatus",
            "object",
            children=[_field("code", "string", required=True)],
        )
        result, errors = DynamicItemValidator().validate(
            {"complianceStatus": '{"code": "PENDING"}'}, [field]
        )
        assert result == {"complianceStatus": {"code": "PENDING"}}
        assert errors == {}


class TestMultiFieldItem:
    def test_mix_of_success_and_failure_across_fields(self):
        fields = [
            _field("producerName", "string", required=True),
            _field("area", "number", min_value=0),
            _field("missingRequired", "string", required=True),
            _field(
                "optionalWithDefault", "string", required=False, default_value="n/a"
            ),
        ]
        item = {"producerName": "Acme", "area": "-5"}

        result, errors = DynamicItemValidator().validate(item, fields)

        assert result == {"producerName": "Acme", "optionalWithDefault": "n/a"}
        assert errors == {
            "area": "below min_value=0",
            "missingRequired": "required field is absent",
        }
