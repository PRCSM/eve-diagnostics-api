from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import RegexValidator
from rest_framework import serializers

from apps.accounts.models import User, normalize_email

phone_validator = RegexValidator(
    regex=r"^\+?[0-9]{7,15}$",
    message="Enter a phone number of 7-15 digits, optionally starting with '+'.",
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "is_staff", "created_at"]
        read_only_fields = fields


class SignupSerializer(serializers.Serializer):
    """Explicit fields only: privileged attributes such as is_staff can never be set here."""

    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, max_length=128, trim_whitespace=False)
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True, validators=[phone_validator]
    )

    def validate_email(self, value: str) -> str:
        return normalize_email(value)

    def validate(self, attrs: dict) -> dict:
        candidate = User(email=attrs["email"], full_name=attrs["full_name"])
        try:
            password_validation.validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, max_length=128, trim_whitespace=False)

    def validate_email(self, value: str) -> str:
        return normalize_email(value)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


class RefreshTokenSerializer(serializers.Serializer):
    refresh = serializers.CharField()
