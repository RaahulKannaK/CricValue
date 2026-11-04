
"""Competition and national cricket strength classification.

Two independent dimensions:
1. Competition strength: quality/importance of the tournament.
2. National strength: relative strength of the participating country.

The opponent XI engine calculates actual opposition challenge separately.

All competition weights are model starting values, not official ICC ratings.
"""

import re
import unicodedata


# ---------------------------------------------------------
# 1. INTERNATIONAL NATIONAL STRENGTH
# ---------------------------------------------------------

GROUP_A = {
    "india", "australia", "england",
    "south africa", "new zealand", "pakistan",
}

GROUP_B = {
    "sri lanka", "west indies",
    "bangladesh", "afghanistan",
}

GROUP_C = {
    "ireland", "zimbabwe", "netherlands",
    "scotland", "nepal", "united arab emirates",
    "uae", "united states of america", "usa",
    "canada", "oman", "namibia",
    "papua new guinea",
}

GROUP_SCALE = {
    "A": 1.00,
    "B": 0.82,
    "C": 0.58,
    "D": 0.35,
}


def normalize_name(name):
    """Normalize competition and country names for matching."""

    name = str(name or "").strip().lower()

    name = unicodedata.normalize("NFKD", name)
    name = "".join(
        char for char in name
        if not unicodedata.combining(char)
    )

    # Normalize apostrophes before removing punctuation.
    name = (
        name.replace("’", "")
        .replace("‘", "")
        .replace("'", "")
    )

    name = (
        name.replace("&", " and ")
        .replace("_", " ")
        .replace("–", "-")
        .replace("—", "-")
    )

    name = re.sub(r"[^a-z0-9]+", " ", name)

    return " ".join(name.split())


def nation_group(name):
    country = normalize_name(name)

    if country in GROUP_A:
        return "A"

    if country in GROUP_B:
        return "B"

    if country in GROUP_C:
        return "C"

    return "D"


def nation_scale(name):
    return GROUP_SCALE[nation_group(name)]


def team_weight(name):
    """Backward-compatible national strength helper."""
    return nation_scale(name)


# ---------------------------------------------------------
# 2. INTERNATIONAL COMPETITION STRENGTH
# ---------------------------------------------------------

INTERNATIONAL_COMPETITION_STRENGTH = {

    # ODI WORLD CUP
    "icc cricket world cup": 1.00,
    "icc mens cricket world cup": 1.00,
    "icc world cup": 1.00,
    "world cup": 1.00,

    # ODI MAJOR TOURNAMENTS
    "icc champions trophy": 0.98,
    "asia cup": 0.95,

    # ODI WORLD CUP QUALIFICATION
    "icc cricket world cup qualifier": 0.90,
    "icc cricket world cup qualifier icc trophy": 0.90,
    "icc world cup qualifier": 0.90,
    "icc cricket world cup super league": 0.88,
    "icc mens cricket world cup super league": 0.88,
    "icc mens cricket world cup league 2": 0.78,
    "icc cricket world cup league 2": 0.78,
    "icc world cricket league championship": 0.78,

    # WCL DIVISIONS
    "icc world cricket league division one": 0.75,
    "icc world cricket league division two": 0.75,
    "icc world cricket league division three": 0.75,
    "icc world cricket league division four": 0.68,
    "icc world cricket league division five": 0.68,
    "icc world cricket league division six": 0.68,
    "icc world cricket league division seven": 0.68,
    "icc world cricket league division eight": 0.68,

    # T20 WORLD CUP
    "icc mens t20 world cup": 1.00,
    "icc mens world twenty20": 1.00,
    "icc world twenty20": 1.00,
    "icc t20 world cup": 1.00,
    "icc world t20": 1.00,
    "world twenty20": 1.00,

    # T20 CONTINENTAL EVENTS
    "asian games": 0.95,
    "asian cricket council premier cup": 0.88,
    "asian cricket council elite league": 0.85,
    "africa continental cup": 0.82,

    # TEST CRICKET
    "icc world test championship": 1.00,
    "world test championship": 1.00,
    "the ashes": 0.98,
    "ashes": 0.98,
    "border gavaskar trophy": 0.98,
    "frank worrell trophy": 0.96,

    # ASSOCIATE TEST CRICKET
    "icc intercontinental cup": 0.78,
    "icc intercontinental shield": 0.72,
}


# ---------------------------------------------------------
# 3. FRANCHISE AND DOMESTIC LEAGUE STRENGTH
# ---------------------------------------------------------

