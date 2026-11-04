"""Format-specific player quality, performance impact and recent form."""

import datetime as dt
import math
import statistics
from decimal import Decimal

BASELINES = {"T20": 8.5, "ODI": 5.5, "TEST": 3.0}
PRIOR_AVG = 20.0

INTL_CATS = ("T20", "ODI", "TEST")

SETTINGS = {
    "T20": dict(window=40, min=5, prior_w=12, scale=1.0),
    "ODI": dict(window=30, min=5, prior_w=10, scale=1.0),
    "TEST": dict(window=20, min=4, prior_w=6, scale=1.0),
    "LEAGUE": dict(window=40, min=5, prior_w=12, scale=1.0),
    "DOM_IN": dict(window=40, min=5, prior_w=10, scale=1.0),
    "DOM_T20": dict(window=40, min=5, prior_w=10, scale=1.0),
    "DOM_ODI": dict(window=40, min=5, prior_w=10, scale=1.0),
    "DOM_TEST": dict(window=30, min=5, prior_w=8, scale=1.0),
}

FORM_WINDOWS = (
    (0, 5, 0.50),
    (5, 15, 0.30),
    (15, 30, 0.20),
)

FORM_CAP = 75.0
FORM_SOFTNESS = 2.2
FORM_SPREAD = 40.0
HALF_LIFE_DAYS = 180


def raw_from_stats(runs, balls, wickets, conceded, overs, fmt):
    """Calculate single-match batting and bowling impact."""

    runs = float(runs or 0)
    balls = float(balls or 0)
    wickets = float(wickets or 0)
    conceded = float(conceded or 0)
    overs = float(overs or 0)

    bat = 0.0
    bowl = 0.0

    if balls > 0:
        strike_rate = runs / balls * 100.0
        par_sr = {
            "T20": 125.0,
            "ODI": 90.0,
            "TEST": 50.0,
        }.get(fmt, 100.0)

        bat = runs * min(1.45, max(0.55, strike_rate / par_sr))

    if overs > 0:
        economy = conceded / overs
        par = BASELINES.get(fmt, 8.5)

        bowl = (
            wickets * 30.0
            + max(-10.0, min(15.0, (par - economy) * 4.0))
        )

    if balls > 0 and overs > 0:
        return max(bat, bowl) + 0.5 * min(bat, bowl)

    return bat + bowl


def raw_impact(perf):
    return raw_from_stats(
        perf.runs,
        perf.balls,
        perf.wickets,
        perf.runs_conceded,
        perf.overs,
        perf.match.fmt,
    )



def match_factor(perf):
    """
    International:
        Opponent XI strength × calibrated competition adjustment.

    Domestic and league:
        Existing competition strength logic.

    Competition and opponent strength remain independent.
    """

    category = str(
        perf.match.category or ""
    ).strip().upper()

    if category in INTL_CATS:

        # Actual opponent strength from the historical XI engine.
        opponent = getattr(perf, "opp_strength", None)

        if opponent is None:
            opponent = 1.0

        opponent = max(
            0.65,
            min(1.35, float(opponent)),
        )

        # Competition strength from Match.strength.
        competition = getattr(
            perf.match,
            "strength",
            None,
        )

        if competition is None:
            competition = 1.0

        competition = max(
            0.0,
            min(1.0, float(competition)),
        )

        # Gentle adjustment around the international scale.
        competition_factor = (
            0.85 + 0.15 * competition
        )

        return opponent * competition_factor

    # Preserve existing domestic and franchise behaviour.
    value = getattr(perf.match, "strength", None)

    if value is None:
        value = 0.70

    return max(
        0.45,
        min(1.20, float(value)),
    )


def impact(perf):
    """Competition-adjusted individual match impact."""

    return max(
        0.0,
        min(100.0, raw_impact(perf) * match_factor(perf)),
    )


def freshness(last_date, as_of=None):
    if not last_date:
        return 0.0

    today = as_of or dt.date.today()
    days = max(0, (today - last_date).days)

    return 0.5 ** (days / HALF_LIFE_DAYS)


def _mean(items):
    return sum(items) / len(items) if items else PRIOR_AVG


def experience_score(matches):
    """
    Experience measures evidence volume.
    It is NOT included directly in player quality.
    """

    matches = max(0, int(matches or 0))

    return round(
        100.0 * (1.0 - math.exp(-matches / 35.0)),
        1,
    )


