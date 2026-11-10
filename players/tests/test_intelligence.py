"""Tests for intelligence.py and discovery.py. No database or Django needed:

    python3 -m unittest players.tests.test_intelligence      (from the folder containing players/)

A synthetic league of generic players fills the pool; named, planted archetypes are
then checked against what the engine reports.
"""
import datetime as dt
import random
import unittest
from types import SimpleNamespace as NS

from players import discovery as D
from players import intelligence as I
from players import valuation as V

TODAY = dt.date(2026, 11, 4)
rng = random.Random(7)


def perf(days_ago, fmt="T20", cat="T20", runs=0, balls=0, wk=0, conc=0, overs=0.0,
         opp=1.0, strength=1.0, phases=None):
    return NS(runs=runs, balls=balls, wickets=wk, runs_conceded=conc, overs=overs,
              opp_strength=opp, phases=phases or {},
              match=NS(date=TODAY - dt.timedelta(days=days_ago), fmt=fmt, category=cat, strength=strength))


def bat_phases(pos, pp=(0, 0, 0), mid=(0, 0, 0), death=(0, 0, 0)):
    return {"bat": {"pp": list(pp), "mid": list(mid), "death": list(death)}, "bowl": {}, "pos": pos}


def bowl_phases(pp=(0, 0, 0), mid=(0, 0, 0), death=(0, 0, 0), pos=9):
    return {"bat": {}, "bowl": {"pp": list(pp), "mid": list(mid), "death": list(death)}, "pos": pos}


def batter(n=40, pos=1, sr=150, avg=32, opp=1.0, step=7, form_boost=0.0, cat="T20", phased=True,
           opp_fn=None):
    """n matches, newest first. form_boost lifts the newest 10 matches by that fraction."""
    out = []
    for i in range(n):
        boost = 1.0 + (form_boost if i < 10 else 0.0)
        runs = max(0, int(rng.gauss(avg, avg * 0.55) * boost))
        balls = max(1, int(runs / (sr / 100.0))) if runs else rng.randint(1, 6)
        ph = None
        if phased:
            share = {1: (0.55, 0.40, 0.05), 3: (0.15, 0.70, 0.15), 6: (0.0, 0.40, 0.60)}.get(pos, (0.1, 0.6, 0.3))
            ph = bat_phases(pos, *[(int(runs * s), int(balls * s), 1) for s in share])
        o = opp_fn(i) if opp_fn else opp
        out.append(perf(i * step + 1, cat=cat, runs=runs, balls=balls, opp=o, phases=ph))
    return out


def bowler(n=40, eco=7.4, wk=1.2, shares=(0.2, 0.6, 0.2), opp=1.0, step=7, with_bat=True, phased=True):
    out = []
    for i in range(n):
        overs = 4.0
        conc = max(0, int(rng.gauss(eco * overs, 6)))
        w = max(0, int(rng.gauss(wk, 1.0)))
        ph = None
        if phased:
            ph = bowl_phases(*[(int(conc * s), int(24 * s), int(w * s)) for s in shares])
        p = perf(i * step + 1, wk=w, conc=conc, overs=overs, opp=opp, phases=ph)
        if with_bat:
            p.runs, p.balls = rng.randint(0, 6), rng.randint(1, 5)
            if phased:
                p.phases["pos"] = 10
        out.append(p)
    return out


