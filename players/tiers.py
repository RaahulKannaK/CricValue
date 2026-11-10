
"""Player classification and auction pricing."""

TIER_TITLES = {
    "vip": "VIP",
    "balanced": "Balanced",
    "others": "Others",
    "unrated": "Unrated",
}

PRICE_BANDS = {
    "premium": (16.0, 23.0),
    "balanced": (8.0, 15.0),
    "value": (0.5, 7.0),
    "unrated": (0.5, 7.0),
}

BANDS = {
    "vip": PRICE_BANDS["premium"],
    "balanced": PRICE_BANDS["balanced"],
    "others": PRICE_BANDS["value"],
    "unrated": PRICE_BANDS["unrated"],
}

MIN_PRICE = 0.50
FORM_CAP = 75.0
UNRATED_BELOW = 5

MIN_MATCHES = {
    "T20": (8, 20),
    "ODI": (8, 18),
    "TEST": (6, 12),
    "LEAGUE": (8, 20),
    "DOM_IN": (8, 20),
    "DOM_T20": (8, 20),
    "DOM_ODI": (8, 20),
    "DOM_TEST": (6, 15),
}

VIP_QUALITY = 68.0
BALANCED_QUALITY = 48.0
PREMIUM_QUALITY = 82.0

MAX_ROLE_SCARCITY = 1.05


def _pct(values, fraction):
    return values[
        min(len(values) - 1, int((len(values) - 1) * fraction))
    ]


def cutoffs(ratings):
    values = sorted(ratings)

    if not values:
        return 0.0, float("inf"), float("inf"), 0.0

    return (
        values[0],
        _pct(values, 0.55),
        _pct(values, 0.85),
        values[-1],
    )


def tier_of(cat, matches, rating, cuts=None, quality=None):
    if matches < UNRATED_BELOW:
        return "unrated"

    score = float(rating if quality is None else quality)

    minimum_balanced, minimum_vip = MIN_MATCHES.get(
        cat, (8, 20)
    )

    if score >= VIP_QUALITY and matches >= minimum_vip:
        return "vip"

    if score >= BALANCED_QUALITY and matches >= minimum_balanced:
        return "balanced"

    return "others"


def price_band_of(tier, quality):
    if tier == "unrated":
        return "unrated"

    if quality >= PREMIUM_QUALITY:
        return "premium"

    if quality >= BALANCED_QUALITY:
        return "balanced"

    return "value"


def band_price(
    tier,
    rating,
    cuts,
    scale=1.0,
    matches=None,
    cat="T20",
    quality=None,
    price_band=None,
    role_scarcity=1.0,
):
    """Calculate starting valuation within its assigned price band."""

    band = price_band or price_band_of(
        tier,
        quality if quality is not None else rating,
    )

    low_price, high_price = PRICE_BANDS[band]

    scale = max(0.25, min(1.0, float(scale or 1.0)))

    low_price *= scale
    high_price *= scale

    q = max(
        0.0,
        min(
            100.0,
            float(quality if quality is not None else rating),
        ),
    )

    ranges = {
        "premium": (PREMIUM_QUALITY, 100.0),
        "balanced": (BALANCED_QUALITY, PREMIUM_QUALITY),
        "value": (0.0, BALANCED_QUALITY),
        "unrated": (0.0, BALANCED_QUALITY),
    }

    lower, upper = ranges[band]

    position = max(
        0.0,
        min(1.0, (q - lower) / max(1.0, upper - lower)),
    )

    sample = min(
        1.0,
        max(0.0, float(matches or 0) / 80.0),
    )

    position *= 0.70 + 0.30 * sample

    price = low_price + position * (high_price - low_price)

    scarcity = max(
        1.0,
        min(
            MAX_ROLE_SCARCITY,
            float(role_scarcity or 1.0),
        ),
    )

    price *= scarcity

    return round(
        max(MIN_PRICE, min(high_price, price)),
        2,
    )


def ceiling_for(
    tier,
    scale=1.0,
    base=None,
    price_band=None,
    matches=None,
):
    """
    Return the actual maximum permitted by the assigned base-price band.

    `base` is retained for compatibility with existing callers.
    It must not increase the permitted ceiling.
    """

    band = price_band or (
        "premium"
        if tier == "vip"
        else "balanced"
        if tier == "balanced"
        else "unrated"
        if tier == "unrated"
        else "value"
    )

    scale = max(0.25, min(1.0, float(scale or 1.0)))

    return round(PRICE_BANDS[band][1] * scale, 2)


def final_price(
    base,
    form_pct,
    ceiling,
    confidence=100.0,
):
    """
    Apply recent form without exceeding the permitted ceiling.
    Invalid base/ceiling combinations raise an error.
    """

    base = max(MIN_PRICE, float(base))
    ceiling = float(ceiling)

    if ceiling < base:
        raise ValueError(
            f"Base price {base:.2f} exceeds ceiling {ceiling:.2f}"
        )

    form = max(
        -FORM_CAP,
        min(FORM_CAP, float(form_pct)),
    )

    confidence = max(
        0.0,
        min(100.0, float(confidence)),
    ) / 100.0

    reliability = 0.30 + 0.70 * confidence

    if form >= 0:
        uplift = (form / FORM_CAP) * 0.45 * reliability
        price = base * (1.0 + uplift)
    else:
        reduction = (
            abs(form) / FORM_CAP
        ) * 0.25 * reliability

        price = base * (1.0 - reduction)

    return round(
        max(MIN_PRICE, min(ceiling, price)),
        2,
    )
