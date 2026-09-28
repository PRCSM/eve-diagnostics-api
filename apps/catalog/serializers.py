from decimal import Decimal

from django.core.validators import RegexValidator
from rest_framework import serializers

from apps.catalog.models import CURRENCY, CentreTest, DiagnosticCentre, DiagnosticTest

pincode_validator = RegexValidator(r"^[1-9][0-9]{5}$", "Enter a valid 6-digit PIN code.")
test_code_validator = RegexValidator(
    r"^[A-Za-z0-9_-]{2,32}$", "Use 2-32 letters, digits, '-' or '_'."
)

PRICE_FIELD_KWARGS = {"max_digits": 10, "decimal_places": 2, "min_value": Decimal("0.01")}


# --- Output -----------------------------------------------------------------------------------


class DiagnosticTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticTest
        fields = ["id", "code", "name", "description", "is_active", "created_at", "updated_at"]
        read_only_fields = fields


class DiagnosticTestSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticTest
        fields = ["id", "code", "name"]
        read_only_fields = fields


class OfferingSerializer(serializers.ModelSerializer):
    test = DiagnosticTestSummarySerializer(read_only=True)
    currency = serializers.SerializerMethodField()

    class Meta:
        model = CentreTest
        fields = ["test", "price", "currency", "is_active", "updated_at"]
        read_only_fields = fields

    def get_currency(self, obj: CentreTest) -> str:
        return CURRENCY


class CentreSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticCentre
        fields = [
            "id",
            "name",
            "address",
            "city",
            "pincode",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CentreDetailSerializer(CentreSerializer):
    tests = OfferingSerializer(many=True, read_only=True, source="active_offerings")

    class Meta(CentreSerializer.Meta):
        fields = [*CentreSerializer.Meta.fields, "tests"]
        read_only_fields = fields


# --- Input ------------------------------------------------------------------------------------


class CentreWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    address = serializers.CharField(max_length=255)
    city = serializers.CharField(max_length=100)
    pincode = serializers.CharField(max_length=10, validators=[pincode_validator])
    is_active = serializers.BooleanField(required=False)


class DiagnosticTestWriteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32, validators=[test_code_validator])
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    is_active = serializers.BooleanField(required=False)

    def validate_code(self, value: str) -> str:
        return value.upper()


class OfferingCreateSerializer(serializers.Serializer):
    test_id = serializers.UUIDField()
    price = serializers.DecimalField(**PRICE_FIELD_KWARGS)


class OfferingUpdateSerializer(serializers.Serializer):
    price = serializers.DecimalField(required=False, **PRICE_FIELD_KWARGS)
    is_active = serializers.BooleanField(required=False)


# --- Query parameters -------------------------------------------------------------------------


class IncludeInactiveQuerySerializer(serializers.Serializer):
    include_inactive = serializers.BooleanField(
        required=False, default=False, help_text="Staff only: include deactivated records."
    )


class CentreListQuerySerializer(IncludeInactiveQuerySerializer):
    city = serializers.CharField(required=False, max_length=100, help_text="Exact city, any case.")
    test = serializers.UUIDField(required=False, help_text="Only centres offering this test.")
    search = serializers.CharField(required=False, max_length=100, help_text="Centre name.")


class DiagnosticTestListQuerySerializer(IncludeInactiveQuerySerializer):
    search = serializers.CharField(required=False, max_length=100, help_text="Name or code.")
