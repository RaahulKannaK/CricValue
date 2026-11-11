"""Import verified player nationalities from CSV (cricsheet_id,name,country)."""
import csv
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from players.models import Player


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("csv_file")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--overwrite", action="store_true", help="allow replacing an already-known country")

    def handle(self, *args, **opts):
        changed = skipped = conflicts = 0
        with open(opts["csv_file"], newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not {"name", "country"}.issubset(reader.fieldnames or []):
                raise CommandError("CSV must contain name,country and optionally cricsheet_id")
            with transaction.atomic():
                for row in reader:
                    cid = (row.get("cricsheet_id") or "").strip()
                    name = (row.get("name") or "").strip()
                    country = (row.get("country") or "").strip()
                    if not country:
                        skipped += 1
                        continue
                    qs = Player.objects.filter(cricsheet_id=cid) if cid else Player.objects.filter(name__iexact=name)
                    if qs.count() != 1:
                        skipped += 1
                        self.stderr.write(f"SKIP {name or cid}: found {qs.count()} players")
                        continue
                    player = qs.first()
                    old = (player.country or "").strip()
                    if old not in ("", "Unknown", "Country Unknown") and old != country and not opts["overwrite"]:
                        conflicts += 1
                        self.stderr.write(f"CONFLICT {player.name}: existing={old}, csv={country}")
                        continue
                    if old != country:
                        changed += 1
                        if opts["apply"]:
                            Player.objects.filter(pk=player.pk).update(country=country, updated=timezone.now())
        self.stdout.write(f"{'Updated' if opts['apply'] else 'Would update'}: {changed}; skipped: {skipped}; conflicts: {conflicts}")
        if not opts["apply"]:
            self.stdout.write("DRY RUN ONLY. Re-run with --apply after checking the CSV.")
