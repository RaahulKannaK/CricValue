from players.categories import category_of
from players.cricsheet import level_of


def test_known_domestic_competitions_are_domestic():
    for name in ("Ranji Trophy", "Sheffield Shield", "County Championship",
                 "Plunket Shield", "Quaid-e-Azam Trophy", "CSA 4-Day Series"):
        assert level_of({"team_type": "club", "event": {"name": name}}) == "DOM"


def test_known_franchise_competitions_remain_leagues():
    for name in ("Indian Premier League", "Big Bash League", "Caribbean Premier League"):
        assert level_of({"team_type": "club", "event": {"name": name}}) == "LEAGUE"


def test_domestic_categories_are_format_specific():
    assert category_of("DOM", "T20", "Syed Mushtaq Ali Trophy") == "DOM_T20"
    assert category_of("DOM", "ODI", "Vijay Hazare Trophy") == "DOM_ODI"
    assert category_of("DOM", "TEST", "Ranji Trophy") == "DOM_TEST"
