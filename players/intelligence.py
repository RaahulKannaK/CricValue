"""Player Intelligence: DNA, strengths and weaknesses, trends, phase and opposition splits.

Pure Python, no Django imports, so every rule here can be unit-tested with plain
objects. A "perf" is anything shaped like a Performance row (newest first):

    perf.runs / balls / wickets / runs_conceded / overs / opp_strength / phases
    perf.match.date / fmt / category / strength

Impact values come from valuation.impact(), so they are already adjusted for the
opposition faced and the competition played in. Nothing here invents data: when a
split needs more evidence than a player has, that part is left out (None) instead of
being guessed.

PAR holds league-wide reference rates used only to say "above / below the norm".
They are round, tunable constants (not fitted to your database): recalibrate them
once you have enough phase data imported.
"""

import statistics

from . import valuation as V

PHASES = ("pp", "mid", "death")
PHASE_LABEL = {"pp": "Powerplay", "mid": "Middle overs", "death": "Death overs"}

PAR = {
    "T20": {"bat_sr": {"all": 125.0, "pp": 125.0, "mid": 118.0, "death": 150.0},
            "bowl_eco": {"all": 8.5, "pp": 7.8, "mid": 7.4, "death": 9.6}},
    "ODI": {"bat_sr": {"all": 90.0, "pp": 85.0, "mid": 80.0, "death": 115.0},
            "bowl_eco": {"all": 5.5, "pp": 5.3, "mid": 5.2, "death": 7.0}},
    "TEST": {"bat_sr": {"all": 50.0}, "bowl_eco": {"all": 3.0}},
}
# (balls in a typical spell, wickets an average regular takes in that spell)
WICKET_PAR = {"T20": (24, 1.0), "ODI": (48, 1.0), "TEST": (90, 1.5)}

STRONG_OPP, WEAK_OPP = 1.05, 0.90            # international opponent-strength factor
STRONG_COMP, WEAK_COMP = 0.85, 0.60          # domestic / league competition strength
TREND_Z = 1.75                               # ~4% one-sided false-positive rate on pure noise
MIN_SPLIT = 4                                # matches needed on each side of a split


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _scale(x, lo, hi):
    """Map x linearly so lo -> 0 and hi -> 100, clamped."""
    return round(100.0 * _clamp((x - lo) / (hi - lo)), 1)


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _fmt_of(perfs):
    """Most common match format in the sample ('T20', 'ODI' or 'TEST')."""
    counts = {}
    for p in perfs:
        counts[p.match.fmt] = counts.get(p.match.fmt, 0) + 1
    return max(counts, key=counts.get) if counts else "T20"


# --------------------------------------------------------------------------
# Opposition split
# --------------------------------------------------------------------------

def opposition_class(perf):
    """'strong', 'weak' or 'mid' for the opposition / competition of one performance."""
    if str(perf.match.category or "").upper() in V.INTL_CATS:
        opp = getattr(perf, "opp_strength", None)
        opp = 1.0 if opp is None else float(opp)
        return "strong" if opp >= STRONG_OPP else "weak" if opp <= WEAK_OPP else "mid"
    comp = getattr(perf.match, "strength", None)
    comp = 0.70 if comp is None else float(comp)
    return "strong" if comp >= STRONG_COMP else "weak" if comp <= WEAK_COMP else "mid"


def opposition_split(perfs, min_n=MIN_SPLIT):
    """Average impact against strong and weak opposition.

    Impact is already opposition-adjusted, so a high number against strong sides is
    a genuinely big-match record; a number that only exists against weak sides is
    flagged by `inflated`.
    """
    buckets = {"strong": [], "weak": [], "mid": []}
    for p in perfs:
        buckets[opposition_class(p)].append(V.impact(p))
    out = {k: {"n": len(v), "impact": round(_mean(v), 1) if len(v) >= min_n else None}
           for k, v in buckets.items()}
    overall = round(_mean(V.impact(p) for p in perfs), 1) if perfs else 0.0
    s, w = out["strong"]["impact"], out["weak"]["impact"]
    out["overall"] = overall
    out["strong_ratio"] = round(s / overall, 2) if s is not None and overall > 0 else None
    out["inflated"] = bool(s is not None and w is not None and s > 0 and w / s >= 1.35)
    return out


