from django.contrib import admin
from modeltranslation.admin import TranslationAdmin

from .models import Product, ProductPrice


class ProductPriceInline(admin.TabularInline):
    model = ProductPrice
    extra = 0


@admin.register(Product)
class ProductAdmin(TranslationAdmin):
    list_display = ["name", "code", "kind", "sort_order", "is_active"]
    list_filter = ["kind", "is_active"]
    inlines = [ProductPriceInline]