class Profile(unittest.TestCase):
    def test_explosive_opener(self):
        pr = I.build_profile(batter(pos=1, sr=165, avg=34))
        self.assertEqual(pr["dna"]["batting"], "Explosive Opener")
        self.assertIn("Aggression", [t["label"] for t in pr["traits"]])
        self.assertTrue(any("Scores quickly" in s for s in pr["strengths"]))

    def test_anchor_and_slow_scorer_weakness(self):
        pr = I.build_profile(batter(pos=3, sr=100, avg=34))
        self.assertEqual(pr["dna"]["batting"], "Anchor")
        self.assertTrue(any("Slow scorer" in w for w in pr["weaknesses"]))

    def test_finisher(self):
        pr = I.build_profile(batter(pos=6, sr=160, avg=22))
        self.assertEqual(pr["dna"]["batting"], "Finisher")

    def test_phase_split_sums_to_one_and_death_share_high_for_finisher(self):
        ph = I.build_profile(batter(pos=6, sr=160, avg=22))["phases"]
        self.assertAlmostEqual(sum(r["share"] for r in ph["bat"].values()), 1.0, delta=0.05)
        self.assertGreater(ph["bat"]["death"]["share"], 0.5)

    def test_death_bowler(self):
        pr = I.build_profile(bowler(eco=8.6, wk=1.2, shares=(0.05, 0.45, 0.5)))
        self.assertEqual(pr["dna"]["bowling"], "Death-Overs Specialist")

    def test_new_ball_specialist(self):
        pr = I.build_profile(bowler(eco=6.8, wk=1.3, shares=(0.7, 0.2, 0.1)))
        self.assertEqual(pr["dna"]["bowling"], "New-Ball Specialist")

    def test_bowler_who_bats_at_ten_gets_no_batting_label(self):
        pr = I.build_profile(bowler(eco=7.0, wk=1.4))
        self.assertNotIn("Batter", pr["dna"]["label"])
        self.assertNotIn("Finisher", pr["dna"]["label"])

    def test_phase_notes_only_when_phase_differs_from_own_norm(self):
        # Opener who scores at the same rate in every phase: no phase commentary at all
        flat = []
        for i in range(40):
            runs, balls = 30, 20
            flat.append(perf(i * 7 + 1, runs=runs, balls=balls,
                             phases=bat_phases(1, (10, 7, 1), (10, 7, 0), (10, 6, 0))))
        pr = I.build_profile(flat)
        self.assertFalse([x for x in pr["strengths"] + pr["weaknesses"] if "overs" in x])
        # Slow powerplay, fast death: both must be called out relative to the player's own average
        skew = []
        for i in range(40):
            skew.append(perf(i * 7 + 1, runs=30, balls=20,
                             phases=bat_phases(4, (4, 8, 1), (10, 8, 0), (16, 4, 0))))
        pr = I.build_profile(skew)
        text = " ".join(pr["strengths"] + pr["weaknesses"])
        self.assertIn("Best in the death overs", text)
        self.assertIn("Slower in the powerplay", text)

    def test_missing_phase_data_degrades_gracefully(self):
        pr = I.build_profile(batter(pos=1, sr=150, phased=False))
        self.assertIsNone(pr["phases"])
        self.assertIsNotNone(pr["dna"]["batting"])       # falls back to stats-only archetype

    def test_empty_history(self):
        self.assertIsNone(I.build_profile([]))


class Trends(unittest.TestCase):
    def test_improving_player_is_flagged(self):
        pr = I.build_profile(batter(avg=22, form_boost=1.2))
        self.assertEqual(pr["trend"]["label"], "Improving")
        self.assertIn(pr["form"]["label"], ("Peaking", "In form"))

    def test_pure_noise_is_rarely_called_a_trend(self):
        """Same underlying ability every match: 'Improving'/'Declining' must be the exception."""
        hits = sum(I.trend(batter(avg=28, sr=135))["label"] != "Stable" for _ in range(300))
        self.assertLess(hits / 300, 0.12)

    def test_too_little_history_gives_no_trend(self):
        self.assertIsNone(I.trend(batter(n=9)))

    def test_flat_track_bully_is_exposed(self):
        # strong opposition in even matches, weak in odd; impact only comes against weak sides
        def opp(i):
            return 1.2 if i % 2 == 0 else 0.75
        ps = batter(n=40, avg=30, opp_fn=opp)
        for p in ps:
            if p.opp_strength > 1.0:
                p.runs, p.balls = p.runs // 4, max(1, p.balls // 3)
        sp = I.opposition_split(ps)
        self.assertTrue(sp["inflated"])
        pr = I.build_profile(ps)
        self.assertTrue(any("flattered by weaker opposition" in w for w in pr["weaknesses"]))

    def test_progression_by_year(self):
        pg = I.progression(batter(n=40, step=30))
        self.assertGreaterEqual(len(pg["years"]), 3)
        self.assertEqual([r["year"] for r in pg["years"]], sorted(r["year"] for r in pg["years"]))


# ---- pool-level -----------------------------------------------------------

