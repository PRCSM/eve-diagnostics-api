from django.contrib import admin

from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest


class OfferingInline(admin.TabularInline):
    model = CentreTest
    extra = 0
    autocomplete_fields = ["test"]
    fields = ["test", "price", "is_active"]


@admin.register(DiagnosticCentre)
class DiagnosticCentreAdmin(admin.ModelAdmin):
    list_display = ["name", "city", "pincode", "is_active"]
    list_filter = ["is_active", "city"]
    search_fields = ["name", "city"]
    inlines = [OfferingInline]

    def has_delete_permission(self, request, obj=None) -> bool:
        return False  # deactivate instead; bookings reference centres


@admin.register(DiagnosticTest)
class DiagnosticTestAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["code", "name"]

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
