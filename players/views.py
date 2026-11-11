
import datetime as dt

from django.db.models import Count, Max
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .categories import (
    TABS,
    TAB_BY_SLUG,
    TAB_BY_KEY,
    GROUPS,
    group_of,
    group_title,
)

from .models import (
    Player,
    Match,
    CategoryValue,
    AuctionMarketProfile,
    MarketValuation,
)

from .valuation import SETTINGS, history
from .tiers import TIER_TITLES, BANDS

from .price_range import (
    range_for_categoryvalue,
    pool_from_categoryvalues,
    opposition_levels,
    Pool,
)

from . import discovery, intel_data, intelligence


RANGE_AXIS = 24.0


# ============================================================
# HOME
# ============================================================

def home(request):
    return redirect("tab", slug="t20")


# ============================================================
# AUCTION TAB / PLAYER LIST
# ============================================================

def tab(request, slug):

    t = TAB_BY_SLUG.get(slug)

    if not t:
        raise Http404

    key = t["key"]
    g = request.GET

    q = g.get("q", "")
    country = g.get("country", "")
    role = g.get("role", "")

    grp = g.get("grp", "")
    sort = g.get("sort", "total")
    inactive = bool(g.get("inactive"))

    tier = g.get("tier", "")

    # --------------------------------------------------------
    # MATCH DATA
    # --------------------------------------------------------

    ms = Match.objects.filter(
        category=key
    )

    chips = []
    comps = {}

    if key in GROUPS:

        counts = {}

        for r in (
            ms.values("competition")
            .annotate(n=Count("id"))
        ):

            gs = group_of(
                key,
                r["competition"],
            )

            comps.setdefault(
                gs,
                [],
            ).append(r["competition"])

            counts[gs] = (
                counts.get(gs, 0)
                + r["n"]
            )

        order = (
            [s for s, _, _ in GROUPS[key]]
            + ["other"]
        )

        chips = [
            {
                "slug": s,
                "title": group_title(s),
                "n": counts[s],
            }
            for s in order
            if s in counts
        ]

    if grp not in comps:
        grp = ""

    ref_qs = (
        ms.filter(
            competition__in=comps[grp]
        )
        if grp else ms
    )

    ref = ref_qs.aggregate(
        m=Max("date")
    )["m"]

    # --------------------------------------------------------
    # PLAYER QUERY
    # --------------------------------------------------------

    cutoff = (
        dt.date.today()
        - dt.timedelta(
            days=t["active_days"]
        )
    )

    qs = (
        CategoryValue.objects
        .filter(
            category=key,
            group=grp,
        )
        .select_related("player")
    )

    if not inactive:

        qs = qs.filter(
            matches__gte=SETTINGS[key]["min"],
            last_played__gte=cutoff,
        )

    # --------------------------------------------------------
    # COMPLETE PLAYER POOL
    # --------------------------------------------------------

    opp = opposition_levels(
        key,
        comps[grp] if grp else None,
    )

    # Optimized pool construction.
    pool = pool_from_categoryvalues(
        qs,
        opp,
    )

    # Evaluate the unfiltered pool once.
    pool_all = list(qs)

    raw_pool = Pool(
        [
            c.quality_score
            for c in pool_all
        ],
        [
            c.potential_score
            for c in pool_all
        ],
    )

    # --------------------------------------------------------
    # SEARCH FILTERS
    # --------------------------------------------------------

    if q:
        qs = qs.filter(
            player__name__icontains=q
        )

    if country:
        qs = qs.filter(
            player__country=country
        )

    if role:
        qs = qs.filter(
            player__role=role
        )

    rows = list(qs)

    # --------------------------------------------------------
    # AUCTION VALUATION
    # --------------------------------------------------------

    for c in rows:

        rng = range_for_categoryvalue(
            c,
            pool,
            ref or dt.date.today(),
            opp.get(c.player_id),
        )

        c.est = rng

        c.range_mid = rng["mid"]
        c.range_text = rng["text"]

        c.trend_text = rng["trend_text"]
        c.trend_dir = rng["trend_dir"]

        c.lo_pct = round(
            rng["low"] / RANGE_AXIS * 100,
            1,
        )

        c.w_pct = round(
            (rng["high"] - rng["low"])
            / RANGE_AXIS * 100,
            1,
        )

        c.mid_pct = round(
            rng["mid"] / RANGE_AXIS * 100,
            1,
        )

        c.signal = discovery.value_signal(
            {
                "est": rng,
                "form": c.form_score,
                "consistency": c.consistency_score,
                "confidence": c.confidence_score,
            },
            raw_pool.quality_index(
                c.quality_score
            ),
        )

    # --------------------------------------------------------
    # SORTING
    # --------------------------------------------------------

    keyfn = {
        "total": lambda c: c.range_mid,
        "form": lambda c: c.form_score,
        "value": lambda c: c.signal["gap"],
    }.get(
        sort,
        lambda c: c.range_mid,
    )

    rows = sorted(
        rows,
        key=keyfn,
        reverse=True,
    )

    # --------------------------------------------------------
    # PLAYER DISPLAY INFORMATION
    # --------------------------------------------------------

    for c in rows:

        c.active = bool(
            c.last_played
            and c.last_played >= cutoff
        )

        c.tier_title = TIER_TITLES.get(
            c.tier,
            "Unrated",
        )

        lo, hi = BANDS.get(
            c.tier,
            BANDS["unrated"],
        )

        c.band = f"{lo:g}-{hi:g}"

        c.price_band_title = (
            c.price_band or "unrated"
        ).replace(
            "_",
            " ",
        ).title()

    if tier in TIER_TITLES:

        rows = [
            c for c in rows
            if c.tier == tier
        ]

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    summary = {
        "n": len(rows),

        "rising": sum(
            1 for c in rows
            if c.est["momentum"] in (
                "Surging",
                "Rising",
            )
        ),

        "falling": sum(
            1 for c in rows
            if c.est["momentum"] in (
                "Cooling",
                "Falling",
            )
        ),

        "undervalued": sum(
            1 for c in rows
            if c.signal["label"] == "Undervalued"
        ),

        "elite": sum(
            1 for c in rows
            if c.range_mid >= 14
        ),

        "scouted": sum(
            1 for c in rows
            if c.player.potential_rating is not None
        ),
    }

    # --------------------------------------------------------
    # COUNTRIES
    # --------------------------------------------------------

    countries = list(
        CategoryValue.objects
        .filter(
            category=key,
            group=grp,
        )
        .exclude(
            player__country__in=[
                "",
                "Unknown",
            ]
        )
        .order_by(
            "player__country"
        )
        .values_list(
            "player__country",
            flat=True,
        )
        .distinct()
    )

    # --------------------------------------------------------
    # RENDER
    # --------------------------------------------------------

    return render(
        request,
        "players/list.html",
        {
            "tabs": TABS,
            "current": slug,
            "t": t,
            "rows": rows,
            "ref": ref,

            "chips": chips,
            "grp": grp,
            "grp_title": group_title(grp),

            "summary": summary,
            "axis": RANGE_AXIS,

            "tier": tier,
            "tier_choices": list(
                TIER_TITLES.items()
            ),

            "q": q,
            "country": country,
            "role": role,
            "sort": sort,
            "inactive": inactive,

            "countries": countries,
            "roles": Player.role.field.choices,
        },
    )


