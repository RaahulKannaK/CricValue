
"""
Auction price RANGE (₹ Cr), form trend and market signals.

Optimized version:
- Avoids N+1 player relationship queries.
- Uses values_list() for pool construction.
- Preserves the existing valuation algorithm.
- Preserves competition, scouting, form and auction adjustments.
"""

import datetime as dt
import math
from bisect import bisect_left, bisect_right

from .strength import nation_scale


# ============================================================
# MARKET CONFIGURATION
# ============================================================

MARKET = {
    "domestic_country": "india",
    "domestic_demand": 0.10,
    "role_demand": {
        "AR": 0.90,
        "WK": 0.80,
        "BOWL": 0.65,
        "BAT": 0.50,
    },
    "unknown_country_scale": 0.75,
    "marquee_matches": 120,
    "marquee_min_scale": 0.80,
    "marquee_min_quality": 0.55,
    "marquee_max_lift": 0.22,
    "stats_only_cap": 9.0,
}

LEVEL_CEILING = [
    (0.30, 3.0),
    (0.40, 4.5),
    (0.58, 6.5),
    (0.75, 12.5),
    (0.90, 17.0),
    (1.00, 23.0),
]

TRANSFER_FLOOR = 0.40

PRICE_CURVE = [
    (0.00, 0.5),
    (0.25, 2.0),
    (0.45, 4.5),
    (0.60, 7.5),
    (0.72, 10.5),
    (0.82, 13.0),
    (0.90, 15.0),
    (0.96, 17.0),
    (1.00, 19.0),
]

SCOUT_CURVE = [
    (40, 2.5),
    (50, 4.5),
    (60, 6.5),
    (70, 9.5),
    (80, 12.5),
    (90, 15.5),
    (95, 17.5),
    (100, 19.0),
]

SCOUT_WEIGHT = 0.80

BANDS = [
    (20, "Exceptional target"),
    (17, "Elite premium"),
    (14, "High value"),
    (10, "Strong target"),
    (7, "Valuable squad player"),
    (4, "Developing"),
    (0, "Budget / backup"),
]

CALIBRATION = {
    "V Kohli": (15, 20),
    "RG Sharma": (15, 20),
    "V Suryavanshi": (18, 20),
    "Washington Sundar": (5, 8),
    "Tilak Varma": (12, 16),
}

ROLE_CODE = {
    "Batter": "BAT",
    "Bowler": "BOWL",
    "All-rounder": "AR",
    "Wicketkeeper": "WK",
    "BAT": "BAT",
    "BOWL": "BOWL",
    "AR": "AR",
    "WK": "WK",
}


# ============================================================
# HELPERS
# ============================================================

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


# ============================================================
# POOL
# ============================================================

class Pool:
    """Sorted quality and potential values for the player pool."""

    def __init__(self, qualities, potentials=None):
        self.q = sorted(float(v) for v in qualities)
        self.p = sorted(float(v) for v in (potentials or []))

    @staticmethod
    def _rank(values, x, absolute):

        if len(values) < 20:
            return _clamp(
                (x - absolute[0]) /
                (absolute[1] - absolute[0])
            )

        lo = bisect_left(values, x)
        hi = bisect_right(values, x)

        return (lo + hi) / 2.0 / len(values)

    def quality_index(self, x):
        return self._rank(
            self.q,
            float(x or 0),
            (25.0, 60.0),
        )

    def potential_index(self, x):
        return self._rank(
            self.p,
            float(x or 0),
            (30.0, 70.0),
        )


# ============================================================
# LABELS
# ============================================================

def band_label(mid):
    return next(
        label for floor, label in BANDS
        if mid >= floor
    )


def potential_label(pot_idx, matches):

    if pot_idx >= 0.85 or (
        pot_idx >= 0.75 and matches < 40
    ):
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

    streak = (
        f >= 30 and
        float(consistency or 50) < 45
    )

    return label, css, streak


# ============================================================
# COMPETITION
# ============================================================

def competition_level(country, avg_opp=None):

    ctry = str(country or "").strip().lower()

    scale = (
        MARKET["unknown_country_scale"]
        if ctry in ("", "unknown", "country unknown")
        else nation_scale(country)
    )

    if avg_opp is None:
        return scale, scale

    opp_idx = _clamp(
        (float(avg_opp) - 0.65) / 0.60
    )

    return scale, 0.5 * scale + 0.5 * opp_idx


