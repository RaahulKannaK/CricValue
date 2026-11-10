"""Auction price RANGE (₹ Cr), form trend and market signals for a player.

Version 2: a generic, pool-aware engine. There are NO player-name price tables
in the pricing path, so every player with similar evidence is valued alike
(blueprint rule: no arbitrary player-specific corrections).

Pipeline (the four layers from the blueprint)
  1. Performance   : quality_score (already opposition/competition adjusted by
                     the old engine) ranked against the whole pool -> quality index.
  2. Competition   : transferability of that record to a franchise auction. Uses
                     the player's nation strength and, for internationals, the
                     average opposition he actually faced. It is a mild factor
                     (0.65-1.0), never a blanket associate discount: facing strong
                     opposition lifts it.
  3. Player profile: potential index, consistency, evidence (confidence).
                     Confidence only sets the WIDTH of the range, never the price.
  4. Auction market: role scarcity, domestic-availability demand and "proven
                     big-stage" demand for long-serving players of elite sides.

Form is applied last as a bounded multiplier and is shown separately as a trend,
so recent form can move a price but never override long-term quality, and a hot
streak with weak consistency counts for less.

CALIBRATION holds the agreed reference ranges. It is only used by
`calibration_report()` to test the engine; it never changes a price.
"""

import datetime as dt
import math
from bisect import bisect_left, bisect_right

from .strength import nation_scale

# --------------------------------------------------------------------------
# Market configuration (edit freely; no migration or recalculation needed)
# --------------------------------------------------------------------------

MARKET = {
    "domestic_country": "india",
    "domestic_demand": 0.10,
    "role_demand": {"AR": 0.90, "WK": 0.80, "BOWL": 0.65, "BAT": 0.50},
    "unknown_country_scale": 0.75,
    "marquee_matches": 120,
    "marquee_min_scale": 0.80,
    "marquee_min_quality": 0.55,
    "marquee_max_lift": 0.22,

    # Maximum value supported by match statistics alone.
    # Scouting/potential can still contribute separately.
    "stats_only_cap": 19.0,
}

# Competition level (0-1: nation strength blended with opposition actually faced)
# -> highest neutral price the evidence can support. This is a ceiling on the
# LEVEL of competition, not on match counts. Facing strong opposition raises it.
# Transfer of a statistical record to franchise level (0.40 weak competition .. 1.0 elite)
TRANSFER_FLOOR = 0.40
# Maximum neutral auction value supported by each competition level.
# Level 0.0 = weakest competition; level 1.0 = elite competition.
LEVEL_CEILING = [
    (0.00, 3.0),
    (0.20, 5.0),
    (0.40, 8.0),
    (0.60, 12.0),
    (0.80, 17.0),
    (1.00, 23.0),
]
# F (franchise score 0-1)  ->  neutral-form price in ₹ Cr
PRICE_CURVE = [
    (0.00, 0.5), (0.25, 2.0), (0.45, 4.5), (0.60, 7.5), (0.72, 10.5),
    (0.82, 13.0), (0.90, 15.0), (0.96, 17.0), (1.00, 19.0),
]

# Scouting / market rating (0-100, stored in Player.potential_rating) -> ₹ Cr.
# This is DATA, not code: it is how franchise demand that the match statistics
# cannot see (a star whose quality score is depressed, an exceptional prospect)
# enters the model. Blended with the statistical estimate, never used alone.
SCOUT_CURVE = [(40, 2.5), (50, 4.5), (60, 6.5), (70, 9.5), (80, 12.5),
               (90, 15.5), (95, 17.5), (100, 19.0)]
SCOUT_WEIGHT = 0.80

# Blueprint section 8 bands, used only for the label.
BANDS = [
    (20, "Exceptional target"), (17, "Elite premium"), (14, "High value"),
    (10, "Strong target"), (7, "Valuable squad player"), (4, "Developing"),
    (0, "Budget / backup"),
]

# Agreed reference ranges (blueprint section 7 + owner corrections) – TEST ONLY.
CALIBRATION = {
    "V Kohli": (15, 20), "RG Sharma": (15, 20), "V Suryavanshi": (18, 20),
    "Washington Sundar": (5, 8), "Tilak Varma": (12, 16),
}

ROLE_CODE = {"Batter": "BAT", "Bowler": "BOWL", "All-rounder": "AR", "Wicketkeeper": "WK",
             "BAT": "BAT", "BOWL": "BOWL", "AR": "AR", "WK": "WK"}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _interp(points, x):
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _round_half(x, mode="nearest"):
    if mode == "down":
        return math.floor(x * 2) / 2
    if mode == "up":
        return math.ceil(x * 2) / 2
    return round(x * 2) / 2


def _fmt(x):
    return f"{x:g}"