def make_cv(pid, name, country, role, perfs, dob=None, cat="T20", scouting=None, potential=None):
    q = V.quality_score(perfs, cat)
    eff = V.recent_form(perfs)
    n = len(perfs)
    return NS(player_id=pid, category=cat, group="", matches=n, quality_score=q,
              consistency_score=V.consistency_score(perfs),
              potential_score=potential if potential is not None else min(95, 30 + q * 0.7 + rng.uniform(-5, 5)),
              form_score=0.0, confidence_score=V.confidence_score(n), eff=eff,
              last_played=perfs[0].match.date,
              player=NS(name=name, country=country, role=role, date_of_birth=dob,
                        potential_rating=scouting, get_role_display=lambda: role))


def build_pool():
    cvs, perfs = [], {}
    countries = ["India", "Australia", "England", "South Africa", "Pakistan", "New Zealand",
                 "Sri Lanka", "Bangladesh", "West Indies", "Afghanistan"]
    pid = 1
    for i in range(55):                                   # generic mid-table league
        avg, sr = rng.uniform(14, 34), rng.uniform(105, 150)
        ps = batter(n=rng.randint(25, 45), pos=rng.choice([1, 2, 3, 4, 5, 6]), sr=sr, avg=avg, opp=rng.uniform(0.9, 1.2))
        perfs[pid] = ps
        cvs.append(make_cv(pid, f"Filler {i}", rng.choice(countries), "BAT", ps))
        pid += 1
    named = {}

    def add(name, country, role, ps, **kw):
        nonlocal pid
        perfs[pid] = ps
        cvs.append(make_cv(pid, name, country, role, ps, **kw))
        named[name] = pid
        pid += 1

    add("Star", "India", "BAT", batter(n=45, pos=1, sr=160, avg=44, opp=1.2))
    add("Rising Youngster", "India", "BAT", batter(n=22, pos=3, sr=150, avg=24, opp=1.1, form_boost=1.4),
        dob=dt.date(2005, 3, 1), potential=88)
    add("Associate Ace", "Netherlands", "BAT", batter(n=34, pos=3, sr=140, avg=36, opp=1.15))
    add("Journeyman", "Pakistan", "BAT", batter(n=45, pos=4, sr=108, avg=16, opp=0.95))
    # a veteran whose price is lifted by reputation + a scouting rating, but with weak numbers
    add("Reputation Name", "India", "BAT", batter(n=45, pos=4, sr=112, avg=15, opp=1.0), scouting=88)
    return cvs, perfs, named


class Discovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cvs, perfs, cls.named = build_pool()
        # form as the tab view computes it
        effs = [c.eff for c in cvs]
        for c in cvs:
            c.form_score = V.form_pct(c.eff, effs)
        cands = D.candidates_from(cvs, perfs, ref_date=TODAY)
        cls.res = {r["name"]: r for r in D.analyse_pool(cands, TODAY)}
        cls.all = list(cls.res.values())

    def test_every_candidate_has_a_priced_range_and_signal(self):
        for r in self.all:
            self.assertLessEqual(r["est"]["low"], r["est"]["high"])
            self.assertIn(r["signal"]["label"], ("Undervalued", "Fairly valued", "Overvalued"))
            self.assertGreaterEqual(r["breakout"]["score"], 0)
            self.assertLessEqual(r["breakout"]["score"], 100)

<<<<<<< HEAD
    def test_stats_only_star_can_receive_a_premium_from_performance(self):
        """No arbitrary ₹9Cr cap: elite evidence can support a premium without manual scouting."""
        r = self.res["Star"]
        self.assertIsNone(r["est"]["factors"]["scouting"])
        self.assertGreater(r["est"]["mid"], 6.0)
        self.assertGreaterEqual(r["est"]["high"] - r["est"]["low"], 1.5)
=======
    def test_stats_only_star_is_not_flagged_just_for_the_neutral_cap(self):
        """The engine holds stats-only players at a neutral cap; 'worth' must obey the same cap."""
        r = self.res["Star"]
        self.assertIsNone(r["est"]["factors"]["scouting"])
        # worth is capped at 9 then shrunk towards the market price: it can never exceed either
        self.assertLessEqual(r["signal"]["worth"], max(9.0, r["signal"]["market"]) + 1e-6)
        self.assertNotEqual(r["signal"]["label"], "Undervalued")