# --------------------------------------------------------------------------
# Batting / bowling usage
# --------------------------------------------------------------------------

def batting_profile(perfs):
    fmt = _fmt_of(perfs)
    inns = [p for p in perfs if p.balls and p.balls > 0]
    if not inns:
        return None
    runs = sum(p.runs for p in inns)
    balls = sum(p.balls for p in inns)
    sr = runs / balls * 100.0
    par = PAR[fmt]["bat_sr"]["all"]
    positions = [p.phases.get("pos") for p in inns if getattr(p, "phases", None) and p.phases.get("pos")]
    return {"fmt": fmt, "innings": len(inns), "runs": runs, "balls": balls,
            "sr": round(sr, 1), "par_sr": par, "sr_ratio": round(sr / par, 3),
            "avg": round(runs / len(inns), 1), "avg_balls": round(balls / len(inns), 1),
            "pos": int(statistics.median(positions)) if len(positions) >= 3 else None,
            "share": round(len(inns) / len(perfs), 2)}


def bowling_profile(perfs):
    fmt = _fmt_of(perfs)
    spells = [p for p in perfs if p.overs and p.overs > 0]
    if not spells:
        return None
    overs = sum(p.overs for p in spells)
    conceded = sum(p.runs_conceded for p in spells)
    wkts = sum(p.wickets for p in spells)
    eco = conceded / overs
    par = PAR[fmt]["bowl_eco"]["all"]
    window, par_w = WICKET_PAR[fmt]
    rate = wkts / (overs * 6.0 / window) / par_w          # 1.0 = average wicket-taking
    return {"fmt": fmt, "spells": len(spells), "overs": round(overs, 1), "wickets": wkts,
            "eco": round(eco, 2), "par_eco": par, "eco_ratio": round(par / eco, 3) if eco > 0 else 1.0,
            "wk_ratio": round(rate, 2),
            "sr": round(overs * 6.0 / wkts, 1) if wkts else None,
            "share": round(len(spells) / len(perfs), 2)}


def phase_summary(perfs, min_coverage=0.25):
    """Batting and bowling by phase, from the per-match phase data.

    Returns None for Tests or when too few matches carry phase data (older imports).
    Only matches in the player's main format are used so phase boundaries agree.
    """
    fmt = _fmt_of(perfs)
    if fmt not in ("T20", "ODI"):
        return None
    used = [p for p in perfs if p.match.fmt == fmt and getattr(p, "phases", None)]
    if not perfs or len(used) / len(perfs) < min_coverage or len(used) < 3:
        return None
    bat = {ph: [0, 0, 0] for ph in PHASES}
    bowl = {ph: [0, 0, 0] for ph in PHASES}
    for p in used:
        for ph in PHASES:
            for i, v in enumerate(p.phases.get("bat", {}).get(ph, (0, 0, 0))):
                bat[ph][i] += v
            for i, v in enumerate(p.phases.get("bowl", {}).get(ph, (0, 0, 0))):
                bowl[ph][i] += v
    total_balls = sum(v[1] for v in bat.values()) or 1
    total_legal = sum(v[1] for v in bowl.values()) or 1
    out = {"fmt": fmt, "coverage": round(len(used) / len(perfs), 2), "matches": len(used),
           "bat": {}, "bowl": {}}
    for ph, (runs, balls, outs) in bat.items():
        if balls:
            sr = runs / balls * 100.0
            out["bat"][ph] = {"runs": runs, "balls": balls, "outs": outs, "sr": round(sr, 1),
                              "avg": round(runs / outs, 1) if outs else None,
                              "share": round(balls / total_balls, 2),
                              "ratio": round(sr / PAR[fmt]["bat_sr"][ph], 2)}
    for ph, (conc, legal, wk) in bowl.items():
        if legal:
            eco = conc / (legal / 6.0)
            out["bowl"][ph] = {"overs": round(legal / 6.0, 1), "wickets": wk, "eco": round(eco, 2),
                               "share": round(legal / total_legal, 2),
                               "ratio": round(PAR[fmt]["bowl_eco"][ph] / eco, 2) if eco > 0 else 1.0}
    return out


