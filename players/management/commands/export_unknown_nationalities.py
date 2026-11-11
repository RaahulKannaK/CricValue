"""Export players whose nationality is not known; fill country and re-import with import_player_nationality."""
import csv
from django.core.management.base import BaseCommand
from players.models import Player


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--output", default="unknown_nationalities.csv")

    def handle(self, *args, **opts):
        qs = Player.objects.filter(country__in=["", "Unknown", "Country Unknown"]).order_by("name", "id")
        with open(opts["output"], "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["cricsheet_id", "name", "country"])
            for p in qs:
                w.writerow([p.cricsheet_id or "", p.name, ""])
        self.stdout.write(f"Exported {qs.count()} players to {opts['output']}; fill only verified nationalities.")
