from django.contrib import admin

from .models import ImageAsset, Tag


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(ImageAsset)
class ImageAssetAdmin(admin.ModelAdmin):
    list_display = (
        "original_name",
        "object_key",
        "provider",
        "status",
        "size",
        "uploaded_at",
        "deleted_at",
    )
    list_filter = ("status", "provider", "tags")
    search_fields = ("original_name", "object_key", "cdn_url")
    readonly_fields = ("uploaded_at", "deleted_at")
    filter_horizontal = ("tags",)
