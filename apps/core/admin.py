from django.contrib import admin

from .models import AuditLog, Dataset, SiteSetting


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "actor", "target_type", "target_id", "ip_address"]
    list_filter = ["action", "target_type"]
    search_fields = ["action", "target_id", "actor__email"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ["key", "updated_at"]
    search_fields = ["key", "description"]


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ["name", "version", "licence", "commercial_use_allowed"]
    list_filter = ["commercial_use_allowed"]
    search_fields = ["name", "provider"]
