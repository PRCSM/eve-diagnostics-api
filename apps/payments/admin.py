from django.contrib import admin

from apps.payments.models import Payment


class ReadOnlyAdmin(admin.ModelAdmin):
    """Payment records are an audit trail; they change only through the payment services."""

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ["id", "booking", "status", "amount", "provider_reference", "created_at"]
    list_filter = ["status", "provider"]
    search_fields = ["provider_reference", "booking__id"]
    ordering = ["-created_at"]