# --------------------------------------------------------------------------
# Trend, progression and form
# --------------------------------------------------------------------------

def trend(perfs):
    """Recent 10 matches against the 30 before them. None when there is too little history."""
    vals = [V.impact(p) for p in perfs]
    if len(vals) < 12:
        return None
    recent, prior = vals[:10], vals[10:40]
    if len(prior) < 5:
        return None
    r, b = _mean(recent), _mean(prior)
    # Shrink towards 'no change' when the earlier sample is small.
    change = (r - b) / max(b, 15.0) * min(1.0, len(prior) / 15.0)
    # Significance: a 10-match average is noisy, so a big swing alone is not a trend.
    se = (statistics.pvariance(recent) / len(recent) + statistics.pvariance(prior) / len(prior)) ** 0.5
    z = (r - b) / max(se, 1.0)
    label = ("Improving" if change >= 0.20 and z >= TREND_Z else
             "Declining" if change <= -0.20 and z <= -TREND_Z else "Stable")
    return {"change": round(change, 3), "z": round(z, 2), "label": label,
            "recent": round(r, 1), "prior": round(b, 1),
            "css": {"Improving": "up", "Declining": "dn"}.get(label, "flat")}


def progression(perfs):
    """Average impact per calendar year (years with at least 3 matches), oldest first."""
    years = {}
    for p in perfs:
        years.setdefault(p.match.date.year, []).append(V.impact(p))
    rows = [{"year": y, "impact": round(_mean(v), 1), "matches": len(v)}
            for y, v in sorted(years.items()) if len(v) >= 3]
    arc = None
    if len(rows) >= 3:
        peak = max(rows, key=lambda r: r["impact"])
        last = rows[-1]
        if last["impact"] >= 0.95 * peak["impact"]:
            arc = "At career peak"
        elif last["impact"] <= 0.80 * peak["impact"]:
            arc = f"Below {peak['year']} peak"
        else:
            arc = "Close to peak"
    return {"years": rows, "arc": arc}


def form_vs_longterm(perfs):
    """Recent form (last 8) against long-term level, plus how reliable the output is."""
    vals = [V.impact(p) for p in perfs]
    if len(vals) < 8:
        return None
    recent, long_ = _mean(vals[:8]), _mean(vals)
    ratio = recent / max(long_, 10.0)
    label = ("Peaking" if ratio >= 1.35 else "In form" if ratio >= 1.12 else
             "On par" if ratio >= 0.88 else "Below par" if ratio >= 0.70 else "Slump")
    cons = V.consistency_score(perfs)
    rel = ("Metronome" if cons >= 62 else "Steady" if cons >= 48 else
           "Streaky" if cons >= 35 else "Volatile")
    return {"recent": round(recent, 1), "long_term": round(long_, 1), "ratio": round(ratio, 2),
            "label": label, "consistency": round(cons, 1), "reliability": rel}


# --------------------------------------------------------------------------
# DNA
# --------------------------------------------------------------------------

def batting_archetype(bp, ph):
    if not bp or bp["innings"] < 5:
        return None
    r, pos, fmt = bp["sr_ratio"], bp["pos"], bp["fmt"]
    if fmt == "TEST":
        if pos and pos <= 2:
            return "Test Opener" if r < 1.1 else "Attacking Test Opener"
        return "Grafter" if r < 0.85 else "Attacking Test Batter" if r >= 1.2 else "Test Batter"
    death_share = (ph or {}).get("bat", {}).get("death", {}).get("share", 0.0)
    if pos:
        if pos >= 8:
            return "Lower-Order Batter"
        if pos <= 2:
            return "Explosive Opener" if r >= 1.12 else "Anchor Opener" if r < 0.95 else "Opening Batter"
        if pos <= 4:
            return "Attacking Top-Order Batter" if r >= 1.12 else "Anchor" if r < 0.95 else "Top-Order Batter"
        if death_share >= 0.35 or (pos >= 6 and r >= 1.10):
            return "Finisher"
        return "Power Hitter" if r >= 1.2 else "Middle-Order Batter"
    return "Aggressor" if r >= 1.15 else "Accumulator" if r < 0.92 else "Balanced Batter"


