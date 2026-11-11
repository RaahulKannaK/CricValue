"""Turns one Cricsheet match JSON into per-player stats. No Django imports."""
FMT = {"T20": "T20", "IT20": "T20", "ODI": "ODI", "ODM": "ODI", "Test": "TEST", "MDM": "TEST"}
# Known non-franchise domestic competitions. Cricsheet does not provide a
# universal domestic-vs-franchise flag, so keep this list explicit and
# conservative: unknown non-international events remain LEAGUE until reviewed.
DOM_WORDS = (
    "ranji", "vijay hazare", "syed mushtaq", "duleep", "irani cup",
    "deodhar", "maharaja trophy", "sheffield shield", "marsh cup",
    "marsh one-day", "one-day cup", "county championship",
    "bob willis trophy", "plunket shield", "ford trophy", "super smash",
    "quaid-e-azam", "quaid e azam", "pakistan cup", "national t20 cup",
    "president's trophy", "presidents trophy", "national cricket league",
    "bangladesh cricket league", "dhaka premier league",
    "csa 4-day", "csa 4 day", "provincial one-day",
    "provincial one day", "sunfoil", "regional 4-day",
    "regional 4 day", "super50", "major club",
    "premier league tournament", "major clubs", "slc major",
)
NO_CREDIT = {"run out", "retired hurt", "retired out", "obstructing the field"}

# Phase boundaries by format, as (end-of-powerplay over, end-of-middle over), 0-based
# Cricsheet over numbers. Tests have no phases.
PHASE_OVERS = {"T20": (6, 15), "ODI": (10, 40)}


def phase_of(fmt, over):
    bounds = PHASE_OVERS.get(fmt)
    if not bounds:
        return None
    return "pp" if over < bounds[0] else "mid" if over < bounds[1] else "death"


def level_of(info):
    if info.get("team_type") == "international":
        return "INTL"
    ev = ((info.get("event") or {}).get("name") or "").lower()
    return "DOM" if any(w in ev for w in DOM_WORDS) else "LEAGUE"


def parse_match(data, include_women=False):
    info = data["info"]
    if info.get("gender", "male") != "male" and not include_women:
        return None
    level = level_of(info)
    reg = (info.get("registry") or {}).get("people", {})
    team_of = {n: t for t, names in (info.get("players") or {}).items() for n in names}
    fmt = FMT.get(info.get("match_type"), "T20")
    st = {}

    def row(n):
        return st.setdefault(n, dict(runs=0, balls=0, bat=False, bowled=False,
                                     wickets=0, conceded=0, legal=0,
                                     bat_ph={}, bowl_ph={}, pos=None))

    def bump(table, phase, i, amount):
        if phase:
            table.setdefault(phase, [0, 0, 0])[i] += amount

    for inn in data.get("innings", []):
        if inn.get("super_over"):
            continue
        order = []          # batting order within this innings: first appearance at the crease
        for ov in inn.get("overs", []):
            phase = phase_of(fmt, ov.get("over", 0))
            for d in ov.get("deliveries", []):
                ex = d.get("extras") or {}
                for who in (d["batter"], d.get("non_striker")):
                    if who and who not in order:
                        order.append(who)
                b = row(d["batter"])
                b["bat"] = True
                b["runs"] += d["runs"]["batter"]
                bump(b["bat_ph"], phase, 0, d["runs"]["batter"])
                if "wides" not in ex:
                    b["balls"] += 1
                    bump(b["bat_ph"], phase, 1, 1)
                w = row(d["bowler"])
                w["bowled"] = True
                conceded = d["runs"]["total"] - ex.get("byes", 0) - ex.get("legbyes", 0)
                w["conceded"] += conceded
                bump(w["bowl_ph"], phase, 0, conceded)
                if "wides" not in ex and "noballs" not in ex:
                    w["legal"] += 1
                    bump(w["bowl_ph"], phase, 1, 1)
                for wk in d.get("wickets") or []:
                    if wk.get("kind") not in NO_CREDIT:
                        w["wickets"] += 1
                        bump(w["bowl_ph"], phase, 2, 1)
                    out = wk.get("player_out")
                    if out and wk.get("kind") != "retired hurt":
                        bump(row(out)["bat_ph"], phase, 2, 1)
        for pos, who in enumerate(order, start=1):
            r = row(who)
            if r["pos"] is None:         # first innings batted: Tests have two, we keep the first
                r["pos"] = pos
    lineups = {
        team: [{"name": name, "cid": reg.get(name, "")}
               for name in names]
        for team, names in (info.get("players") or {}).items()
    }
    players = []
    for name, r in st.items():
        if not (r["bat"] or r["bowled"]):
            continue
        team = team_of.get(name, "")
        players.append(dict(
            name=name, cid=reg.get(name, ""), team=team,
            country=team if level == "INTL" else "",
            runs=r["runs"], balls=r["balls"], wickets=r["wickets"],
            conceded=r["conceded"], overs=round(r["legal"] / 6, 2),
            phases={"bat": r["bat_ph"], "bowl": r["bowl_ph"], "pos": r["pos"]}
                   if (r["bat_ph"] or r["bowl_ph"] or r["pos"]) else {}))
    dates = info.get("dates") or [""]
    return dict(date=dates[0], teams=info.get("teams") or [], lineups=lineups,
                level=level, fmt=fmt,
                competition=(info.get("event") or {}).get("name") or info.get("match_type", "Match"),
                players=players)