LEAGUE_STRENGTH = {

    # Major franchise leagues
    "indian premier league": 1.00,
    "ipl": 1.00,

    "big bash league": 0.94,
    "bbl": 0.94,

    "sa20": 0.93,

    "pakistan super league": 0.91,
    "psl": 0.91,

    "the hundred mens competition": 0.90,
    "the hundred": 0.90,

    "vitality blast": 0.88,
    "vitality blast men": 0.88,
    "natwest t20 blast": 0.88,

    "caribbean premier league": 0.87,
    "cpl": 0.87,

    "international league t20": 0.87,
    "ilt20": 0.87,

    "major league cricket": 0.84,
    "mlc": 0.84,

    "bangladesh premier league": 0.83,
    "bpl": 0.83,

    "lanka premier league": 0.78,
    "lpl": 0.78,

    "super smash": 0.78,
    "mzansi super league": 0.78,
    "ram slam t20 challenge": 0.78,
    "hrv cup": 0.78,
    "hrv twenty20": 0.78,

    "nepal premier league": 0.72,

    # Domestic competitions stored under LEAGUE
    "bob willis trophy": 0.82,
    "major league tournament": 0.75,

    # South African domestic competitions
    "csa t20 challenge": 0.75,
    "csa pro20": 0.75,
    "miway t20 challenge": 0.75,

    # Irish domestic competitions
    "cricket ireland inter provincial twenty20 trophy": 0.68,
    "cricket ireland inter provincial limited over cup": 0.68,

    # Other club competitions
    "major clubs limited over tournament": 0.65,
    "major clubs t20 tournament": 0.65,

    "t10": 0.60,

    "other": 0.55,
}


# ---------------------------------------------------------
# 4. DOMESTIC COMPETITION STRENGTH
# ---------------------------------------------------------

DOMESTIC_STRENGTH = {

    # First-class cricket
    "county championship": 0.82,
    "specsavers county championship": 0.82,
    "lv county championship": 0.82,
    "bob willis trophy": 0.82,

    "sheffield shield": 0.84,
    "marsh sheffield shield": 0.84,

    "plunket shield": 0.77,

    "major league tournament": 0.75,

    # One-day domestic cricket
    "one day cup": 0.73,
    "royal london one day cup": 0.73,
    "one day cup australia": 0.76,
    "the marsh cup": 0.76,

    # Indian domestic T20
    "syed mushtaq ali trophy": 0.75,
}


DOMESTIC_DEFAULT = 0.65
LEAGUE_DEFAULT = 0.55


# ---------------------------------------------------------
# 5. INTERNATIONAL COMPETITION PATTERN MATCHING
# ---------------------------------------------------------

def _contains(name, *patterns):
    return any(pattern in name for pattern in patterns)


def _is_regional_qualifier(name):
    """Identify regional T20 World Cup qualifiers."""

    if "qualifier" not in name:
        return False

    regional_terms = (
        "africa",
        "americas",
        "asia",
        "europe",
        "east asia",
        "east asia pacific",
        "eap",
        "regional",
        "region",
        "sub regional",
    )

    return _contains(name, *regional_terms)


def _is_regional_final(name):
    """Identify regional T20 World Cup finals."""

    if "final" not in name:
        return False

    regional_terms = (
        "africa",
        "americas",
        "asia",
        "europe",
        "east asia",
        "east asia pacific",
        "eap",
        "regional",
        "region",
    )

    return _contains(name, *regional_terms)