def bowling_archetype(bw, ph):
    if not bw or bw["spells"] < 5:
        return None
    fmt, er, wk = bw["fmt"], bw["eco_ratio"], bw["wk_ratio"]
    if fmt == "TEST":
        return "Strike Bowler" if wk >= 1.3 else "Control Bowler" if er >= 1.1 else "Workhorse"
    share = {k: v["share"] for k, v in (ph or {}).get("bowl", {}).items()}
    if share.get("pp", 0) >= 0.45 and er >= 0.95:
        return "New-Ball Specialist"
    if share.get("death", 0) >= 0.35:
        return "Death-Overs Specialist" if er >= 0.95 else "Death-Overs Option"
    if share.get("mid", 0) >= 0.60:
        return "Middle-Overs Wicket-Taker" if wk >= 1.3 else "Middle-Overs Controller" if er >= 1.05 else "Middle-Overs Bowler"
    return "Strike Bowler" if wk >= 1.3 else "Economy Controller" if er >= 1.1 else "Workhorse"


def dna(bp, bw, ph):
    """Playing-style label, e.g. 'Explosive Opener + Death-Overs Specialist'."""
    bat = batting_archetype(bp, ph)
    bowl = bowling_archetype(bw, ph)
    # Real batting involvement: a regular who faces enough balls (not a tail-ender who bats at 10).
    min_balls = {"T20": 9.0, "ODI": 14.0, "TEST": 25.0}.get(bp["fmt"] if bp else "T20", 9.0)
    bat_main = bool(bat) and bp["share"] >= 0.5 and bp["avg_balls"] >= min_balls
    bowl_main = bool(bowl) and bw["share"] >= 0.5
    # A bowler who occasionally bats (or the reverse) is described by the main skill only.
    parts = [x for x, main in ((bat, bat_main), (bowl, bowl_main)) if x and main]
    if not parts:
        parts = [x for x in (bat, bowl) if x][:1]
    return {"label": " + ".join(parts) if parts else "Profile still forming",
            "batting": bat, "bowling": bowl}


def traits(bp, bw, split, form, perfs):
    """0-100 trait scores for the profile bars; a trait is omitted if it can't be measured."""
    out = []
    if bp and bp["innings"] >= 5:
        out.append({"key": "aggression", "label": "Aggression", "score": _scale(bp["sr_ratio"], 0.70, 1.40),
                    "hint": f"strike rate {bp['sr']:.0f} vs par {bp['par_sr']:.0f}"})
    if bw and bw["spells"] >= 5:
        out.append({"key": "control", "label": "Bowling control", "score": _scale(bw["eco_ratio"], 0.80, 1.25),
                    "hint": f"economy {bw['eco']:.2f} vs par {bw['par_eco']:.1f}"})
        out.append({"key": "wickets", "label": "Wicket-taking", "score": _scale(bw["wk_ratio"], 0.50, 1.50),
                    "hint": f"{bw['wickets']} wickets in {bw['overs']:g} overs"})
    if form:
        out.append({"key": "consistency", "label": "Consistency", "score": round(form["consistency"], 1),
                    "hint": form["reliability"].lower()})
        out.append({"key": "form", "label": "Current form", "score": _scale(form["ratio"], 0.60, 1.40),
                    "hint": f"recent impact {form['recent']:.0f} vs long-term {form['long_term']:.0f}"})
    if perfs:
        avg = _mean(V.impact(p) for p in perfs)
        out.append({"key": "impact", "label": "Match impact", "score": _scale(avg, 10.0, 50.0),
                    "hint": f"average impact {avg:.0f}/100"})
    if split and split["strong_ratio"] is not None:
        out.append({"key": "bigmatch", "label": "Big-match temperament",
                    "score": _scale(split["strong_ratio"], 0.70, 1.30),
                    "hint": f"impact {split['strong']['impact']:.0f} vs strong sides"})
    return out


# --------------------------------------------------------------------------
# Strengths and weaknesses
# --------------------------------------------------------------------------

