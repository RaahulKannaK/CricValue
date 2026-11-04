"""Value signals and the discovery engine: hidden gems, breakout players, future value.

Pure Python, no Django imports. It sits on top of price_range.estimate() (what the
auction market is modelled to pay) and intelligence.* (how the player actually plays).

Two ideas are kept deliberately separate:

  MARKET PRICE  price_range.estimate()["mid"]. Competition ceilings, evidence caps,
                role demand, big-stage reputation and scouting ratings all push it.
  WORTH         what the player's own performance, form, consistency and potential
                say, with no market effects. Shrunk towards the market price when the
                evidence is thin, so a handful of matches never produces a loud flag.

Undervalued = worth is clearly above the market price; overvalued = clearly below.
Every flag carries the reasons that drive the gap, so it can be challenged.

Nothing in here uses age inferred from match counts. Age tags need a verified
date_of_birth; without one the player gets an "early career" tag instead.

A candidate is a dict (built from CategoryValue + Player + performances):
    id, name, country, role, dob, category, matches, quality, consistency, potential,
    form, confidence, scouting, est (price_range.estimate dict),
    trend (intelligence.trend dict or None), split (intelligence.opposition_split dict)
"""

import datetime as dt

from . import intelligence as I
from .price_range import (MARKET, PRICE_CURVE, Pool, _interp, _round_half,
                          pool_from_categoryvalues, range_for_categoryvalue)
from .strength import nation_scale

CFG = {
    "gap_abs": 1.5,           # Rs Cr gap needed before a value flag is raised ...
    "gap_rel": 0.25,          # ... and at least this fraction of the market price
    "young_age": 23,
    "early_career_matches": 40,
    "cheap_price": 6.0,       # 'low-cost' means a mid price at or below this (Rs Cr)
    "associate_scale": 0.58,  # nation_scale at or below this = associate / emerging nation
    "riser_change": 0.25,     # +25% recent impact vs earlier
    "min_confidence": 35.0,   # evidence (0-100) required before a gem tag is given
    "breakout_high": 60.0,
    "breakout_medium": 45.0,
    "max_growth": 0.55,       # largest 12-month price uplift the projection will show
}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def age_on(dob, today):
    if not dob:
        return None
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


# --------------------------------------------------------------------------
# Value signal: undervalued / fair / overvalued
# --------------------------------------------------------------------------

def value_signal(c, raw_rank):
    est = c["est"]
    f = est["factors"]
    mid = est["mid"]
    conf = _clamp(float(c["confidence"] or 0) / 100.0)

    form01 = _clamp((float(c["form"] or 0) + 75.0) / 150.0)
    cons01 = _clamp(float(c["consistency"] or 0) / 100.0)
    score = _clamp(0.60 * raw_rank + 0.15 * form01 + 0.15 * f["potential_index"] + 0.10 * cons01)
    worth_raw = _interp(PRICE_CURVE, score)
    if f["scouting"] is None:
        # Same rule as the price engine: statistics alone cannot prove franchise demand, so
        # without a scouting rating "worth" is held at the same neutral cap. Otherwise every
        # top performer would be flagged undervalued purely because of that deliberate cap.
        worth_raw = min(worth_raw, MARKET["stats_only_cap"])
    shrink = 0.40 + 0.60 * conf                     # thin evidence: stay close to the market price
    worth = mid + (worth_raw - mid) * shrink
    gap = worth - mid
    need = max(CFG["gap_abs"], CFG["gap_rel"] * mid)

    label = "Undervalued" if gap >= need else "Overvalued" if gap <= -need else "Fairly valued"
    strength = "strong" if abs(gap) >= 2 * need else "moderate"

    reasons = []
    if gap > 0:
        if f["transfer"] < 0.75:
            reasons.append("market discounts a record built against weaker competition")
        if f["ceiling"] < 23 and est["neutral"] >= f["ceiling"] - 0.01:
            reasons.append("price held down by the level of competition played")
        if float(c["form"] or 0) >= 25:
            reasons.append("recent form not yet fully priced in")
        if f["potential_index"] >= 0.70:
            reasons.append("high potential")
    elif gap < 0:
        if f["marquee_lift"] > 0:
            reasons.append("price carries a big-stage reputation premium")
        if f["scouting"] is not None and f["scouting"] >= 85:
            reasons.append("scouting rating lifts the price above the statistics")
        if f["demand"] >= 0.8:
            reasons.append("scarce role keeps demand high")
        if float(c["form"] or 0) <= -25:
            reasons.append("recent form is weak")
    if conf < 0.5 and label != "Fairly valued":
        reasons.append("limited match evidence, treat as a lead not a verdict")

    return {"label": label, "strength": strength if label != "Fairly valued" else "",
            "css": {"Undervalued": "up", "Overvalued": "dn"}.get(label, "flat"),
            "worth": round(worth, 1), "market": round(mid, 1), "gap": round(gap, 1),
            "reasons": reasons}


