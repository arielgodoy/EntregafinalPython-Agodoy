from django.contrib import admin

from .models import SearchPageIndex


@admin.register(SearchPageIndex)
class SearchPageIndexAdmin(admin.ModelAdmin):
    list_display = ("key", "vista", "url_name", "default_label", "is_active", "order")
    list_filter = ("is_active",)
    search_fields = ("key", "default_label", "keywords", "vista__nombre")
