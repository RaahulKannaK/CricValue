from django.contrib import admin
from .models import Player, Match, Performance, CategoryValue, AuctionMarketProfile, MarketValuation


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "role", "date_of_birth", "potential_rating")
    fields = ("name", "country", "role", "cricsheet_id", "date_of_birth", "potential_rating", "base_value", "base_locked")
    list_filter = ("role", "country")
    search_fields = ("name", "country")


@admin.register(CategoryValue)
class CategoryValueAdmin(admin.ModelAdmin):
    list_display = ("player", "category", "base_value", "form_premium", "matches", "locked")
    list_filter = ("category", "locked")
    search_fields = ("player__name",)


admin.site.register(Match)
admin.site.register(Performance)

@admin.register(AuctionMarketProfile)
class AuctionMarketProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "market_type", "cricket_format", "team_purse", "squad_size", "team_count", "is_active")
    list_filter = ("market_type", "cricket_format", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(MarketValuation)
class MarketValuationAdmin(admin.ModelAdmin):
    list_display = ("player", "market", "global_base_value", "estimated_value", "price_band", "confidence_score")
    list_filter = ("market", "price_band")
    search_fields = ("player__name", "market__name")
    readonly_fields = ("calculated_at",)
