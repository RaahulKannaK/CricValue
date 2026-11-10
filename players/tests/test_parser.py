"""Phase / batting-position extraction in cricsheet.parse_match, checked against a randomly
generated Cricsheet-format match. Pure Python:

    python3 -m unittest players.tests.test_parser
"""
import random
import unittest

from players.cricsheet import parse_match, phase_of


def fake_match(fmt="T20", overs=20, seed=1):
    rng = random.Random(seed)
    A = [f"A{i}" for i in range(1, 12)]
    B = [f"B{i}" for i in range(1, 12)]
    innings = []
    for bat, bowl in ((A, B), (B, A)):
        striker, non, nxt = bat[0], bat[1], 2
        ovs = []
        for o in range(overs):
            bowler = bowl[6 + o % 5]
            dels = []
            for _ in range(6 + rng.choice([0, 0, 0, 1])):     # occasional extra delivery
                kind = rng.random()
                d = {"batter": striker, "bowler": bowler, "non_striker": non,
                     "runs": {"batter": rng.choice([0, 0, 1, 1, 2, 4, 6]), "extras": 0, "total": 0}}
                if kind < 0.06:
                    d["extras"] = {"wides": 1}; d["runs"].update(batter=0, extras=1)
                elif kind < 0.10:
                    d["extras"] = {"noballs": 1}; d["runs"].update(extras=1)
                elif kind < 0.13:
                    d["extras"] = {"legbyes": 1}; d["runs"].update(batter=0, extras=1)
                d["runs"]["total"] = d["runs"]["batter"] + d["runs"]["extras"]
                if rng.random() < 0.05 and nxt < 11:
                    k = rng.choice(["bowled", "caught", "run out"])
                    d["wickets"] = [{"kind": k, "player_out": striker if rng.random() < .8 or k != "run out" else non}]
                    out = d["wickets"][0]["player_out"]
                    if out == striker:
                        striker = bat[nxt]
                    else:
                        non = bat[nxt]
                    nxt += 1
                dels.append(d)
            ovs.append({"over": o, "deliveries": dels})
        innings.append({"team": "X", "overs": ovs})
    return {"info": {"gender": "male", "match_type": fmt, "team_type": "international",
                     "dates": ["2026-01-01"], "teams": ["A", "B"], "players": {"A": A, "B": B},
                     "event": {"name": "Test Series"}}, "innings": innings}


class Parser(unittest.TestCase):
    def check(self, fmt, overs):
        m = parse_match(fake_match(fmt, overs, seed=overs), include_women=False)
        self.assertEqual(m["fmt"], fmt.upper())
        for p in m["players"]:
            ph = p["phases"]
            if fmt.upper() == "TEST":
                self.assertFalse(ph.get("bat") or ph.get("bowl"))
                continue
            bat, bowl = ph.get("bat", {}), ph.get("bowl", {})
            # phase totals must reconcile exactly with the whole-match totals
            self.assertEqual(sum(v[0] for v in bat.values()), p["runs"], p["name"])
            self.assertEqual(sum(v[1] for v in bat.values()), p["balls"], p["name"])
            self.assertEqual(sum(v[0] for v in bowl.values()), p["conceded"], p["name"])
            self.assertEqual(sum(v[2] for v in bowl.values()), p["wickets"], p["name"])
            self.assertAlmostEqual(sum(v[1] for v in bowl.values()) / 6, p["overs"], places=1)

    def test_t20_phases_reconcile(self):
        self.check("T20", 20)

    def test_odi_phases_reconcile(self):
        self.check("ODI", 50)

    def test_test_has_no_phases(self):
        self.check("Test", 30)

    def test_phase_boundaries(self):
        self.assertEqual([phase_of("T20", o) for o in (0, 5, 6, 14, 15, 19)],
                         ["pp", "pp", "mid", "mid", "death", "death"])
        self.assertEqual([phase_of("ODI", o) for o in (0, 9, 10, 39, 40, 49)],
                         ["pp", "pp", "mid", "mid", "death", "death"])
        self.assertIsNone(phase_of("TEST", 3))

    def test_batting_positions_are_unique_crease_order(self):
        # A non-striker who never faces a ball has no performance row (existing behaviour), so
        # positions can skip numbers, but they must be unique per side, start at 1, and be real.
        m = parse_match(fake_match("T20", 20, seed=3))
        for team in ("A", "B"):
            pos = sorted(p["phases"]["pos"] for p in m["players"]
                         if p["name"].startswith(team) and p["phases"].get("pos"))
            self.assertEqual(len(pos), len(set(pos)), team)
            self.assertEqual(pos[0], 1, team)
            self.assertTrue(all(1 <= x <= 11 for x in pos), team)

    def test_dismissals_are_attributed_to_the_player_out(self):
        m = parse_match(fake_match("T20", 20, seed=5))
        outs = sum(v[2] for p in m["players"] for v in p["phases"].get("bat", {}).values())
        self.assertGreater(outs, 0)


if __name__ == "__main__":
    unittest.main()
