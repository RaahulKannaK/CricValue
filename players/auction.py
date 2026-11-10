"""CricValue auction-value model. Pure Python (no Django), so it can be tested on its own.

    market score S = ability percentile + potential + (form effect)
    price          = soft_cap( curve(S) x price_mult )

Nothing here is a hard ceiling or a tie-prone clamp: the curve is smooth, and prices
above SOFT_START are compressed smoothly towards PRICE_MAX, so players stay differentiated.
"""
import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from statistics import mean, pstdev

from .valuation import FORM_CAP, FORM_WINDOWS, HALF_LIFE_DAYS, form_pct

PRICE_MIN, PRICE_MAX = 0.5, 23.0
CURVE_POWER = 5.0            # higher = fewer players at the top
SOFT_START = 16.0            # above this, prices are compressed smoothly towards PRICE_MAX
POT_MAX = 0.07               # most a verified young talent can add to the market score
POT_DATA_SHARE = 0.4         # share of that available when only match data (no date of birth) is known
FORM_UP, FORM_DOWN = 0.08, 0.04   # market-score change for full hot / cold form
DEMAND_MAX = 0.05            # bidding-war premium for the very top of the pool
RISK_MAX = 0.10              # largest price discount for a tiny sample
APPEAR_FULL = {"T20": 12, "ODI": 8, "TEST": 6, "LEAGUE": 10, "DOM_IN": 8}   # matches/yr of a regular
AGE_POINTS = [(18, 1.0), (20, 1.0), (22, 0.8), (24, 0.5), (26, 0.25), (28, 0.08), (30, 0.0)]


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def smoothstep(x):
    x = clamp(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def pool_percentile(pool, x, fallback_scale=(10.0, 50.0)):
    """Mid-rank percentile (0-1) of x inside a sorted pool; absolute fallback for tiny pools."""
    n = len(pool)
    if n < 10:
        lo, hi = fallback_scale
        return clamp((x - lo) / (hi - lo), 0.0, 1.0)
    return (bisect_left(pool, x) + bisect_right(pool, x)) / 2.0 / n


def age_years(dob, today):
    return (today - dob).days / 365.25 if dob else None


def age_factor(age):
    if age <= AGE_POINTS[0][0]:
        return AGE_POINTS[0][1]
    for (a0, f0), (a1, f1) in zip(AGE_POINTS, AGE_POINTS[1:]):
        if age <= a1:
            return f0 + (f1 - f0) * (age - a0) / (a1 - a0)
    return 0.0


def soft_cap(raw):
    if raw <= SOFT_START:
        return max(PRICE_MIN, raw)
    room = PRICE_MAX - SOFT_START
    return SOFT_START + room * (1.0 - math.exp(-(raw - SOFT_START) / room))


def price_at(s, mult=1.0):
    curve = PRICE_MIN + (PRICE_MAX - PRICE_MIN) * max(0.0, s) ** CURVE_POWER
    return soft_cap(curve * mult)


def total_price(s0, mult, form_effect, reliability):
    """Price with form applied. form_effect is -1..+1, reliability 0..1."""
    e = clamp(form_effect, -1.0, 1.0) * reliability
    return price_at(s0 + (FORM_UP if e >= 0 else FORM_DOWN) * e, mult)


# ---- player-level measures -------------------------------------------------------------
def career_level(vals, dates, as_of, window=80, half_life=730.0, prior=20.0, prior_w=6.0):
    """Recency-weighted career mean impact; the prior is deliberately weak, so a small
    sample is not automatically marked down (confidence is handled separately)."""
    tw = tv = 0.0
    for v, d in zip(vals[:window], dates[:window]):
        w = 0.5 ** (max(0, (as_of - d).days) / half_life)
        tw += w
        tv += w * v
    return (tv + prior_w * prior) / (tw + prior_w)


def recent_level_vals(vals, dates, as_of):
    """Blended last-5 / next-10 / next-15 level. Absence fades it towards neutral (20)."""
    if not vals:
        return 0.0
    acc = used = 0.0
    for start, end, w in FORM_WINDOWS:
        sample = vals[start:end]
        if sample:
            acc += mean(sample) * w
            used += w
    level = acc / used
    fresh = 0.5 ** (max(0, (as_of - dates[0]).days) / HALF_LIFE_DAYS)
    return 20.0 + (level - 20.0) * fresh


def consistency(vals, window=40):
    v = vals[:window]
    if len(v) < 3:
        return 45.0
    m = mean(v)
    if m <= 0:
        return 0.0
    return clamp(100.0 - pstdev(v) / max(m, 1.0) * 42.0, 0.0, 100.0)


def confidence(n):
    return 100.0 * (1.0 - math.exp(-max(0, n) / 28.0))


def experience(n):
    return min(100.0, 100.0 * (1.0 - math.exp(-max(0, n) / 32.0)))


def form_reliability(cat, n, vals, dates, as_of):
    """How far recent form can be trusted: sample size, streak vs longer record,
    appearances in the last year, and a cluster of games right after a long gap."""
    conf = confidence(n) / 100.0
    sustain = 1.0
    if len(vals) >= 13:
        r, longer = mean(vals[:5]), mean(vals[5:30])
        sustain = 1.0 - 0.5 * clamp((r - longer) / max(longer, 10.0), 0.0, 1.0)
    appear = min(1.0, sum(1 for d in dates if (as_of - d).days <= 365) / APPEAR_FULL.get(cat, 10))
    cluster = 1.0
    if len(dates) >= 6 and (dates[0] - dates[4]).days <= 30 and (dates[4] - dates[5]).days >= 60:
        cluster = 0.75
    return clamp((0.3 + 0.7 * conf) * sustain * cluster * (0.5 + 0.5 * appear), 0.0, 1.0)


def potential(age, p_ability, p_level, n):
    """(market-score points, 0-100 score, source). Needs evidence of real quality."""
    evidence = clamp((max(p_ability, p_level) - 0.55) / 0.35, 0.0, 1.0)
    if age is not None:
        f, src = age_factor(age), "age"
    else:
        early = clamp((30 - n) / 20.0, 0.0, 1.0)
        f = POT_DATA_SHARE * early * (1.0 if p_level >= p_ability else 0.5)
        src = "data"
    return POT_MAX * f * evidence, round(100.0 * f * evidence, 1), src


def class_of(p_ability, n):
    if n < 5:
        return "unrated"
    return "vip" if p_ability >= 0.88 else "balanced" if p_ability >= 0.55 else "others"


def value(cat, n, vals, dates, as_of, level, eff, form_pct, ability_pool, eff_pool,
          age=None, manual_demand=1.0, scarcity=1.0):
    p_ab = pool_percentile(ability_pool, level)
    p_lv = pool_percentile(eff_pool, eff, (5.0, 45.0))
    conf = confidence(n) / 100.0
    cons = consistency(vals)
    rf = form_reliability(cat, n, vals, dates, as_of)
    pts, pot_score, src = potential(age, p_ab, p_lv, n)
    s0 = p_ab + pts
    demand = 1.0 + DEMAND_MAX * smoothstep((s0 - 0.85) / 0.15)
    mult = scarcity * demand * (manual_demand or 1.0) * (1.0 - RISK_MAX * (1.0 - conf))
    e = form_pct / FORM_CAP
    base = price_at(s0, mult)
    total = total_price(s0, mult, e, rf)
    u = 0.06 + 0.14 * (1.0 - conf) + 0.05 * (1.0 - cons / 100.0) + (0.03 if src == "data" else 0.0)
    return dict(p_ability=p_ab, s0=s0, mult=mult, base=base, total=total, reliability=rf,
                potential_score=pot_score, potential_source=src, consistency=cons,
                confidence=conf * 100.0, experience=experience(n),
                low=max(PRICE_MIN, total * (1 - u)), high=total * (1 + u))


def price_all(recs, today):
    """Value every record. Each rec is a dict with: cat, group, rc (BAT/BOWL/AR), n, vals,
    dates (newest first), level, recent, avail, active, age, demand.
    The result for each is stored in rec["out"]."""
    for r in recs:
        r["eff"] = r["recent"] * (0.90 + 0.10 * r["avail"])
    # small role-scarcity modifier (same idea as before)
    counts, totals, kinds = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in recs:
        counts[(r["cat"], r["group"], r["rc"])] += 1
    for (cat, group, _rc), c in counts.items():
        totals[(cat, group)] += c
        kinds[(cat, group)] += 1
    # comparison pools: ability and recent level among active, rated players of the whole tab
    ab, ef, peers_pool = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in recs:
        if r["group"] == "" and r["active"] and r["n"] >= 8:
            for key in ((r["cat"], r["rc"]), (r["cat"], "ALL")):
                ab[key].append(r["level"])
                ef[key].append(r["eff"])
        if r["active"] and r["avail"] >= 0.35:
            peers_pool[(r["cat"], r["group"], r["rc"])].append(r["eff"])
    for pool in list(ab.values()) + list(ef.values()):
        pool.sort()
    for r in recs:
        cat, rc, grp = r["cat"], r["rc"], r["group"]
        apool = ab.get((cat, rc), [])
        if len(apool) < 20:
            apool = ab.get((cat, "ALL"), [])
        epool = ef.get((cat, rc), [])
        if len(epool) < 20:
            epool = ef.get((cat, "ALL"), [])
        peers = peers_pool.get((cat, grp, rc), [])
        if len(peers) < 5:
            peers = peers_pool.get((cat, grp, "BAT"), [])
        avg_role = totals[(cat, grp)] / max(1, kinds[(cat, grp)])
        own = counts[(cat, grp, rc)]
        scarcity = min(1.08, 1.0 + max(0.0, avg_role - own) / max(1.0, avg_role) * 0.08)
        pct = form_pct(r["eff"], peers)
        out = value(cat, r["n"], r["vals"], r["dates"], today, r["level"], r["eff"], pct,
                    apool, epool, r["age"], r["demand"], scarcity)
        out["form_pct"] = pct
        r["out"] = out
    return recs