# --------------------------------------------------------------------------
# Breakout score and future value
# --------------------------------------------------------------------------

def breakout(c, raw_rank, price_rank):
    f = c["est"]["factors"]
    conf = _clamp(float(c["confidence"] or 0) / 100.0)
    tr = c.get("trend")
    split = c.get("split") or {}
    traj01 = _clamp((tr["change"] if tr else 0.0) / 0.5)
    strong01 = (_clamp((split["strong_ratio"] - 0.9) / 0.4)
                if split.get("strong_ratio") is not None else 0.3)
    stage01 = _clamp(1.0 - c["matches"] / 80.0)
    cheap01 = 1.0 - price_rank
    raw = (0.28 * f["potential_index"] + 0.24 * traj01 + 0.16 * raw_rank
           + 0.12 * strong01 + 0.10 * cheap01 + 0.10 * stage01)
    score = 100.0 * raw * (0.65 + 0.35 * conf)
    label = ("High" if score >= CFG["breakout_high"] else
             "Medium" if score >= CFG["breakout_medium"] else "Low")
    return {"score": round(score, 1), "label": label,
            "parts": {"potential": round(f["potential_index"], 2), "trajectory": round(traj01, 2),
                      "performance": round(raw_rank, 2), "big_match": round(strong01, 2),
                      "low_price": round(cheap01, 2), "early_career": round(stage01, 2)}}


def projection(c, brk):
    """12-month price range if the current trajectory continues. A model projection, not a promise."""
    mid = c["est"]["mid"]
    conf = _clamp(float(c["confidence"] or 0) / 100.0)
    growth = _clamp((brk["score"] / 100.0 - 0.40) * 1.2, 0.0, CFG["max_growth"])
    if growth < 0.05:
        return None
    future = min(23.0, mid * (1.0 + growth), mid + 8.0)
    width = 0.15 + 0.25 * (1.0 - conf)
    lo = max(0.5, _round_half(future * (1.0 - width)))
    hi = max(lo + 1.0, _round_half(future * (1.0 + width)))
    return {"low": lo, "high": hi, "mid": round(future, 1), "growth_pct": round(growth * 100),
            "text": f"₹{lo:g}–{hi:g} Cr",
            "confidence": "low" if conf < 0.4 else "medium" if conf < 0.7 else "good"}


# --------------------------------------------------------------------------
# Building candidates
# --------------------------------------------------------------------------

def candidates_from(cvs, perfs_by_pid, opp=None, ref_date=None):
    """Turn CategoryValue-shaped rows into candidate dicts, pricing each against the whole pool.

    cvs: iterable of CategoryValue-like objects (with .player). perfs_by_pid: {player_id:
    [perf, ...]} newest first. opp: {player_id: average opposition factor faced}.
    """
    cvs = list(cvs)
    opp = opp or {}
    ref_date = ref_date or dt.date.today()
    pool = pool_from_categoryvalues(cvs, opp)
    out = []
    for cv in cvs:
        perfs = perfs_by_pid.get(cv.player_id, [])
        out.append({
            "id": cv.player_id, "name": cv.player.name, "country": cv.player.country,
            "role": cv.player.role, "dob": getattr(cv.player, "date_of_birth", None),
            "category": cv.category, "group": cv.group, "matches": cv.matches,
            "quality": float(cv.quality_score or 0), "consistency": float(cv.consistency_score or 0),
            "potential": float(cv.potential_score or 50), "form": float(cv.form_score or 0),
            "confidence": float(cv.confidence_score or 0),
            "scouting": getattr(cv.player, "potential_rating", None),
            "est": range_for_categoryvalue(cv, pool, ref_date, opp.get(cv.player_id)),
            "trend": I.trend(perfs) if perfs else None,
            "split": I.opposition_split(perfs) if perfs else None,
        })
    return out


# --------------------------------------------------------------------------
# Tagging a whole pool
# --------------------------------------------------------------------------

TAG_TITLES = {
    "young": "Young high-potential",
    "early": "Early career, high potential",
    "undervalued": "Undervalued",
    "undervalued_domestic": "Undervalued domestic",
    "associate": "Emerging nation",
    "riser": "Rapid riser",
    "strong_opp": "Strong-opposition performer",
    "low_cost": "Low-cost, high-impact",
    "breakout": "Breakout candidate",
}


