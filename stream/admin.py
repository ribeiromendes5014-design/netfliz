from django.contrib import admin

from .models import Tenant, Video


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("user", "slug", "is_active", "access_end_date", "show_subscription_popup")
    list_filter = ("is_active",)
    search_fields = ("user__username", "user__email", "slug")
    readonly_fields = ("show_subscription_popup",)


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "tenant", "video_type", "is_public", "created_at")
    list_filter = ("video_type", "is_public", "tenant__is_active")
    search_fields = ("title", "tenant__slug")
