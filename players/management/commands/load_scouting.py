"""Load scouting / market ratings (0-100) from players/scouting.csv into Player.potential_rating.

    python manage.py load_scouting            # uses players/scouting.csv
    python manage.py load_scouting my.csv     # or your own file (columns: name,rating)

Edit the CSV any time and run again. Names are matched ignoring case, dots and spacing.
Players not in the file keep whatever potential_rating they already have.
"""
import csv
import os
import re

from django.core.management.base import BaseCommand, CommandError

from players.models import Player


def _key(name):
    return " ".join(re.sub(r"[^a-z\s]", " ", str(name or "").lower()).split())


class Command(BaseCommand):
    help = "Load scouting/market ratings from a CSV into Player.potential_rating."

    def add_arguments(self, parser):
        default = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scouting.csv")
        parser.add_argument("path", nargs="?", default=default)

    def handle(self, *args, **opts):
        path = opts["path"]
        if not os.path.exists(path):
            raise CommandError(f"File not found: {path}")
        by_key = {}
        for p in Player.objects.all():
            by_key.setdefault(_key(p.name), []).append(p)
        updated, missing = 0, []
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                name, rating = row["name"].strip(), float(row["rating"])
                matches = by_key.get(_key(name), [])
                if not matches:
                    missing.append(name)
                    continue
                for p in matches:
                    p.potential_rating = max(0.0, min(100.0, rating))
                    p.save(update_fields=["potential_rating"])
                    updated += 1
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} players."))
        if missing:
            self.stdout.write("Not found in database: " + ", ".join(missing))
