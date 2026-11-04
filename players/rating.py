"""Compatibility helpers for older imports and role inference."""
from decimal import Decimal
from .valuation import impact, quality_score


def base_from_history(player, n=60, min_matches=5):
    perfs = list(player.performances.select_related("match").order_by("-match__date")[:n])
    if len(perfs) < min_matches:
        return None
    score = quality_score(perfs, perfs[0].match.category or "T20")
    from .tiers import quality_anchor, experience_price_cap
    value = quality_anchor(score)
    return Decimal(str(round(min(23.0, max(0.50, value)), 2)))


def infer_role(player, n=40):
    perfs = list(player.performances.order_by("-match__date")[:n])
    if len(perfs) < 5:
        return None
    bat = sum(1 for p in perfs if p.balls >= 8) / len(perfs)
    bowl = sum(1 for p in perfs if p.overs >= 2) / len(perfs)
    if bat >= .35 and bowl >= .35:
        return "AR"
    return "BOWL" if bowl >= .35 else "BAT"