def transfer_factor(level):
    return (
        TRANSFER_FLOOR
        + (1.0 - TRANSFER_FLOOR) * _clamp(level)
    )


# ============================================================
# OPTIMIZED CATEGORY VALUE POOL
# ============================================================

def pool_from_categoryvalues(cvs, opp=None):
    """
    Optimized pool construction.

    QuerySets use values_list() with a SQL JOIN to Player.

    This prevents individual database queries for:
        c.player.country

    when processing thousands of CategoryValue records.

    The existing valuation formula remains unchanged.
    """

    opp = opp or {}

    adjusted_quality = []
    potentials = []

    if hasattr(cvs, "values_list"):

        rows = cvs.values_list(
            "quality_score",
            "potential_score",
            "player__country",
            "player_id",
        )

    else:

        rows = (
            (
                c.quality_score,
                c.potential_score,
                c.player.country,
                c.player_id,
            )
            for c in cvs
        )

    for quality, potential, country, player_id in rows:

        _, level = competition_level(
            country,
            opp.get(player_id),
        )

        adjusted_quality.append(
            float(quality or 0)
            * transfer_factor(level)
        )

        potentials.append(
            float(potential or 0)
        )

    return Pool(
        adjusted_quality,
        potentials,
    )


# ============================================================
# AUCTION VALUATION ENGINE
# ============================================================

def estimate(
    name,
    role,
    country,
    quality,
    form_pct,
    confidence,
    consistency,
    potential,
    matches,
    last_played,
    pool,
    ref_date=None,
    avg_opp=None,
    scouting=None,
):

    ref_date = ref_date or dt.date.today()

    role = ROLE_CODE.get(role, "BAT")

    conf = _clamp(
        float(confidence or 0) / 100.0
    )

    matches = int(matches or 0)

    # Competition adjustment
    ctry = str(country or "").strip().lower()

    scale, level = competition_level(
        country,
        avg_opp,
    )

    transfer = transfer_factor(level)

    # Performance quality
    qi = pool.quality_index(
        float(quality or 0) * transfer
    )

    # Player potential
    pi = pool.potential_index(
        potential if potential is not None else quality
    )

    # Market demand
    demand = MARKET["role_demand"].get(role, 0.5)

    if ctry == MARKET["domestic_country"]:
        demand += MARKET["domestic_demand"]

    demand = _clamp(demand)

    score = _clamp(
        0.64 * qi
        + 0.21 * pi
        + 0.15 * demand
    )

    neutral = _interp(
        PRICE_CURVE,
        score,
    )

    # Proven big-stage demand
    marquee = 0.0

    idle = (
        (ref_date - last_played).days
        if last_played else 999
    )

    if (
        matches >= MARKET["marquee_matches"]
        and scale >= MARKET["marquee_min_scale"]
        and qi >= MARKET["marquee_min_quality"]
        and idle <= 365
    ):

        marquee = min(
            MARKET["marquee_max_lift"],
            0.08
            + (matches - MARKET["marquee_matches"]) / 1000.0
            + 0.10 * (qi - 0.55),
        )

        neutral *= 1.0 + marquee

    # Scouting adjustment
    if scouting is None:

        neutral = min(
            neutral,
            MARKET["stats_only_cap"],
        )

    stats_neutral = neutral

    if scouting is not None:

        market = _interp(
            SCOUT_CURVE,
            float(scouting),
        )

        neutral = (
            SCOUT_WEIGHT * market
            + (1.0 - SCOUT_WEIGHT) * stats_neutral
        )

    # Competition ceiling
    ceiling = _interp(
        LEVEL_CEILING,
        level,
    )

    capped = neutral > ceiling

    neutral = min(
        neutral,
        ceiling,
    )

    # Form adjustment
    f = _clamp(
        float(form_pct or 0) / 75.0,
        -1.0,
        1.0,
    )

    reliability = 0.5 + 0.5 * conf

    cons = _clamp(
        float(
            consistency
            if consistency is not None
            else 60
        ) / 100.0
    )

    cons_w = (
        0.70
        + 0.30 * _clamp(cons / 0.60)
    )

    cap_up = 0.08 + 0.10 * qi
    cap_dn = 0.10 + 0.12 * qi

    ff = 1.0 + (
        cap_up * f
        if f >= 0
        else cap_dn * f
    ) * reliability * (
        cons_w if f > 0 else 1.0
    )

    mid = min(
        23.0,
        ceiling,
        neutral * ff,
    )

    # Auction range width
    width = (
        0.09
        + 0.12 * (1.0 - conf)
        + 0.10 * (1.0 - transfer)
    )

    if idle > 45:
        width += min(
            0.08,
            (idle - 45) / 600.0,
        )

    up_skew = (
        0.07
        if pi >= 0.75 and matches < 60
        else 0.0
    )

    low = max(
        0.5,
        mid * (1.0 - width),
    )

    high = min(
        23.0,
        mid * (1.0 + width + up_skew),
    )

    lo_r = max(
        0.5,
        _round_half(low),
    )

    hi_r = _round_half(high)

    if hi_r - lo_r < 1.0:
        hi_r = lo_r + 1.0

    # Form trend
    delta = mid - neutral

    if delta >= 0.4:

        a = max(
            _round_half(delta * 0.8, "down"),
            0.5,
        )

        b = max(
            _round_half(delta * 1.2, "up"),
            a + 0.5,
        )

        trend = f"▲ +{_fmt(a)}–{_fmt(b)} Cr"
        tdir = "up"

    elif delta <= -0.4:

        a = max(
            _round_half(-delta * 0.8, "down"),
            0.5,
        )

        b = max(
            _round_half(-delta * 1.2, "up"),
            a + 0.5,
        )

        trend = f"▼ −{_fmt(a)}–{_fmt(b)} Cr"
        tdir = "dn"

    else:

        trend = "▬ steady"
        tdir = "flat"

    mlabel, mcss, streak = momentum(
        form_pct,
        consistency,
    )

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
        "low": lo_r,
        "high": hi_r,
        "mid": round(mid, 2),
        "neutral": round(neutral, 2),

        "text": f"₹{_fmt(lo_r)}–{_fmt(hi_r)} Cr",

        "trend_text": trend,
        "trend_dir": tdir,

        "momentum": mlabel,
        "momentum_css": mcss,

        "band": band_label(mid),
        "potential_label": potential_label(pi, matches),

        "note": "; ".join(notes),

        "factors": {
            "quality_index": round(qi, 2),
            "transfer": round(transfer, 2),
            "level": round(level, 2),
            "ceiling": round(ceiling, 1),
            "potential_index": round(pi, 2),
            "demand": round(demand, 2),
            "marquee_lift": round(marquee, 3),
            "stats_value": round(stats_neutral, 2),
            "scouting": scouting,
            "form_factor": round(ff, 3),
            "franchise_score": round(score, 3),
        },
    }


