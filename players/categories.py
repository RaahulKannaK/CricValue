"""Tab / category definitions. Pure Python."""
TABS = [
    {"slug": "t20", "key": "T20", "title": "T20", "sub": "International T20", "active_days": 365},
    {"slug": "odi", "key": "ODI", "title": "ODI", "sub": "International ODI", "active_days": 365},
    {"slug": "test", "key": "TEST", "title": "Test", "sub": "International Test", "active_days": 540},
    {"slug": "league", "key": "LEAGUE", "title": "Leagues", "sub": "IPL, BBL, Hundred, T10 and other leagues", "active_days": 365},
    {"slug": "domestic-t20", "key": "DOM_T20", "title": "Domestic T20", "sub": "Domestic T20 competitions", "active_days": 365},
    {"slug": "domestic-odi", "key": "DOM_ODI", "title": "Domestic ODI", "sub": "Domestic List A / ODI competitions", "active_days": 365},
    {"slug": "domestic-test", "key": "DOM_TEST", "title": "Domestic First Class", "sub": "Ranji Trophy and other first-class competitions", "active_days": 540},
    {"slug": "domestic-india-legacy", "key": "DOM_IN", "title": "Domestic India (legacy)", "sub": "Older combined domestic records; new imports are format-specific", "active_days": 540},
]
TAB_BY_SLUG = {t["slug"]: t for t in TABS}
TAB_BY_KEY = {t["key"]: t for t in TABS}
CATEGORY_CHOICES = [(t["key"], t["title"]) for t in TABS]

INDIA_DOM = ("ranji", "vijay hazare", "syed mushtaq", "duleep", "irani cup",
             "irani trophy", "deodhar")


def category_of(level, fmt, competition):
    """Return the tab key for a match, or None if it belongs to no tab."""
    if level == "INTL":
        return {"T20": "T20", "ODI": "ODI", "TEST": "TEST"}.get(fmt)
    c = (competition or "").lower()
    if level == "DOM":
        return {"T20": "DOM_T20", "ODI": "DOM_ODI", "TEST": "DOM_TEST"}.get(fmt, "DOM_IN")
    if level == "LEAGUE":
        return "LEAGUE"
    return None


# Sub-selections inside a tab: (slug, title, lowercase words found in the competition name)
GROUPS = {
    "LEAGUE": [
        ("ipl", "IPL", ("indian premier league",)),
        ("bbl", "BBL", ("big bash",)),
        ("hundred", "The Hundred", ("hundred",)),
        ("t10", "T10", ("t10", "d10")),
        ("cpl", "CPL", ("caribbean premier league",)),
        ("sa20", "SA20", ("sa20", "sat20")),
        ("psl", "PSL", ("pakistan super league",)),
        ("ilt20", "ILT20", ("international league t20",)),
        ("mlc", "MLC", ("major league cricket",)),
        ("lpl", "LPL", ("lanka premier league",)),
        ("bpl", "BPL", ("bangladesh premier league",)),
        ("blast", "T20 Blast", ("t20 blast", "vitality blast")),
    ],
    "DOM_IN": [
        ("vijay-hazare", "Vijay Hazare", ("vijay hazare",)),
        ("smat", "Syed Mushtaq Ali", ("syed mushtaq",)),
        ("ranji", "Ranji Trophy", ("ranji",)),
        ("duleep", "Duleep Trophy", ("duleep",)),
        ("irani", "Irani Cup", ("irani",)),
        ("deodhar", "Deodhar Trophy", ("deodhar",)),
    ],
}
for _dom_key in ("DOM_T20", "DOM_ODI", "DOM_TEST"):
    GROUPS[_dom_key] = GROUPS["DOM_IN"]
_TITLES = {s: t for gs in GROUPS.values() for s, t, _ in gs}
_TITLES["other"] = "Others"


def group_of(category, competition):
    """Sub-selection slug for a match inside a tab ('' if the tab has none)."""
    c = (competition or "").lower()
    for slug, _title, words in GROUPS.get(category, []):
        if any(w in c for w in words):
            return slug
    return "other" if category in GROUPS else ""


def group_title(slug):
    return _TITLES.get(slug, slug.title() if slug else "")