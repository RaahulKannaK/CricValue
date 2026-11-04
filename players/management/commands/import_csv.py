"""Provider-agnostic importer. CSV columns:
date,competition,level,fmt,external_id,player,country,role,runs,balls,wickets,runs_conceded,overs
Swap this for an API client (or Cricsheet converter) once you pick a data source."""
import csv
from django.core.management.base import BaseCommand
from players.models import Player, Match, Performance
from django.core.management import call_command
from players.categories import category_of

class Command(BaseCommand):
    help = "Import match performances from a CSV file and recalculate values."
    def add_arguments(self, parser):
        parser.add_argument("path")
    def handle(self, *a, **o):
        touched = set()
        with open(o["path"], newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                m, _ = Match.objects.get_or_create(
                    external_id=r["external_id"],
                    defaults=dict(date=r["date"], competition=r["competition"],
                                  level=r["level"], fmt=r["fmt"],
                                  category=category_of(r["level"], r["fmt"], r["competition"]) or ""))
                p, _ = Player.objects.get_or_create(
                    name=r["player"], country=r["country"], defaults=dict(role=r["role"]))
                Performance.objects.update_or_create(player=p, match=m, defaults=dict(
                    runs=int(r["runs"]), balls=int(r["balls"]), wickets=int(r["wickets"]),
                    runs_conceded=int(r["runs_conceded"]), overs=float(r["overs"])))
                touched.add(p.pk)
        if touched:
            call_command("recalc_values")
        self.stdout.write(f"Imported; updated {len(touched)} players")