def analyse_pool(cands, today=None):
    """Attach signal, tags, breakout and projection to every candidate in one tab's pool.

    Ranks are taken inside this pool, so pass everyone the tab would show (not a filtered
    subset), the same rule the price engine follows.
    """
    today = today or dt.date.today()
    if not cands:
        return []
    raw_pool = Pool([c["quality"] for c in cands], [c["potential"] for c in cands])
    mids = sorted(c["est"]["mid"] for c in cands)
    n = len(mids)

    def price_rank(m):
        lo = sum(1 for x in mids if x < m)
        hi = sum(1 for x in mids if x <= m)
        return (lo + hi) / 2.0 / n

    out = []
    for c in cands:
        f = c["est"]["factors"]
        raw_rank = raw_pool.quality_index(c["quality"])
        sig = value_signal(c, raw_rank)
        brk = breakout(c, raw_rank, price_rank(c["est"]["mid"]))
        proj = projection(c, brk)
        age = age_on(c.get("dob"), today)
        conf_ok = float(c["confidence"] or 0) >= CFG["min_confidence"]
        split = c.get("split") or {}
        tr = c.get("trend")
        pot = f["potential_index"]
        tags = []

        if age is not None and age <= CFG["young_age"] and pot >= 0.60 and conf_ok:
            tags.append("young")
        elif age is None and c["matches"] <= CFG["early_career_matches"] and pot >= 0.80 and conf_ok:
            tags.append("early")
        if sig["label"] == "Undervalued" and conf_ok:
            tags.append("undervalued")
            if str(c["category"]).startswith("DOM_"):
                tags.append("undervalued_domestic")
        country_known = str(c.get("country") or "").strip().lower() not in ("", "unknown", "country unknown")
        if (country_known and nation_scale(c["country"]) <= CFG["associate_scale"]
                and raw_rank >= 0.60 and conf_ok):
            tags.append("associate")
        if (tr and tr["change"] >= CFG["riser_change"] and tr["z"] >= 2.0
                and c["matches"] >= 15 and conf_ok):
            tags.append("riser")
        if (split.get("strong_ratio") is not None and split["strong"]["n"] >= 4
                and split["strong_ratio"] >= 1.10 and raw_rank >= 0.50 and conf_ok):
            tags.append("strong_opp")
        if c["est"]["mid"] <= CFG["cheap_price"] and raw_rank >= 0.70 and conf_ok:
            tags.append("low_cost")
        if brk["label"] == "High":
            tags.append("breakout")

        out.append(dict(c, raw_rank=round(raw_rank, 2), signal=sig, breakout=brk,
                        projection=proj, age=age, tags=tags,
                        tag_titles=[TAG_TITLES[t] for t in tags]))
    return out


def sections(results, limit=10):
    """Group analysed candidates into the discovery page sections, best first."""
    def pick(tag, key, reverse=True):
        rows = [r for r in results if tag in r["tags"]]
        return sorted(rows, key=key, reverse=reverse)[:limit]

    return [
        ("breakout", "Breakout predictions",
         "Highest breakout scores: potential, trajectory, big-match record and a price that hasn't caught up.",
         sorted([r for r in results if r["breakout"]["label"] != "Low"],
                key=lambda r: -r["breakout"]["score"])[:limit]),
        ("undervalued", "Undervalued players",
         "Performance, form and potential say they are worth more than the modelled market price.",
         pick("undervalued", lambda r: r["signal"]["gap"])),
        ("low_cost", "Low-cost, high-impact",
         f"Modelled price of ₹{CFG['cheap_price']:g} Cr or less with a top-30% performance record.",
         pick("low_cost", lambda r: r["raw_rank"])),
        ("riser", "Improving rapidly",
         "Recent matches are at least 25% better than the 30 before them, by more than normal match-to-match noise.",
         pick("riser", lambda r: r["trend"]["change"])),
        ("strong_opp", "Standing out against strong opposition",
         "Impact against strong sides is at least 10% above their overall average.",
         pick("strong_opp", lambda r: r["split"]["strong_ratio"])),
        ("young", "Young, high potential",
         f"Verified age {CFG['young_age']} or under, high potential score. "
         "Players with no recorded date of birth appear as early-career below instead.",
         pick("young", lambda r: -(r["age"] or 99))),
        ("early", "Early career, high potential",
         f"{CFG['early_career_matches']} matches or fewer and a high potential score. Age not recorded.",
         pick("early", lambda r: r["est"]["factors"]["potential_index"])),
        ("associate", "Emerging nations",
         "Players from associate and emerging nations who rank in the top 40% of the pool on performance.",
         pick("associate", lambda r: r["raw_rank"])),
    ]
