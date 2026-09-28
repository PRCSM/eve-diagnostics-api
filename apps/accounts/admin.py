from django.contrib import admin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Minimal user admin. Accounts are created via the API or `createsuperuser`."""

    list_display = ["email", "full_name", "is_staff", "is_active", "created_at"]
    list_filter = ["is_staff", "is_active"]
    search_fields = ["email", "full_name"]
    ordering = ["-created_at"]
    fields = ["email", "full_name", "phone", "is_active", "is_staff", "last_login", "created_at"]
    readonly_fields = ["last_login", "created_at"]
