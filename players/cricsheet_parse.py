"""Turns one Cricsheet JSON match into per-player stats. No Django imports."""
from collections import defaultdict

FMT = {"T20": "T20", "IT20": "T20", "ODI": "ODI", "ODM": "ODI", "Test": "TEST", "MDM": "TEST"}
DOMESTIC_WORDS = ("ranji", "vijay hazare", "syed mushtaq", "duleep", "irani", "sheffield",
                  "marsh one-day", "plunket", "ford trophy", "quaid", "county championship",
                  "csa 4-day", "momentum one day")
NOT_BOWLER_WICKET = {"run out", "retired hurt", "retired out", "obstructing the field"}


def level_of(info):
    if info.get("team_type") == "international":
        return "INTL"
    event = (info.get("event") or {}).get("name", "").lower()
    return "DOM" if any(w in event for w in DOMESTIC_WORDS) else "LEAGUE"


def parse(data):
    st = defaultdict(lambda: dict(runs=0, balls=0, wkts=0, conc=0, legal=0))
    for inn in data.get("innings", []):
        if inn.get("super_over"):
            continue
        for ov in inn.get("overs", []):
            for d in ov["deliveries"]:
                ex = d.get("extras", {})
                bat, bowl = st[d["batter"]], st[d["bowler"]]
                bat["runs"] += d["runs"]["batter"]
                if "wides" not in ex:
                    bat["balls"] += 1
                bowl["conc"] += d["runs"]["batter"] + ex.get("wides", 0) + ex.get("noballs", 0)
                if "wides" not in ex and "noballs" not in ex:
                    bowl["legal"] += 1
                for w in d.get("wickets", []):
                    if w["kind"] not in NOT_BOWLER_WICKET:
                        bowl["wkts"] += 1
    return st
