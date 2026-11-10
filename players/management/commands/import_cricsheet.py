import json
from pathlib import Path
from django.core.management.base import BaseCommand
from players.cricsheet import parse_match
from players.importer import MatchImporter
from players.models import Player, Match, Performance

class Command(BaseCommand):
    help = "Import Cricsheet JSON match files from a folder (or one file)."
    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--women", action="store_true", help="include women's matches")
        parser.add_argument("--backfill-phases", action="store_true",
                            help="for matches already imported, only fill in phase / batting-position data")

    def handle(self, *a, **o):
        p = Path(o["path"])
        files = [p] if p.is_file() else sorted(p.glob("*.json"))
        new = skipped = filled = 0
        importer = None if o["backfill_phases"] else MatchImporter(o["women"])
        for f in files:
            ext = f.stem
            existing = Match.objects.filter(external_id=ext).first()
            if existing and o["backfill_phases"]:
                filled += self.backfill(existing, f, o["women"])
                continue
            if existing:
                skipped += 1
                continue
            try:
                status = importer.import_one(ext, json.loads(f.read_text(encoding="utf-8")))
            except (KeyError, ValueError) as e:
                self.stderr.write(f"skip {f.name}: {e}")
                continue
            if status == "new":
                new += 1
            else:
                skipped += 1
        if o["backfill_phases"]:
            self.stdout.write(f"Backfilled phase data for {filled} performances")
        else:
            self.stdout.write(f"Imported {new} new matches, skipped {skipped}")

    def backfill(self, match, path, women):
        """Add phases to Performance rows of an already-imported match; never creates players."""
        try:
            m = parse_match(json.loads(path.read_text(encoding="utf-8")), women)
        except (KeyError, ValueError):
            return 0
        if not m:
            return 0
        n = 0
        for r in m["players"]:
            if not r.get("phases"):
                continue
            pl = Player.objects.filter(cricsheet_id=r["cid"]).first() if r["cid"] else None
            if pl is None:
                pl = Player.objects.filter(name=r["name"], country=r["country"] or "Unknown").first()
            if pl is None:
                continue
            n += Performance.objects.filter(player=pl, match=match).update(phases=r["phases"])
        return n
