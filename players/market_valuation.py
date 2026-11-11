"""Optimized bulk market valuation recalculation.

Replaces per-player COUNT(), SELECT and update_or_create() calls with:
- one role-count aggregation per market
- one player query and one CategoryValue query per market
- batched bulk_update()/bulk_create() writes
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    AuctionMarketProfile,
    CategoryValue,
    MarketValuation,
    Player,
)

FORMAT_CATEGORY = {"T20": "T20", "ODI": "ODI", "TEST": "TEST"}
WRITE_BATCH_SIZE = 500


def _money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _first(mapping, player_id, category, group):
    return mapping.get((player_id, category, group))


def _global_and_fit_values(player_id, market, values):
    fmt_category = FORMAT_CATEGORY[market.cricket_format]
    source_category = market.source_category
    source_group = market.source_group

    if market.market_type == "DOMESTIC" and source_category:
        global_cv = (
            _first(values, player_id, source_category, source_group)
            or _first(values, player_id, fmt_category, "")
        )
    else:
        global_cv = (
            _first(values, player_id, fmt_category, "")
            or (_first(values, player_id, source_category, source_group)
                if source_category else None)
        )

    fit_cv = (
        _first(values, player_id, source_category, source_group)
        if source_category else None
    )
    return global_cv, fit_cv


def _role_scarcity_factor(role, role_counts):
    nonzero = [count for count in role_counts.values() if count]
    if not nonzero:
        return 1.0
    average = sum(nonzero) / len(nonzero)
    own = role_counts.get(role, 0)
    if not own:
        return 1.0
    return max(0.96, min(
        1.08,
        1.0 + (average - own) / max(average, 1.0) * 0.08,
    ))


def calculate_market_value(player, market):
    """Compatibility helper for callers needing a single persisted valuation."""
    return recalculate_market(market, player_ids=[player.pk], player_roles={player.pk: player.role},
                              only_player=player)


def recalculate_market(market, player_ids=None, player_roles=None, only_player=None):
    """Recalculate all eligible players for one market using batched DB operations."""
    fmt_category = FORMAT_CATEGORY[market.cricket_format]
    source_category = market.source_category
    source_group = market.source_group
    primary_category = (
        source_category
        if market.market_type == "DOMESTIC" and source_category
        else fmt_category
    )
    primary_group = source_group if market.market_type == "DOMESTIC" else ""

    if player_ids is None:
        ids = set(CategoryValue.objects.filter(
            category=primary_category, group=primary_group
        ).values_list("player_id", flat=True))
        if source_category:
            ids.update(CategoryValue.objects.filter(
                category=source_category, group=source_group
            ).values_list("player_id", flat=True))
    else:
        ids = set(player_ids)

    if not ids:
        return 0

    players = list(
        Player.objects.filter(pk__in=ids).values_list("id", "role")
    )
    if only_player is not None:
        players = [(only_player.pk, only_player.role)]

    role_map = dict(player_roles or players)

    # Fetch only the category/group combinations that can affect this market.
    pairs = {(fmt_category, ""), (primary_category, primary_group)}
    if source_category:
        pairs.add((source_category, source_group))
    condition = Q(pk__in=[])
    for category, group in pairs:
        condition |= Q(category=category, group=group)

    value_map = {}
    for cv in CategoryValue.objects.filter(player_id__in=ids).filter(condition).order_by("id"):
        value_map.setdefault((cv.player_id, cv.category, cv.group), cv)

    # One aggregate query replaces four COUNT() queries for every player.
    scarcity_category = source_category or fmt_category
    role_counts = dict(
        CategoryValue.objects.filter(
            category=scarcity_category, group=source_group
        ).values("player__role").annotate(total=Count("id")).values_list("player__role", "total")
    )

    purse = float(market.team_purse)
    squad_size = max(1, int(market.squad_size or 20))
    purse_factor = max(0.80, min(1.25, (purse / 100.0) ** 0.35))
    squad_factor = max(0.90, min(1.10, (20.0 / squad_size) ** 0.15))
    configured_factor = max(0.75, min(1.25, float(market.market_factor or 1.0)))

    now = timezone.now()
    desired = []
    for player_id, role in players:
        global_cv, fit_cv = _global_and_fit_values(player_id, market, value_map)
        if not global_cv:
            continue

        fit_factor = 1.0
        if fit_cv:
            difference = (float(fit_cv.quality_score) - float(global_cv.quality_score)) / 100.0
            fit_factor = max(0.90, min(1.10, 1.0 + difference * 0.20))

        scarcity_factor = _role_scarcity_factor(role, role_counts)
        adjustment = purse_factor * squad_factor * configured_factor * fit_factor * scarcity_factor
        adjustment = max(0.70, min(1.50, adjustment))
        estimate = max(0.50, min(purse * 0.40, float(global_cv.total) * adjustment))
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
        desired.append(MarketValuation(
            player_id=player_id,
            market=market,
            category_value=global_cv,
            global_base_value=_money(global_cv.total),
            market_adjustment=round(adjustment, 4),
            estimated_value=_money(estimate),
            confidence_score=global_cv.confidence_score,
            price_band=price_band,
            explanation=explanation,
            calculated_at=now,
        ))

    if not desired:
        return 0

    desired_ids = [obj.player_id for obj in desired]
    existing = {
        obj.player_id: obj
        for obj in MarketValuation.objects.filter(
            market=market, player_id__in=desired_ids
        )
    }
    to_create = []
    to_update = []
    update_fields = [
        "category_value", "global_base_value", "market_adjustment",
        "estimated_value", "confidence_score", "price_band",
        "explanation", "calculated_at",
    ]
    for obj in desired:
        old = existing.get(obj.player_id)
        if old is None:
            to_create.append(obj)
        else:
            old.category_value = obj.category_value
            old.global_base_value = obj.global_base_value
            old.market_adjustment = obj.market_adjustment
            old.estimated_value = obj.estimated_value
            old.confidence_score = obj.confidence_score
            old.price_band = obj.price_band
            old.explanation = obj.explanation
            old.calculated_at = now
            to_update.append(old)

    for start in range(0, len(to_update), WRITE_BATCH_SIZE):
        MarketValuation.objects.bulk_update(
            to_update[start:start + WRITE_BATCH_SIZE],
            update_fields,
            batch_size=WRITE_BATCH_SIZE,
        )
    for start in range(0, len(to_create), WRITE_BATCH_SIZE):
        MarketValuation.objects.bulk_create(
            to_create[start:start + WRITE_BATCH_SIZE],
            batch_size=WRITE_BATCH_SIZE,
        )

    return len(desired)


def recalculate_all_markets():
    return {
        market.name: recalculate_market(market)
        for market in AuctionMarketProfile.objects.filter(is_active=True)
    }