class Pool:
    """Sorted quality / potential values of every player in the same tab."""

    def __init__(self, qualities, potentials=None):
        self.q = sorted(float(v) for v in qualities)
        self.p = sorted(float(v) for v in (potentials or []))

    @staticmethod
    def _rank(values, x, absolute):
        if len(values) < 20:                      # tiny pool: use an absolute scale
            return _clamp((x - absolute[0]) / (absolute[1] - absolute[0]))
        lo, hi = bisect_left(values, x), bisect_right(values, x)
        return (lo + hi) / 2.0 / len(values)      # mid-rank percentile

    def quality_index(self, x):
        return self._rank(self.q, float(x or 0), (25.0, 60.0))

    def potential_index(self, x):
        return self._rank(self.p, float(x or 0), (30.0, 70.0))


def band_label(mid):
    return next(label for floor, label in BANDS if mid >= floor)


def potential_label(pot_idx, matches):
    if pot_idx >= 0.85 or (pot_idx >= 0.75 and matches < 40):
        return "Exceptional"
    if pot_idx >= 0.60:
        return "High"
    if pot_idx >= 0.35:
        return "Medium"
    return "Low"


def momentum(form_pct, consistency):
    f = float(form_pct or 0)
    if f >= 45:
        label, css = "Surging", "up"
    elif f >= 15:
        label, css = "Rising", "up"
    elif f > -15:
        label, css = "Steady", "flat"
    elif f > -40:
        label, css = "Cooling", "dn"
    else:
        label, css = "Falling", "dn"
    streak = f >= 30 and float(consistency or 50) < 45
    return label, css, streak


# --------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------

def estimate(name, role, country, quality, form_pct, confidence, consistency,
             potential, matches, last_played, pool, ref_date=None, avg_opp=None,
             scouting=None):
    ref_date = ref_date or dt.date.today()
    role = ROLE_CODE.get(role, "BAT")
    conf = _clamp(float(confidence or 0) / 100.0)
    matches = int(matches or 0)

    # 2. competition: how well this record transfers to a franchise auction
    ctry = str(country or "").strip().lower()
    scale, level = competition_level(country, avg_opp)
    transfer = transfer_factor(level)

    # 1. performance: competition-adjusted quality, ranked against the pool
    qi = pool.quality_index(float(quality or 0) * transfer)

    # 3. profile: potential index
    pi = pool.potential_index(potential if potential is not None else quality)

    # 4. market: role scarcity + domestic availability
    demand = MARKET["role_demand"].get(role, 0.5)
    if ctry == MARKET["domestic_country"]:
        demand += MARKET["domestic_demand"]
    demand = _clamp(demand)

    score = _clamp(0.64 * qi + 0.21 * pi + 0.15 * demand)
    neutral = _interp(PRICE_CURVE, score)

    # proven big-stage demand (long record, elite nation, still a top performer, active)
    marquee = 0.0
    idle = (ref_date - last_played).days if last_played else 999
    if (matches >= MARKET["marquee_matches"] and scale >= MARKET["marquee_min_scale"]
            and qi >= MARKET["marquee_min_quality"] and idle <= 365):
        marquee = min(MARKET["marquee_max_lift"],
                      0.08 + (matches - MARKET["marquee_matches"]) / 1000.0 + 0.10 * (qi - 0.55))
        neutral *= 1.0 + marquee

    if scouting is None:
        neutral = min(neutral, MARKET["stats_only_cap"])
    stats_neutral = neutral
    if scouting is not None:
        market = _interp(SCOUT_CURVE, float(scouting))
        neutral = SCOUT_WEIGHT * market + (1.0 - SCOUT_WEIGHT) * stats_neutral

    # competition ceiling: the level of cricket played caps what the record can justify
    ceiling = _interp(LEVEL_CEILING, level)
    capped = neutral > ceiling
    neutral = min(neutral, ceiling)

    # form: bounded, reliability- and consistency-weighted, never above quality's say
    f = _clamp(float(form_pct or 0) / 75.0, -1.0, 1.0)
    reliability = 0.5 + 0.5 * conf
    cons = _clamp(float(consistency if consistency is not None else 60) / 100.0)
    cons_w = 0.70 + 0.30 * _clamp(cons / 0.60)           # weak consistency: streak counts less
    cap_up = 0.08 + 0.10 * qi
    cap_dn = 0.10 + 0.12 * qi
    ff = 1.0 + (cap_up * f if f >= 0 else cap_dn * f) * reliability * (cons_w if f > 0 else 1.0)

    mid = min(23.0, ceiling, neutral * ff) if ceiling < 23 else min(23.0, neutral * ff)

    # range width: evidence, inactivity, level of competition; upward skew for upside
    width = 0.09 + 0.12 * (1.0 - conf) + 0.10 * (1.0 - transfer)
    if idle > 45:
        width += min(0.08, (idle - 45) / 600.0)
    up_skew = 0.07 if (pi >= 0.75 and matches < 60) else 0.0
    low = max(0.5, mid * (1.0 - width))
    high = min(23.0, mid * (1.0 + width + up_skew))
    lo_r, hi_r = _round_half(low), _round_half(high)
    lo_r = max(0.5, lo_r)
    if hi_r - lo_r < 1.0:
        hi_r = lo_r + 1.0

    # trend = what form adds or removes
    delta = mid - neutral
    if delta >= 0.4:
        a = max(_round_half(delta * 0.8, "down"), 0.5)
        b = max(_round_half(delta * 1.2, "up"), a + 0.5)
        trend, tdir = f"▲ +{_fmt(a)}–{_fmt(b)} Cr", "up"
    elif delta <= -0.4:
        a = max(_round_half(-delta * 0.8, "down"), 0.5)
        b = max(_round_half(-delta * 1.2, "up"), a + 0.5)
        trend, tdir = f"▼ −{_fmt(a)}–{_fmt(b)} Cr", "dn"
    else:
        trend, tdir = "▬ steady", "flat"

    mlabel, mcss, streak = momentum(form_pct, consistency)
    notes = []
    if scouting is not None:
        notes.append("scouting rating applied")
    if marquee:
        notes.append("proven big-stage demand")
    if capped or transfer < 0.75:
        notes.append("record built against weaker competition")
    if streak:
        notes.append("short streak, consistency low")
    if conf < 0.5:
        notes.append("limited match evidence (wider range)")
    if idle > 120:
        notes.append("inactive recently")

    return {
        "low": lo_r, "high": hi_r, "mid": round(mid, 2), "neutral": round(neutral, 2),
        "text": f"₹{_fmt(lo_r)}–{_fmt(hi_r)} Cr",
        "trend_text": trend, "trend_dir": tdir,
        "momentum": mlabel, "momentum_css": mcss,
        "band": band_label(mid), "potential_label": potential_label(pi, matches),
        "note": "; ".join(notes),
        "factors": {"quality_index": round(qi, 2), "transfer": round(transfer, 2), "level": round(level, 2), "ceiling": round(ceiling, 1),
                    "potential_index": round(pi, 2), "demand": round(demand, 2),
                    "marquee_lift": round(marquee, 3), "stats_value": round(stats_neutral, 2),
                    "scouting": scouting, "form_factor": round(ff, 3),
                    "franchise_score": round(score, 3)},
    }


