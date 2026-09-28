from django.contrib import admin

from apps.bookings.models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    """Read-only: status changes must go through the booking and payment services."""

    list_display = ["id", "status", "appointment_at", "amount", "currency", "created_at"]
    list_filter = ["status"]
    list_select_related = ["offering__centre", "offering__test"]
    ordering = ["-created_at"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
