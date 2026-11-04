"""Daily job: download the latest Cricsheet matches, import them, recalculate values, record the run.

  python manage.py daily_update            (last 7 days of matches)
  python manage.py daily_update --days 30  (catch up after the site was off for a while)

Safe to run twice: matches already imported are skipped, and a lock file stops overlapping runs."""
import datetime as dt
import json
import time
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max
from players.models import Match


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, choices=[2, 7, 30], default=7)

    def handle(self, *a, **o):
        data = settings.BASE_DIR / "data"
        data.mkdir(exist_ok=True)
        lock = data / "daily_update.lock"
        if lock.exists() and time.time() - lock.stat().st_mtime < 6 * 3600:
            self.stdout.write("Another update is running (lock file under 6 hours old). Skipping.")
            return
        lock.write_text(dt.datetime.now().isoformat())
        before, ok, error = Match.objects.count(), True, ""
        try:
            call_command("update_data", "--source", f"recently_added_{o['days']}_json")
        except Exception as e:          # record the failure, then report it below
            ok, error = False, str(e)[:300]
        finally:
            lock.unlink(missing_ok=True)
        latest = Match.objects.aggregate(m=Max("date"))["m"]
        new = Match.objects.count() - before
        (data / "last_update.json").write_text(json.dumps({
            "ran_at": dt.datetime.now().isoformat(timespec="seconds"), "ok": ok, "error": error,
            "new_matches": new, "latest_match": latest.isoformat() if latest else ""}), encoding="utf-8")
        if not ok:
            raise CommandError(f"Update failed: {error}")
        self.stdout.write(self.style.SUCCESS(f"Daily update done: {new} new matches, data up to {latest}."))