# --------------------------------------------------------------------------
# Django glue
# --------------------------------------------------------------------------

def competition_level(country, avg_opp=None):
    """0-1 competition level: nation strength, blended with opposition faced when known."""
    ctry = str(country or "").strip().lower()
    scale = MARKET["unknown_country_scale"] if ctry in ("", "unknown", "country unknown") else nation_scale(country)
    if avg_opp is None:
        return scale, scale
    opp_idx = _clamp((float(avg_opp) - 0.65) / 0.60)
    return scale, 0.5 * scale + 0.5 * opp_idx


def transfer_factor(level):
    return TRANSFER_FLOOR + (1.0 - TRANSFER_FLOOR) * _clamp(level)


def pool_from_categoryvalues(cvs, opp=None):
    """Pool of competition-adjusted quality, so a record built against weak sides
    is ranked as such against every other player."""
    cvs = list(cvs)
    opp = opp or {}
    adj = []
    for c in cvs:
        _, level = competition_level(c.player.country, opp.get(c.player_id))
        adj.append(float(c.quality_score or 0) * transfer_factor(level))
    return Pool(adj, [c.potential_score for c in cvs])


def range_for_categoryvalue(cv, pool, ref_date=None, avg_opp=None):
    role = cv.player.get_role_display() if hasattr(cv.player, "get_role_display") else cv.player.role
    return estimate(
        cv.player.name, role, cv.player.country, cv.quality_score, cv.form_score,
        cv.confidence_score, cv.consistency_score, cv.potential_score, cv.matches,
        cv.last_played, pool, ref_date, avg_opp,
        scouting=getattr(cv.player, "potential_rating", None),
    )


def opposition_levels(category, competitions=None):
    """{player_id: average opposition factor faced}; internationals only."""
    from django.db.models import Avg
    from .models import Performance
    from .valuation import INTL_CATS
    if category not in INTL_CATS:
        return {}
    qs = Performance.objects.filter(match__category=category)
    if competitions:
        qs = qs.filter(match__competition__in=competitions)
    return dict(qs.values_list("player_id").annotate(a=Avg("opp_strength")))


def calibration_report(results_by_name):
    """results_by_name: {name: estimate()-dict}. Returns lines comparing to CALIBRATION."""
    lines = []
    for name, (lo, hi) in CALIBRATION.items():
        r = results_by_name.get(name)
        if r:
            ok = r["low"] <= hi and r["high"] >= lo
            lines.append(f"{'OK ' if ok else 'OFF'} {name}: engine {r['text']} vs target ₹{lo}–{hi} Cr")
    return lines
