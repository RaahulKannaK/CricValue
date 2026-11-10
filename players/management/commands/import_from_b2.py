"""Import Cricsheet matches stored in the Backblaze B2 bucket into the database.

  python manage.py import_from_b2                                  (daily: files new since the last import)
  python manage.py import_from_b2 --zip raw/cricsheet/all_json.zip (first load from the full archive)
  python manage.py import_from_b2 --all                            (check every file under matches/)

Safe to run twice: matches already in the database are skipped, and every match is
committed on its own, so an interrupted run simply continues next time.
Status is written to metadata/import_status.json in the bucket.
"""
import datetime as dt
import io
import json
import zipfile
from pathlib import PurePosixPath

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from players import storage_b2 as b2
from players.importer import MatchImporter
from players.models import Match

STATUS_KEY = "metadata/import_status.json"


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--zip", help="key of a Cricsheet zip in the bucket")
        parser.add_argument("--prefix", default="matches/")
        parser.add_argument("--overlap-days", type=int, default=2,
                            help="re-check files this many days before the last successful import")
        parser.add_argument("--all", action="store_true", help="ignore the last-import time")
        parser.add_argument("--women", action="store_true")
        parser.add_argument("--no-recalc", action="store_true")

    def handle(self, *a, **o):
        if not b2.configured():
            raise CommandError("Set B2_KEY_ID, B2_APP_KEY, B2_BUCKET and B2_ENDPOINT first.")
        now = dt.datetime.now(dt.timezone.utc)
        status = b2.get_json(STATUS_KEY, {}) or {}
        known = set(Match.objects.values_list("external_id", flat=True))
        importer = MatchImporter(women=o["women"])
        new = skipped = failed = 0
        first_error = ""

        for ext, load in self.items(o, status):
            if ext in known:
                skipped += 1
                continue
            try:
                result = importer.import_one(ext, json.loads(load()))
            except Exception as e:      # keep going; the run is reported as failed at the end
                failed += 1
                first_error = first_error or f"{ext}: {e}"[:300]
                if failed <= 20:
                    self.stderr.write(f"failed {ext}: {e}")
                continue
            known.add(ext)
            if result == "new":
                new += 1
                if new % 500 == 0:
                    self.stdout.write(f"  ... {new} matches imported")
            else:
                skipped += 1        # e.g. women's matches when --women is not set

        self.stdout.write(f"Imported {new} new matches, skipped {skipped}, failed {failed}")
        if new and not o["no_recalc"]:
            call_command("recalc_values", "--base")

        latest = Match.objects.aggregate(m=Max("date"))["m"]
        report = {
            "ran_at": now.isoformat(timespec="seconds"),
            "ok": failed == 0,
            "error": first_error,
            "new_matches": new,
            "latest_match": latest.isoformat() if latest else "",
            "last_success_at": now.isoformat(timespec="seconds") if failed == 0
                               else status.get("last_success_at", ""),
        }
        try:
            b2.put_json(STATUS_KEY, report)
        except Exception as e:
            self.stderr.write(f"Could not write {STATUS_KEY}: {e}")
        if failed:
            raise CommandError(f"{failed} matches failed. First error: {first_error}")
        self.stdout.write(self.style.SUCCESS(f"Done. Data up to {latest}."))

    def items(self, o, status):
        """Yield (match id, function that returns the JSON bytes)."""
        if o["zip"]:
            self.stdout.write(f"Reading {o['zip']} from the bucket ...")
            zf = zipfile.ZipFile(io.BytesIO(b2.get_bytes(o["zip"])))
            for name in sorted(zf.namelist()):
                if name.endswith(".json"):
                    yield PurePosixPath(name).stem, (lambda n=name: zf.read(n))
            return

        cutoff = None
        if not o["all"] and status.get("last_success_at"):
            cutoff = (dt.datetime.fromisoformat(status["last_success_at"])
                      - dt.timedelta(days=o["overlap_days"]))
        for obj in b2.list_objects(o["prefix"]):
            key = obj["Key"]
            if not key.endswith(".json"):
                continue
            if cutoff and obj["LastModified"] < cutoff:
                continue
            yield PurePosixPath(key).stem, (lambda k=key: b2.get_bytes(k))