def strengths_weaknesses(bp, bw, ph, split, form, limit_s=4, limit_w=3):
    """Evidence-backed strengths and weaknesses. Each item states the numbers behind it."""
    c = []        # (z-score, text); positive = strength

    if bp and bp["innings"] >= 5:
        z = (bp["sr_ratio"] - 1.0) / 0.15
        c.append((z, f"Scores quickly: strike rate {bp['sr']:.0f} vs par {bp['par_sr']:.0f}" if z > 0 else
                  f"Slow scorer: strike rate {bp['sr']:.0f} vs par {bp['par_sr']:.0f}"))
    if bw and bw["spells"] >= 5:
        z = (bw["eco_ratio"] - 1.0) / 0.10
        c.append((z, f"Tight with the ball: economy {bw['eco']:.2f} vs par {bw['par_eco']:.1f}" if z > 0 else
                  f"Expensive: economy {bw['eco']:.2f} vs par {bw['par_eco']:.1f}"))
        z = (bw["wk_ratio"] - 1.0) / 0.30
        c.append((z, f"Regular wicket-taker: {bw['wk_ratio']:.1f}x the average strike rate" if z > 0 else
                  f"Wicket-light: {bw['wk_ratio']:.1f}x the average strike rate"))
    if form:
        z = (form["consistency"] - 50.0) / 15.0
        c.append((z, f"Reliable output (consistency {form['consistency']:.0f}/100)" if z > 0 else
                  f"Streaky: output swings match to match (consistency {form['consistency']:.0f}/100)"))
        z = (form["ratio"] - 1.0) / 0.25
        c.append((z, f"Currently above their usual level: recent impact {form['recent']:.0f} vs {form['long_term']:.0f} long-term" if z > 0 else
                  f"Currently below their usual level: recent impact {form['recent']:.0f} vs {form['long_term']:.0f} long-term"))
    if split and split["strong_ratio"] is not None:
        z = (split["strong_ratio"] - 1.0) / 0.15
        s = split["strong"]["impact"]
        c.append((z, f"Lifts against strong opposition: impact {s:.0f} vs {split['overall']:.0f} overall" if z > 0 else
                  f"Fades against strong opposition: impact {s:.0f} vs {split['overall']:.0f} overall"))
    if split and split["inflated"]:
        c.append((-1.5, f"Record flattered by weaker opposition: impact {split['weak']['impact']:.0f} "
                        f"vs weak sides, {split['strong']['impact']:.0f} vs strong"))
    if ph:
        # Phase notes are relative to the player's OWN norm: they exist to show where the
        # player differs from their own average, not to repeat the overall strike rate or economy.
        own_sr = bp["sr_ratio"] if bp else None
        for phase, row in ph["bat"].items():
            if own_sr and row["balls"] >= 80 and abs(row["ratio"] - own_sr) >= 0.12:
                z = (row["ratio"] - own_sr) / 0.15
                c.append((z, f"Best in the {PHASE_LABEL[phase].lower()}: strike rate {row['sr']:.0f}, "
                             f"above their overall {bp['sr']:.0f}" if z > 0 else
                          f"Slower in the {PHASE_LABEL[phase].lower()}: strike rate {row['sr']:.0f}, "
                          f"below their overall {bp['sr']:.0f}"))
        own_eco = bw["eco_ratio"] if bw else None
        for phase, row in ph["bowl"].items():
            if own_eco and row["overs"] >= 10 and abs(row["ratio"] - own_eco) >= 0.10:
                z = (row["ratio"] - own_eco) / 0.12
                c.append((z, f"Most effective in the {PHASE_LABEL[phase].lower()}: economy {row['eco']:.2f}, "
                             f"better than their overall {bw['eco']:.2f}" if z > 0 else
                          f"Leaks runs in the {PHASE_LABEL[phase].lower()}: economy {row['eco']:.2f}, "
                          f"worse than their overall {bw['eco']:.2f}"))

    strengths = [t for z, t in sorted((x for x in c if x[0] >= 0.6), key=lambda x: -x[0])][:limit_s]
    weaknesses = [t for z, t in sorted((x for x in c if x[0] <= -0.6), key=lambda x: x[0])][:limit_w]
    return strengths, weaknesses


# --------------------------------------------------------------------------
# Whole profile
# --------------------------------------------------------------------------