# ============================================================
# CATEGORY VALUE INTEGRATION
# ============================================================

def range_for_categoryvalue(
    cv,
    pool,
    ref_date=None,
    avg_opp=None,
):

    player = cv.player

    role = player.get_role_display()

    return estimate(
        player.name,
        role,
        player.country,
        cv.quality_score,
        cv.form_score,
        cv.confidence_score,
        cv.consistency_score,
        cv.potential_score,
        cv.matches,
        cv.last_played,
        pool,
        ref_date,
        avg_opp,
        scouting=player.potential_rating,
    )


# ============================================================
# OPPOSITION LEVELS
# ============================================================

def opposition_levels(category, competitions=None):
    """
    Returns player_id -> average opposition strength.

    Internationals only.
    """

    from django.db.models import Avg

    from .models import Performance
    from .valuation import INTL_CATS

    if category not in INTL_CATS:
        return {}

    qs = Performance.objects.filter(
        match__category=category
    )

    if competitions:
        qs = qs.filter(
            match__competition__in=competitions
        )

    return dict(
        qs.values_list("player_id")
        .annotate(a=Avg("opp_strength"))
    )


# ============================================================
# CALIBRATION REPORT
# ============================================================

def calibration_report(results_by_name):

    lines = []

    for name, (lo, hi) in CALIBRATION.items():

        r = results_by_name.get(name)

        if r:

            ok = (
                r["low"] <= hi
                and r["high"] >= lo
            )

            lines.append(
                f"{'OK ' if ok else 'OFF '}"
                f"{name}: engine {r['text']} "
                f"vs target ₹{lo}–{hi} Cr"
            )

    return lines
