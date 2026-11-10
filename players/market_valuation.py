"""Market-specific auction valuation, layered on top of format-specific global value."""
from decimal import Decimal, ROUND_HALF_UP

from .models import AuctionMarketProfile, CategoryValue, MarketValuation

FORMAT_CATEGORY = {"T20": "T20", "ODI": "ODI", "TEST": "TEST"}


def _money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _global_category_value(player, market):
    category = FORMAT_CATEGORY[market.cricket_format]
    if market.market_type == "DOMESTIC" and market.source_category:
        return (CategoryValue.objects.filter(player=player, category=market.source_category,
                                             group=market.source_group).first()
                or CategoryValue.objects.filter(player=player, category=category, group="").first())
    return (CategoryValue.objects.filter(player=player, category=category, group="").first()
            or CategoryValue.objects.filter(player=player, category=market.source_category,
                                            group=market.source_group).first())


def _market_fit_factor(player, market, global_cv):
    """Use relevant league/domestic evidence as a modest suitability adjustment."""
    if not market.source_category:
        return 1.0
    fit = CategoryValue.objects.filter(
        player=player, category=market.source_category, group=market.source_group
    ).first()
    if not fit or not global_cv:
        return 1.0
    difference = (float(fit.quality_score) - float(global_cv.quality_score)) / 100.0
    return max(0.90, min(1.10, 1.0 + difference * 0.20))


def _pool_role_scarcity(market, player):
    """Small pool-relative role adjustment; not a substitute for live squad demand."""
    category = market.source_category or FORMAT_CATEGORY[market.cricket_format]
    qs = CategoryValue.objects.filter(category=category, group=market.source_group)
    counts = {}
    for role_code, _label in player._meta.get_field("role").choices:
        counts[role_code] = qs.filter(player__role=role_code).count()
    nonzero = [n for n in counts.values() if n]
    if not nonzero:
        return 1.0
    average = sum(nonzero) / len(nonzero)
    own = counts.get(player.role, 0)
    if not own:
        return 1.0
    return max(0.96, min(1.08, 1.0 + (average - own) / max(average, 1.0) * 0.08))


def calculate_market_value(player, market):
    """Return a persisted MarketValuation for a player and a market profile."""
    global_cv = _global_category_value(player, market)
    if not global_cv:
        return None

    global_base = float(global_cv.total)
    purse = float(market.team_purse)
    squad_size = max(1, int(market.squad_size or 20))
    # Diminishing purse/squad scaling: a 20% larger purse does not mean 20% higher prices.
    purse_factor = max(0.80, min(1.25, (purse / 100.0) ** 0.35))
    squad_factor = max(0.90, min(1.10, (20.0 / squad_size) ** 0.15))
    configured_factor = max(0.75, min(1.25, float(market.market_factor or 1.0)))
    fit_factor = _market_fit_factor(player, market, global_cv)
    scarcity_factor = _pool_role_scarcity(market, player)
    adjustment = purse_factor * squad_factor * configured_factor * fit_factor * scarcity_factor
    adjustment = max(0.70, min(1.50, adjustment))

    estimate = global_base * adjustment
    # Keep an estimate plausible relative to the purse, without tying it to a hard-coded ₹23 Cr ceiling.
    estimate = max(0.50, min(purse * 0.40, estimate))
    price_band = "premium" if estimate >= 16 else "balanced" if estimate >= 8 else "value"
    explanation = {
        "format": market.cricket_format,
        "global_category": global_cv.category,
        "global_group": global_cv.group,
        "purse_factor": round(purse_factor, 4),
        "squad_factor": round(squad_factor, 4),
        "configured_market_factor": round(configured_factor, 4),
        "competition_fit_factor": round(fit_factor, 4),
        "role_scarcity_factor": round(scarcity_factor, 4),
        "note": "Estimated market value; actual winning bids depend on team needs and bidding competition.",
    }
    obj, _ = MarketValuation.objects.update_or_create(
        player=player, market=market,
        defaults={
            "category_value": global_cv,
            "global_base_value": _money(global_base),
            "market_adjustment": round(adjustment, 4),
            "estimated_value": _money(estimate),
            "confidence_score": global_cv.confidence_score,
            "price_band": price_band,
            "explanation": explanation,
        },
    )
    return obj


def recalculate_market(market):
    """Recalculate every player with a usable global value for this market's format."""
    category = market.source_category if market.market_type == "DOMESTIC" and market.source_category else FORMAT_CATEGORY[market.cricket_format]
    player_ids = CategoryValue.objects.filter(category=category, group=market.source_group if market.market_type == "DOMESTIC" else "").values_list("player_id", flat=True)
    # Also include players who only have the configured source category (e.g. domestic data).
    if market.source_category:
        source_ids = CategoryValue.objects.filter(
            category=market.source_category, group=market.source_group
        ).values_list("player_id", flat=True)
        player_ids = set(player_ids).union(source_ids)
    else:
        player_ids = set(player_ids)
    from .models import Player
    created = 0
    for player in Player.objects.filter(pk__in=player_ids).iterator():
        if calculate_market_value(player, market):
            created += 1
    return created


def recalculate_all_markets():
    return {market.name: recalculate_market(market) for market in AuctionMarketProfile.objects.filter(is_active=True)}