def international_competition_strength(competition, fmt=None):
    """
    Determine international competition strength.

    Specific competition patterns are checked before broad patterns.
    This prevents regional qualifiers from receiving World Cup finals
    strength accidentally.
    """

    name = normalize_name(competition)
    fmt = str(fmt or "").strip().upper()

    # Exact competition mapping.
    if name in INTERNATIONAL_COMPETITION_STRENGTH:
        return INTERNATIONAL_COMPETITION_STRENGTH[name]

    # ---------------- ODI ----------------

    if fmt == "ODI":

        # Challenge League before general League 2 / WCL rules.
        if "challenge league" in name:
            return 0.65

        # World Cricket League divisions.
        if "world cricket league" in name:

            if _contains(
                name,
                "division one",
                "division two",
                "division three",
            ):
                return 0.75

            if _contains(
                name,
                "division four",
                "division five",
                "division six",
                "division seven",
                "division eight",
            ):
                return 0.68

            if _contains(name, "league 2"):
                return 0.78

            if _contains(name, "championship"):
                return 0.78

            return 0.72

        # Regional qualification competitions.
        if _contains(
            name,
            "regional qualifier",
            "regional qualifiers",
            "region qualifier",
            "region qualifiers",
        ):
            return 0.72

        if "world cup qualifier play off" in name:
            return 0.86

        if "world cup qualifier" in name:
            return 0.90

        if "super league" in name and "world cup" in name:
            return 0.88

        if "champions trophy" in name:
            return 0.98

        if "asia cup" in name:
            return 0.95

        if "world cup" in name:
            return 1.00

        if _contains(name, "tri series", "tri nation", "triangular"):
            return 0.88

        if _contains(name, "tour of", " in ", " v ", " vs "):
            return 0.90

        if "series" in name:
            return 0.90

        return 0.85

    # ---------------- T20 ----------------

    if fmt == "T20":

        # 1. Sub-regional qualifiers.
        # Must be checked before generic World Cup patterns.
        if _contains(name, "sub regional", "subregional"):
            return 0.72

        # 2. Regional qualifiers.
        # Includes Africa, Americas, Asia, Europe and EAP qualifiers.
        if _is_regional_qualifier(name):
            return 0.80

        # 3. Regional finals.
        if _is_regional_final(name):
            return 0.84

        # 4. Global T20 World Cup qualifiers.
        # Example: ICC Men's T20 World Cup Qualifier A.
        if "world cup qualifier" in name:
            return 0.88

        if "world twenty20 qualifier" in name:
            return 0.88

        # 5. Actual World Cup tournaments.
        if _contains(
            name,
            "world cup",
            "world twenty20",
            "world t20",
        ):
            return 1.00

        # 6. Continental competitions.
        if _contains(name, "asia cup", "asian games"):
            return 0.95

        if _contains(
            name,
            "continental cup",
            "africa continental",
        ):
            return 0.82

        # 7. Other international tournaments.
        if _contains(name, "tri series", "tri nation", "triangular"):
            return 0.90

        if _contains(name, "tour of", " in ", " v ", " vs "):
            return 0.90

        if "series" in name:
            return 0.90

        return 0.85

    # ---------------- TEST ----------------

    if fmt == "TEST":

        if _contains(name, "world test championship"):
            return 1.00

        if _contains(name, "ashes", "border gavaskar"):
            return 0.98

        if _contains(name, "intercontinental shield"):
            return 0.72

        if _contains(name, "intercontinental cup"):
            return 0.78

        if _contains(name, "tour of", " in ", " v ", " vs "):
            return 0.95

        if "series" in name:
            return 0.95

        return 0.90

    return 0.85


# ---------------------------------------------------------
# 6. MAIN COMPETITION STRENGTH FUNCTION
# ---------------------------------------------------------

def competition_strength(category, competition, fmt=None):
    """
    Return competition strength independently of national strength.
    """

    name = normalize_name(competition)
    category = str(category or "").strip().upper()

    # International formats
    if category in ("T20", "ODI", "TEST"):
        return international_competition_strength(
            name,
            fmt or category,
        )

    # Franchise and other league competitions
    if category == "LEAGUE":

        if name in LEAGUE_STRENGTH:
            return LEAGUE_STRENGTH[name]

        # Competition-specific fallback rules.
        if "premier league" in name:
            return 0.72

        if "blast" in name:
            return 0.85

        if "t20 challenge" in name:
            return 0.75

        if "county championship" in name:
            return 0.82

        if "sheffield shield" in name:
            return 0.84

        if "plunket shield" in name:
            return 0.77

        if "one day cup" in name:
            return 0.73

        return LEAGUE_DEFAULT

    # Domestic formats
    if category in (
        "DOM",
        "DOM_IN",
        "DOM_T20",
        "DOM_ODI",
        "DOM_TEST",
    ):

        if name in DOMESTIC_STRENGTH:
            return DOMESTIC_STRENGTH[name]

        if "county championship" in name:
            return 0.82

        if "bob willis trophy" in name:
            return 0.82

        if "sheffield shield" in name:
            return 0.84

        if "plunket shield" in name:
            return 0.77

        if "one day cup" in name:
            return 0.73

        return DOMESTIC_DEFAULT

    return 1.0


# ---------------------------------------------------------
# 7. BACKWARD-COMPATIBLE IMPORT FUNCTION
# ---------------------------------------------------------

def strength_of(category, competition, teams=()):
    """
    Compatibility function used by existing import code.

    Match.strength stores competition strength for all categories.

    National strength is calculated separately using nation_scale()
    and the opponent XI engine.
    """

    category = str(category or "").strip().upper()

    return round(
        competition_strength(category, competition),
        3,
    )
