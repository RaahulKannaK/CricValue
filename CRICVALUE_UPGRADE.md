# CricValue upgrade: Player Intelligence and Discovery

Adds the three recommendations on top of the existing `players` app.

## What is new

| Recommendation | Where | What it does |
|---|---|---|
| 1. Valuation engine | `discovery.value_signal`, tab list, player page | **Undervalued / Fairly valued / Overvalued** flag with reasons. "Worth" (performance, form, consistency, potential; no market effects) is compared with the modelled market price. Already in your code and unchanged: price range with confidence width, opposition and competition adjustment, role demand, format-specific tabs, market profiles. |
| 2. Player intelligence | `intelligence.py`, player page | Player DNA label, trait bars, evidence-backed strengths and weaknesses, form vs long-term, trend (significance-tested), career progression by year, strong vs weak opposition split, **batting and bowling phase analysis**, similar players. |
| 3. Hidden gems and future stars | `discovery.py`, `/discover/` page | Breakout score and 12-month projected value; tags for young high-potential, early career, undervalued (incl. domestic), emerging nations, rapid risers, strong-opposition performers, low-cost high-impact. |

New files: `intelligence.py`, `discovery.py`, `intel_data.py`, `templates/players/discover.html`,
`migrations/0011_performance_phases.py`, `tests/`.
Changed: `cricsheet.py`, `models.py`, `views.py`, `urls.py`, `import_cricsheet.py`, `detail.html`,
`list.html`, `base.html`, `site.css`.

## Deploy

1. Copy the `players/` folder over your project's `players/`.
2. `python manage.py migrate` (adds `Performance.phases`, one JSON column).
3. Phase analysis needs over-by-over data, which was not stored before. For matches already
   imported, run `python manage.py import_cricsheet <folder-of-json> --backfill-phases`.
   New imports capture it automatically. Without it everything else still works and the phase
   panel says so.
4. Optional: set `date_of_birth` on players (admin) to enable the "Young high-potential" tag.
5. Tests (no database needed): `python -m unittest players.tests.test_intelligence players.tests.test_parser`

## Honest limits

* The analysis logic is unit-tested (33 tests, synthetic data). **The Django layer (views,
  templates, migration, importer) was not run**, because Django could not be installed in the
  build environment. It was syntax-checked and statically analysed only. Run it once against
  your real database before trusting it.
* Thresholds are starting points, not fitted to your data: `PAR` and phase boundaries in
  `intelligence.py`, `CFG` in `discovery.py`. Look at the flag rates on your real pools
  (on the synthetic pool about 5% of players were flagged undervalued) and tune.
* Age is never inferred. No date of birth means "early career" instead of "young".
* Future values are projections that assume the current trajectory continues, with a wider
  range when evidence is thin.
* The value signal obeys the engine's own rule that stats alone cannot prove franchise demand:
  without a scouting rating, "worth" is held at the same neutral cap as the price.
* Franchise demand is still a role-and-domestic proxy. Real team-needs modelling would need
  squad composition and purse data per franchise.
* Pool-wide results are cached for 15 minutes; call `intel_data.clear_cache()` after a recalc
  if you want them instantly.
* No spin vs pace data exists in the source, so DNA cannot distinguish bowling type.
