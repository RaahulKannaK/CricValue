"""Database glue for the player-intelligence and discovery engines.

All the actual logic lives in intelligence.py and discovery.py (pure Python, unit
tested). This module only loads rows, shapes them for those engines and caches the
slow pool-wide results.

Caching: pool-wide results (discovery, similarity vectors) are cached per tab for
CACHE_SECONDS. After `recalc_values` they refresh within that time; call
`clear_cache()` to refresh immediately.
"""

import datetime as dt
from types import SimpleNamespace as NS

from django.core.cache import cache
from django.db.models import Count, Max, Q, Sum

from . import discovery, intelligence
from .categories import TAB_BY_KEY
from .models import CategoryValue, Match, Performance
from .price_range import opposition_levels
from .valuation import SETTINGS

CACHE_SECONDS = 15 * 60
PERF_CAP = 40       # most recent matches per player fed to the engines
MIN_MATCHES_FOR_PROFILE = 5

# Format used for style reference rates (PAR) for each tab.
FMT_OF_CATEGORY = {"T20": "T20", "ODI": "ODI", "TEST": "TEST", "LEAGUE": "T20",
                   "DOM_T20": "T20", "DOM_ODI": "ODI", "DOM_TEST": "TEST", "DOM_IN": "T20"}


def clear_cache():

    for key in TAB_BY_KEY:
        cache.delete_many([f"cricvalue:discover:{key}", f"cricvalue:vectors:{key}"])


def pool_queryset(key, group=""):
    """The players a tab shows by default: enough matches and recently active."""
    cutoff = dt.date.today() - dt.timedelta(days=TAB_BY_KEY[key]["active_days"])
    return (CategoryValue.objects
            .filter(category=key, group=group, matches__gte=SETTINGS[key]["min"], last_played__gte=cutoff)
            .select_related("player"))


def perf_shim(player_id, runs, balls, wickets, conceded, overs, opp, phases, date, fmt, category, strength):
    return NS(player_id=player_id, runs=runs, balls=balls, wickets=wickets, runs_conceded=conceded,
              overs=overs, opp_strength=opp, phases=phases or {},
              match=NS(date=date, fmt=fmt, category=category, strength=strength))


def perfs_by_player(category, player_ids=None):
    """{player_id: [perf, ...]} newest first, at most PERF_CAP each, loaded in one query."""
    qs = Performance.objects.filter(match__category=category)
    if player_ids is not None:
        qs = qs.filter(player_id__in=list(player_ids))
    rows = qs.order_by("player_id", "-match__date").values_list(
        "player_id", "runs", "balls", "wickets", "runs_conceded", "overs", "opp_strength", "phases",
        "match__date", "match__fmt", "match__category", "match__strength")
    out = {}
    for row in rows.iterator(chunk_size=5000):
        lst = out.setdefault(row[0], [])
        if len(lst) < PERF_CAP:
            lst.append(perf_shim(*row))
    return out


# --------------------------------------------------------------------------
# Discovery (pool-wide)
# --------------------------------------------------------------------------

def discovery_results(key):
    """Analysed candidates for one tab (cached). See discovery.analyse_pool."""
    ck = f"cricvalue:discover:{key}"
    res = cache.get(ck)
    if res is None:
        cvs = list(pool_queryset(key))
        ref = Match.objects.filter(category=key).aggregate(m=Max("date"))["m"] or dt.date.today()
        opp = opposition_levels(key)
        perfs = perfs_by_player(key, [c.player_id for c in cvs])
        res = discovery.analyse_pool(discovery.candidates_from(cvs, perfs, opp, ref))
        cache.set(ck, res, CACHE_SECONDS)
    return res


# --------------------------------------------------------------------------
# Similar players
# --------------------------------------------------------------------------

def _totals(key, player_ids=None):
    qs = Performance.objects.filter(match__category=key)
    if player_ids is not None:
        qs = qs.filter(player_id__in=list(player_ids))
    rows = qs.values("player_id").annotate(
        matches=Count("id"), bat_inns=Count("id", filter=Q(balls__gt=0)),
        runs=Sum("runs"), balls=Sum("balls"), spells=Count("id", filter=Q(overs__gt=0)),
        overs=Sum("overs"), conceded=Sum("runs_conceded"), wickets=Sum("wickets"))
    return {r["player_id"]: {k: (r[k] or 0) for k in
                             ("matches", "bat_inns", "runs", "balls", "spells", "overs", "conceded", "wickets")}
            for r in rows}


def _vector(cv, totals, key):
    return intelligence.feature_vector(
        cv.player.role, cv.quality_score, cv.consistency_score, cv.potential_score, cv.form_score,
        totals, FMT_OF_CATEGORY.get(key, "T20"))


def category_vectors(key):
    """({player_id: feature vector}, {player_id: name}) for the tab's pool (cached)."""
    ck = f"cricvalue:vectors:{key}"
    got = cache.get(ck)
    if got is None:
        cvs = list(pool_queryset(key))
        tot = _totals(key, [c.player_id for c in cvs])
        vectors = {c.player_id: _vector(c, tot.get(c.player_id, {}), key) for c in cvs}
        got = (vectors, {c.player_id: c.player.name for c in cvs})
        cache.set(ck, got, CACHE_SECONDS)
    return got


def similar_for(cv, k=5):
    """Players most like this CategoryValue's player in the same format."""
    vectors, names = category_vectors(cv.category)
    if cv.player_id not in vectors:                       # inactive player: not in the cached pool
        vectors = dict(vectors)
        vectors[cv.player_id] = _vector(cv, _totals(cv.category, [cv.player_id]).get(cv.player_id, {}),
                                        cv.category)
    return intelligence.similar_players(cv.player_id, vectors, names, k)


def cached_discovery_results(key):
    """Return discovery analysis only when already warm; never build a full pool on a player click."""
    return cache.get(f"cricvalue:discover:{key}")


def cached_similar_for(cv, k=5):
    """Return similar players from a warm vector cache without triggering a pool scan."""
    got = cache.get(f"cricvalue:vectors:{cv.category}")
    if got is None:
        return []
    vectors, names = got
    if cv.player_id not in vectors:
        totals = _totals(cv.category, [cv.player_id]).get(cv.player_id, {})
        vectors = dict(vectors)
        vectors[cv.player_id] = _vector(cv, totals, cv.category)
    return intelligence.similar_players(cv.player_id, vectors, names, k)