def build_profile(perfs):
    """Everything the player page needs, from one list of performances (newest first)."""
    perfs = list(perfs)
    if not perfs:
        return None
    bp, bw = batting_profile(perfs), bowling_profile(perfs)
    ph = phase_summary(perfs)
    split = opposition_split(perfs)
    form = form_vs_longterm(perfs)
    s, w = strengths_weaknesses(bp, bw, ph, split, form)
    return {
        "matches": len(perfs), "fmt": _fmt_of(perfs),
        "batting": bp, "bowling": bw, "phases": ph, "opposition": split,
        "trend": trend(perfs), "progression": progression(perfs), "form": form,
        "dna": dna(bp, bw, ph), "traits": traits(bp, bw, split, form, perfs),
        "strengths": s, "weaknesses": w,
        "impact": round(_mean(V.impact(p) for p in perfs[:30]), 1),
    }


# --------------------------------------------------------------------------
# Similar players
# --------------------------------------------------------------------------

# (label, weight). The order is the order of the vector built by feature_vector().
DIMENSIONS = [
    ("overall quality", 2.0), ("consistency", 1.0), ("potential", 1.0), ("current form", 0.5),
    ("batting involvement", 1.5), ("bowling involvement", 1.5),
    ("scoring rate", 1.2), ("bowling economy", 1.2), ("wicket-taking", 1.0),
    ("role: batter", 1.0), ("role: bowler", 1.0), ("role: all-rounder", 1.0), ("role: keeper", 1.0),
]
_ROLES = ("BAT", "BOWL", "AR", "WK")


def feature_vector(role, quality, consistency, potential, form, totals, fmt):
    """Normalised 0-1 features for one player in one format.

    totals: dict(bat_inns, runs, balls, spells, overs, conceded, wickets, matches) summed
    over the player's matches in the format. Unmeasured style dimensions are 0.5 (neutral)
    so they neither attract nor repel.
    """
    matches = max(1, totals.get("matches", 0))
    bat_share = _clamp(totals.get("bat_inns", 0) / matches)
    bowl_share = _clamp(totals.get("spells", 0) / matches)
    sr_n = eco_n = wk_n = 0.5
    if totals.get("balls", 0) >= 60:
        sr = totals["runs"] / totals["balls"] * 100.0
        sr_n = _clamp((sr / PAR[fmt]["bat_sr"]["all"] - 0.6) / 1.0)
    if totals.get("overs", 0) >= 10:
        eco = totals["conceded"] / totals["overs"]
        eco_n = _clamp((PAR[fmt]["bowl_eco"]["all"] / max(eco, 0.5) - 0.6) / 1.0)
        window, par_w = WICKET_PAR[fmt]
        wk_n = _clamp(totals["wickets"] / (totals["overs"] * 6.0 / window) / par_w / 2.0)
    vec = [_clamp(quality / 100.0), _clamp(consistency / 100.0), _clamp(potential / 100.0),
           _clamp((form + 75.0) / 150.0), bat_share, bowl_share, sr_n, eco_n, wk_n]
    vec += [1.0 if role == r else 0.0 for r in _ROLES]
    return vec


def similar_players(target_id, vectors, names, k=5):
    """Nearest players by weighted distance. vectors: {id: vec}; names: {id: name}."""
    base = vectors.get(target_id)
    if base is None:
        return []
    scored = []
    for pid, vec in vectors.items():
        if pid == target_id:
            continue
        diffs = [abs(a - b) for a, b in zip(base, vec)]
        dist = sum(w * d * d for (_, w), d in zip(DIMENSIONS, diffs)) ** 0.5
        total_w = sum(w for _, w in DIMENSIONS) ** 0.5
        sim = round(100.0 * (1.0 - _clamp(dist / total_w * 1.8)), 0)
        # Name the two closest 'meaningful' traits (skip role one-hots and neutral 0.5 pairs).
        order = sorted(range(9), key=lambda i: diffs[i] - (0.0 if base[i] != 0.5 else 1.0))
        shared = [DIMENSIONS[i][0] for i in order[:2]]
        scored.append((dist, {"id": pid, "name": names.get(pid, "?"), "similarity": int(sim), "shared": shared}))
    scored.sort(key=lambda x: x[0])
    return [row for _, row in scored[:k]]