# ============================================================
# AUCTION MARKETS
# ============================================================

def markets(request):

    profiles = AuctionMarketProfile.objects.filter(
        is_active=True
    )

    return render(
        request,
        "players/markets.html",
        {
            "tabs": TABS,
            "current": "",
            "profiles": profiles,
        },
    )


# ============================================================
# MARKET DETAIL
# ============================================================

def market_detail(request, slug):

    market = get_object_or_404(
        AuctionMarketProfile,
        slug=slug,
        is_active=True,
    )

    qs = (
        MarketValuation.objects
        .filter(market=market)
        .select_related(
            "player",
            "category_value",
        )
    )

    q = request.GET.get(
        "q",
        "",
    ).strip()

    role = request.GET.get(
        "role",
        "",
    )

    if q:
        qs = qs.filter(
            player__name__icontains=q
        )

    if role:
        qs = qs.filter(
            player__role=role
        )

    rows = list(
        qs.order_by(
            "-estimated_value",
            "player__name",
        )
    )

    top = max(
        (
            float(v.estimated_value)
            for v in rows
        ),
        default=1.0,
    ) or 1.0

    for v in rows:

        v.pct = int(
            float(v.estimated_value)
            / top * 100
        )

    return render(
        request,
        "players/market_detail.html",
        {
            "tabs": TABS,
            "current": "",
            "market": market,
            "rows": rows,
            "q": q,
            "role": role,
            "roles": Player.role.field.choices,
        },
    )


# ============================================================
# CHART HELPER
# ============================================================

def _chart(points, w=320, h=90, pad=8):

    vals = [
        v for _, v in points
    ]

    lo = min(vals)
    hi = max(vals)

    span = (hi - lo) or 1

    n = len(points)

    xy = [
        (
            pad + i * (w - 2 * pad)
            / max(1, n - 1),

            h - pad
            - (v - lo) / span
            * (h - 2 * pad),
        )
        for i, (_, v) in enumerate(points)
    ]

    return (
        " ".join(
            f"{x:.1f},{y:.1f}"
            for x, y in xy
        ),
        f"{xy[-1][0]:.1f}",
        f"{xy[-1][1]:.1f}",
    )


# ============================================================
# OPTIMIZED PLAYER DETAIL
# ============================================================

