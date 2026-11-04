"""Compare the model's estimates with prices you believe are right (reports only; changes nothing).

CSV columns: name, category (T20/ODI/TEST/LEAGUE/DOM_IN), low, high   (Rs crore)
  python manage.py calibrate_values anchors.csv
Use it to see which players the model places too high or too low, then adjust the constants at the
top of players/auction.py (CURVE_POWER, POT_MAX, FORM_UP, ...) and run recalc_values again."""
import csv
from django.core.management.base import BaseCommand
from players.models import CategoryValue


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *a, **o):
        ok = total = 0
        self.stdout.write(f"{'player':26} {'tab':6} {'target':>11} {'model':>7} {'range':>11}  ability form potential  verdict")
        with open(o["path"], newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                cat = row["category"].strip().upper()
                lo, hi = float(row["low"]), float(row["high"])
                cvs = list(CategoryValue.objects.filter(player__name__icontains=row["name"].strip(),
                           category=cat, group="").select_related("player")[:3])
                if not cvs:
                    self.stdout.write(f"{row['name']:26} {cat:6} not found")
                    continue
                for cv in cvs:
                    t = float(cv.total)
                    verdict = "ok" if lo <= t <= hi else f"too {'low' if t < lo else 'high'} by {abs(t - (lo if t < lo else hi)):.1f}"
                    total += 1
                    ok += verdict == "ok"
                    self.stdout.write(f"{cv.player.name[:26]:26} {cat:6} {lo:5.1f}-{hi:<5.1f} {t:7.1f} {cv.price_low:5.1f}-{cv.price_high:<5.1f} "
                                      f"{cv.quality_score:6.0f}% {cv.form_score:+4.0f}% {cv.potential_score:5.0f}     {verdict}")
        self.stdout.write(f"\n{ok} of {total} inside the target range")