>>>>>>> 32c894519d1d3703c8124559016ca18af8eb90d6

    def test_most_players_are_fairly_valued(self):
        fair = sum(1 for r in self.all if r["signal"]["label"] == "Fairly valued")
        self.assertGreater(fair / len(self.all), 0.5, "flags should be the exception, not the rule")

    def test_rising_youngster_is_a_breakout_with_young_tag_and_projection(self):
        r = self.res["Rising Youngster"]
        self.assertIn("young", r["tags"])
        self.assertIn(r["breakout"]["label"], ("High", "Medium"))
        self.assertIsNotNone(r["projection"])
        self.assertGreater(r["projection"]["mid"], r["est"]["mid"])

    def test_age_is_only_ever_taken_from_dob(self):
        r = self.res["Rising Youngster"]
        self.assertEqual(r["age"], 21)
        for n, o in self.res.items():
            if n != "Rising Youngster":
                self.assertIsNone(o["age"])
                self.assertNotIn("young", o["tags"])

    def test_associate_ace_is_tagged_emerging_nation(self):
        self.assertIn("associate", self.res["Associate Ace"]["tags"])

    def test_reputation_premium_is_called_overvalued_with_reason(self):
        r = self.res["Reputation Name"]
        self.assertEqual(r["signal"]["label"], "Overvalued")
        self.assertTrue(any("scouting" in x or "reputation" in x for x in r["signal"]["reasons"]))

    def test_journeyman_is_not_a_hidden_gem(self):
        r = self.res["Journeyman"]
        self.assertNotIn("breakout", r["tags"])
        self.assertNotIn("low_cost", r["tags"])

    def test_projection_never_exceeds_cap(self):
        for r in self.all:
            if r["projection"]:
                self.assertLessEqual(r["projection"]["high"], 23.0 + 1.0)
                self.assertLessEqual(r["projection"]["growth_pct"], D.CFG["max_growth"] * 100)

    def test_thin_evidence_does_not_produce_gem_tags(self):
        ps = batter(n=6, pos=1, sr=190, avg=60)
        cv = make_cv(9999, "Six Match Wonder", "India", "BAT", ps, dob=dt.date(2006, 1, 1), potential=95)
        cv.form_score = 60
        cands = D.candidates_from([cv], {9999: ps}, ref_date=TODAY)
        r = D.analyse_pool(cands, TODAY)[0]
        self.assertEqual(r["tags"], [])

    def test_sections_are_well_formed(self):
        secs = D.sections(self.all)
        self.assertEqual(secs[0][0], "breakout")
        scores = [r["breakout"]["score"] for r in secs[0][3]]
        self.assertEqual(scores, sorted(scores, reverse=True))


class Similarity(unittest.TestCase):
    def test_similar_players_prefers_same_role_and_style(self):
        def tot(runs, balls, bat_inns, matches=30, spells=0, overs=0, conc=0, wk=0):
            return dict(runs=runs, balls=balls, bat_inns=bat_inns, matches=matches, spells=spells,
                        overs=overs, conceded=conc, wickets=wk)
        vecs = {
            1: I.feature_vector("BAT", 70, 55, 70, 10, tot(900, 600, 30), "T20"),   # target: aggressive batter
            2: I.feature_vector("BAT", 68, 52, 68, 5, tot(880, 590, 30), "T20"),    # near twin
            3: I.feature_vector("BOWL", 70, 55, 70, 10, tot(40, 40, 10, spells=30, overs=110, conc=800, wk=45), "T20"),
            4: I.feature_vector("BAT", 30, 30, 30, -20, tot(300, 300, 30), "T20"),
        }
        names = {1: "target", 2: "twin", 3: "bowler", 4: "weak"}
        out = I.similar_players(1, vecs, names, k=3)
        self.assertEqual(out[0]["name"], "twin")
        self.assertEqual(out[-1]["name"] in ("bowler", "weak"), True)
        self.assertTrue(all(0 <= r["similarity"] <= 100 for r in out))
        self.assertEqual(I.similar_players(99, vecs, names), [])


if __name__ == "__main__":
    unittest.main()
