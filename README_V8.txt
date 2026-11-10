CRICVALUE v8 - AUCTION-VALUE MODEL (changed and new files only)

Copy these files into your project, keeping the folder structure:
  NEW      players/auction.py                                   the model (constants at the top)
  NEW      players/migrations/0009_auction_model.py             new columns
  NEW      players/management/commands/import_player_meta.py    verified date of birth / role / demand
  NEW      players/management/commands/calibrate_values.py      compare model vs prices you believe
  CHANGED  players/models.py
  CHANGED  players/valuation.py        (only history() changed)
  CHANGED  players/views.py            (one call in detail())
  CHANGED  players/admin.py
  CHANGED  players/templates/players/list.html
  CHANGED  players/templates/players/detail.html
  CHANGED  players/management/commands/recalc_values.py
  CHANGED  players/management/commands/debug_player.py

Then:
  python manage.py migrate
  python manage.py recalc_values

HOW A PRICE IS BUILT
  ability percentile (career, recency-weighted, versus active players of the same role and format)
  + potential (young + real quality; verified age if known, otherwise a smaller match-data estimate)
  -> market score -> smooth price curve (no match-count ceilings, no hard clamps)
  x role scarcity x top-of-pool demand x small-sample risk (max 10%)
  then form is added on top, trusted less after a long gap, a short streak, or few recent appearances.
  The range shown is the uncertainty (smaller for long, consistent records).

NOT IN THE DATA (so not invented)
  Age/date of birth, injuries, retirement, actual auction demand, team purses, wicketkeeper role.
  Add dates of birth with import_player_meta. Everything is a statistical estimate.
