from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import Organization, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "first_name", "last_name", "language", "currency", "is_staff"]
    list_filter = ["is_staff", "is_active", "groups", "language", "currency"]
    search_fields = ["email", "first_name", "last_name", "phone"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Profile"), {"fields": ("first_name", "last_name", "phone", "language", "currency")}),
        (_("Organization"), {"fields": ("organization",)}),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "billing_email", "invoiced_monthly"]
    search_fields = ["name"]