def detail(request, pk):

    # --------------------------------------------------------
    # PLAYER
    # --------------------------------------------------------

    p = get_object_or_404(
        Player,
        pk=pk,
    )

    # --------------------------------------------------------
    # PERFORMANCE DATA
    # --------------------------------------------------------

    all_perfs = list(
        p.performances
        .select_related("match")
    )

    # Group performances once.
    performances_by_category = {}

    for f in all_perfs:

        category = f.match.category

        performances_by_category.setdefault(
            category,
            [],
        ).append(f)

    # --------------------------------------------------------
    # CATEGORY VALUES
    # --------------------------------------------------------

    cat_values = list(
        p.cat_values
        .filter(group="")
        .select_related("player")
        .order_by("category")
    )

    charts = []

    # --------------------------------------------------------
    # CATEGORY VALUATION AND CHARTS
    # --------------------------------------------------------

    for v in cat_values:

        fs = performances_by_category.get(
            v.category,
            [],
        )

        cutoff = (
            dt.date.today()
            - dt.timedelta(
                days=TAB_BY_KEY[v.category]["active_days"]
            )
        )

        peers = (
            CategoryValue.objects
            .filter(
                category=v.category,
                group="",
                matches__gte=SETTINGS[v.category]["min"],
                last_played__gte=cutoff,
            )
        )

        # Opposition information.
        opp = opposition_levels(
            v.category
        )

        # Optimized pool calculation.
        pool = pool_from_categoryvalues(
            peers,
            opp,
        )

        # Player valuation.
        v.est = range_for_categoryvalue(
            v,
            pool,
            v.last_played or dt.date.today(),
            opp.get(p.pk),
        )

        v.range_text = v.est["text"]

        # Historical performance chart.
        pts = history(
            fs,
            v.category,
            float(v.base_value),
            v.form_score,
            v.ceiling,
        )

        if len(pts) >= 2:

            poly, lx, ly = _chart(
                pts
            )

            charts.append(
                {
                    "title": TAB_BY_KEY[v.category]["title"],
                    "v": v,
                    "poly": poly,
                    "lx": lx,
                    "ly": ly,
                    "d1": pts[0][0],
                    "d2": pts[-1][0],
                    "n": len(pts),
                    "change": round(
                        pts[-1][1] - pts[0][1],
                        1,
                    ),
                }
            )

    # --------------------------------------------------------
    # PLAYER INTELLIGENCE
    # --------------------------------------------------------

    intel = []

    # Cache discovery results per category for this request.
    discovery_cache = {}

    for v in cat_values:

        fs = performances_by_category.get(
            v.category,
            [],
        )[:intel_data.PERF_CAP]

        if len(fs) < intel_data.MIN_MATCHES_FOR_PROFILE:
            continue

        profile = intelligence.build_profile(
            fs
        )

        item = {
            "title": TAB_BY_KEY[v.category]["title"],
            "v": v,
            "profile": profile,
            "similar": intel_data.similar_for(v),
            "signal": None,
            "found": None,
        }

        # Avoid repeating discovery lookups for the same category.
        if v.category not in discovery_cache:

            discovery_cache[v.category] = (
                intel_data.discovery_results(
                    v.category
                )
            )

        found = next(
            (
                r for r in discovery_cache[v.category]
                if r["id"] == p.pk
            ),
            None,
        )

        if found:

            item.update(
                signal=found["signal"],
                found=found,
            )

        intel.append(item)

    # --------------------------------------------------------
    # ALL CATEGORY VALUES
    # --------------------------------------------------------

    vals = (
        p.cat_values
        .select_related("player")
        .order_by(
            "category",
            "group",
        )
    )

    # --------------------------------------------------------
    # RENDER PLAYER DETAIL
    # --------------------------------------------------------

    return render(
        request,
        "players/detail.html",
        {
            "tabs": TABS,
            "current": "",
            "p": p,
            "charts": charts,
            "intel": intel,
            "vals": vals,
            "perfs": all_perfs[:15],
        },
    )


# ============================================================
# DISCOVERY
# ============================================================

def discover(request):
    """
    Discovery engine:
    hidden gems, undervalued players,
    breakout and future-value predictions.
    """

    choices = [
        t for t in TABS
        if t["key"] != "DOM_IN"
    ]

    slug = request.GET.get(
        "cat",
        "t20",
    )

    t = TAB_BY_SLUG.get(slug)

    if not t or t["key"] == "DOM_IN":
        raise Http404

    results = intel_data.discovery_results(
        t["key"]
    )

    return render(
        request,
        "players/discover.html",
        {
            "tabs": TABS,
            "current": "discover",
            "t": t,
            "choices": choices,
            "slug": slug,
            "sections": discovery.sections(results),
            "pool": len(results),
            "flagged": sum(
                1 for r in results
                if r["tags"]
            ),
        },
    )