def confidence_score(matches):
    """Reliability of the valuation estimate."""

    matches = max(0, int(matches or 0))

    return round(
        100.0 * (1.0 - math.exp(-matches / 24.0)),
        1,
    )


def recent_level(perfs, as_of=None):
    """Blended recent impact with gradual freshness adjustment."""

    items = list(perfs)

    if not items:
        return 0.0

    values = [impact(p) for p in items]

    blended = 0.0
    used = 0.0

    for start, end, weight in FORM_WINDOWS:
        sample = values[start:end]

        if sample:
            blended += _mean(sample) * weight
            used += weight

    blended = blended / used if used else PRIOR_AVG

    fresh = freshness(items[0].match.date, as_of)

    return 20.0 + (blended - 20.0) * fresh


def recent_form(perfs, as_of=None, avail=1.0):
    availability = max(0.0, min(1.0, float(avail)))

    return recent_level(perfs, as_of) * (
        0.90 + 0.10 * availability
    )


def rating_of(perfs, cat):
    settings = SETTINGS.get(cat, SETTINGS["T20"])

    items = list(perfs)[:settings["window"]]

    if not items:
        return PRIOR_AVG

    values = [impact(p) for p in items]

    count = len(values)

    return (
        count * _mean(values)
        + settings["prior_w"] * PRIOR_AVG
    ) / (count + settings["prior_w"])


def consistency_score(perfs, window=30):
    values = [
        impact(p)
        for p in list(perfs)[:window]
    ]

    if len(values) < 3:
        return 50.0

    avg = _mean(values)

    if avg <= 0:
        return 0.0

    deviation = statistics.pstdev(values)

    cv = deviation / max(avg, 1.0)

    return max(
        0.0,
        min(100.0, 100.0 - cv * 55.0),
    )


def quality_score(perfs, cat):
    """
    Long-term ability.

    Experience is deliberately excluded from the quality calculation.
    The score uses actual competition-adjusted performance and consistency.
    """

    items = list(perfs)

    if not items:
        return 0.0

    settings = SETTINGS.get(cat, SETTINGS["T20"])

    career = [
        impact(p)
        for p in items[:settings["window"]]
    ]

    medium = [
        impact(p)
        for p in items[:15]
    ]

    career_avg = _mean(career)
    medium_avg = _mean(medium)

    consistency = consistency_score(items)

    score = (
        0.60 * career_avg
        + 0.25 * medium_avg
        + 0.15 * consistency
    )

    # Small samples cannot immediately produce elite classifications.
    sample_factor = min(1.0, len(items) / 20.0)

    score = 50.0 + (score - 50.0) * sample_factor

    return round(max(0.0, min(100.0, score)), 2)


def form_pct(eff, peers):
    peers = list(peers)

    if len(peers) < 5:
        return 0.0

    median = statistics.median(peers)

    deviation = max(
        statistics.pstdev(peers),
        3.0,
    )

    result = FORM_CAP * math.tanh(
        (eff - median) / deviation / FORM_SOFTNESS
    )

    return max(-FORM_CAP, min(FORM_CAP, result))


def base_value(perfs, cat):
    settings = SETTINGS.get(cat, SETTINGS["T20"])

    items = list(perfs)[:settings["window"]]

    if len(items) < settings["min"]:
        return None

    score = quality_score(items, cat)

    value = 0.50 + (score / 100.0) ** 1.65 * 22.5

    return Decimal(
        str(round(max(0.50, min(23.0, value)), 2))
    )


def history(perfs, cat, base, current_pct, ceiling, n=15):
    from .tiers import final_price

    points = []
    items = list(perfs)

    for i in range(min(n, len(items))):
        subset = items[i:]

        if len(subset) < SETTINGS.get(cat, SETTINGS["T20"])["min"]:
            continue

        points.append((
            items[i].match.date,
            recent_form(
                subset,
                as_of=items[i].match.date,
            ),
        ))

    if not points:
        return []

    shift = current_pct - (
        (points[0][1] - 20.0) / 8.0 * FORM_SPREAD
    )

    return list(reversed([
        (
            date,
            round(
                final_price(
                    base,
                    (value - 20.0) / 8.0 * FORM_SPREAD + shift,
                    ceiling,
                ),
                2,
            ),
        )
        for date, value in points
    ]))