CRICVALUE PLAYERS APP — UNIVERSAL + MARKET-SPECIFIC VALUATION
===========================================================

PACKAGE SCOPE
-------------
This ZIP contains the complete Django `players/` app directory, not the parent
Django project. It does not include manage.py, project settings, root URLs, or
requirements because those were not included in the supplied app archive.

WHAT IS NEW
-----------
1. Global format valuation remains separate from auction-market valuation.
2. AuctionMarketProfile stores a configurable competition, format, purse, squad
   size, team count, overseas limit, source category/group and market factor.
3. MarketValuation stores each player's global value, market adjustment, estimated
   auction value, confidence and a transparent adjustment breakdown.
4. Default profiles are seeded by migration: IPL ₹120 Cr; International T20, ODI
   and Test ₹100 Cr; Domestic T20, ODI and First Class ₹100 Cr.
5. Domestic match records are split into Domestic T20, Domestic ODI and Domestic
   First Class categories based on their saved match format. Legacy DOM_IN records
   are retained as a legacy tab.
6. Optional Player.date_of_birth and Player.potential_rating fields are available.
   DOB is never inferred. Potential rating is an optional 0-100 scouting override;
   when blank, the engine uses an evidence-based neutral estimate.
7. Removed the hard match-count price ceilings. Match count affects confidence and
   modest experience weighting, not an absolute price cap. This allows an emerging
   player to earn a higher estimate through quality/potential evidence.
8. Form remains a controlled modifier, with a maximum +10% uplift and -8% downside.
   Rest/inactivity fades towards neutral rather than treating absence as poor form.
9. The Auction Markets pages display Global Base Value beside Market Auction Value.
10. Django Admin lets you add/edit league and custom auction market profiles.

MARKET VALUE LOGIC
------------------
The global format value is the starting point. Market valuation then applies:
- Diminishing purse scaling (not a direct purse-ratio multiplication).
- Squad-size scaling.
- Configurable competition factor.
- A small league/domestic suitability factor when relevant records exist.
- A small role-scarcity factor based on the available player pool.
The final estimate is bounded relative to the configured purse (40% of one team
purse). This is an estimate, not a guaranteed winning bid. Live team purse, squad
gaps, overseas slots and bidding competition are not currently modelled per team.

INSTALL / UPDATE
----------------
1. Back up your existing app and database.
2. Extract this ZIP and replace your existing `players/` directory with this one.
   Do not replace your project settings or other apps.
3. From the directory containing manage.py, run:

       python manage.py check
       python manage.py migrate
       python manage.py recalc_values
       python manage.py recalc_market_values

4. Open `/markets/` to browse the default auction markets.
5. To add BBL, PSL, SA20 or a custom league, open Django Admin → Auction market
   profiles → Add. Choose format, purse, squad size, team count, source category
   and source group. For IPL-style profiles use source category `LEAGUE` and group
   `ipl`; for other league groups use their matching slug (e.g. `bbl`, `psl`, `sa20`).
6. After changing market settings or importing new player data, run:

       python manage.py recalc_market_values

POTENTIAL / AGE DATA
--------------------
Player date of birth is optional and must be verified before entry. The engine
never treats 32+ as a penalty. Consistency and career quality remain important.
A potential_rating override is also optional; leave it blank unless you have a
scouting assessment. It is not hardcoded by player name.

IMPORTANT DATA LIMITS
--------------------
- Market estimates depend on the records actually imported. Missing league or
  domestic performances cannot be inferred from international performances.
- The current model does not know each team's actual remaining purse, squad gaps,
  overseas slots already used, or live bidding competition. Those can be added in
  a later team-specific auction-demand layer.
- Existing DOM_IN combined valuations are retained as legacy data. Run
  `recalc_values` after migration to create new format-specific domestic values.
- A full project-level database migration/check must be run inside your Django
  project because this ZIP intentionally contains only the `players` app.
