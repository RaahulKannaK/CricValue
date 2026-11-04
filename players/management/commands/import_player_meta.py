"""Add verified date of birth (and optional role / demand) to players.

  python manage.py import_player_meta --export meta.csv     (writes active players to fill in)
  python manage.py import_player_meta meta.csv [--dry-run]  (reads it back)

CSV columns: cricsheet_id, name, country, dob (YYYY-MM-DD), role (BAT/BOWL/AR/WK, optional),
demand (optional multiplier, 0.7 to 1.4). Rows are matched by cricsheet_id, else by exact name.
Only fill in dates of birth you have checked; blank cells are left unchanged."""
import csv
import datetime as dt
from django.core.management.base import BaseCommand, CommandError
from players.models import Player


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?")
        parser.add_argument("--export", help="write a CSV of recently active players to fill in")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *a, **o):
        if o["export"]:
            cutoff = dt.date.today() - dt.timedelta(days=365)
            qs = Player.objects.filter(cat_values__last_played__gte=cutoff).distinct().order_by("name")
            with open(o["export"], "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["cricsheet_id", "name", "country", "dob", "role", "demand"])
                for p in qs:
                    w.writerow([p.cricsheet_id or "", p.name, p.country, p.dob or "", "", ""])
            self.stdout.write(f"Wrote {qs.count()} players to {o['export']}")
            return
        if not o["path"]:
            raise CommandError("Give a CSV path, or use --export")
        done = missing = 0
        with open(o["path"], newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                cid, name = (row.get("cricsheet_id") or "").strip(), (row.get("name") or "").strip()
                qs = Player.objects.filter(cricsheet_id=cid) if cid else Player.objects.filter(name__iexact=name)
                if qs.count() != 1:
                    missing += 1
                    self.stderr.write(f"skip {name or cid!r}: {qs.count()} matching players")
                    continue
                p = qs.first()
                changed = []
                if (row.get("dob") or "").strip():
                    try:
                        p.dob = dt.date.fromisoformat(row["dob"].strip())
                        changed.append("dob")
                    except ValueError:
                        self.stderr.write(f"bad date for {p.name}: {row['dob']!r} (use YYYY-MM-DD)")
                if (row.get("role") or "").strip().upper() in ("BAT", "BOWL", "AR", "WK"):
                    p.role, p.role_locked = row["role"].strip().upper(), True
                    changed.append("role")
                if (row.get("demand") or "").strip():
                    try:
                        p.market_demand = max(0.7, min(1.4, float(row["demand"])))
                        changed.append("demand")
                    except ValueError:
                        self.stderr.write(f"bad demand for {p.name}: {row['demand']!r}")
                if changed and not o["dry_run"]:
                    p.save()
                done += bool(changed)
        self.stdout.write(f"{'Would update' if o['dry_run'] else 'Updated'} {done} players; {missing} rows not matched. "
                          f"Now run: python manage.py recalc_values")
