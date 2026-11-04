import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from players.cricsheet import parse_match
from players.models import Player, Match, Performance
from players.categories import category_of
from players.strength import strength_of

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
                m = parse_match(json.loads(f.read_text(encoding="utf-8")), o["women"])
            except (KeyError, ValueError) as e:
                self.stderr.write(f"skip {f.name}: {e}")
                continue
            if not m or not m["date"]:
                skipped += 1
                continue
            cat = category_of(m["level"], m["fmt"], m["competition"]) or ""
            with transaction.atomic():
                lineup_ids = {}
                for team, selected in (m.get("lineups") or {}).items():
                    ids = []
                    for entry in selected:
                        cid, name = entry.get("cid") or "", entry["name"]
                        pl = Player.objects.filter(cricsheet_id=cid).first() if cid else None
                        if pl is None:
                            pl = Player.objects.filter(name=name, country=team).first()
                        if pl is None:
                            pl = Player.objects.create(
                                name=name, cricsheet_id=cid or None,
                                country=team if m["level"] == "INTL" else "Unknown", role="BAT")
                        elif m["level"] == "INTL" and pl.country != team:
                            pl.country = team
                            pl.save(update_fields=["country"])
                        ids.append(pl.pk)
                    lineup_ids[team] = ids

                match = Match.objects.create(
                    date=m["date"], competition=m["competition"][:80], level=m["level"],
                    fmt=m["fmt"], external_id=ext, category=cat,
                    teams=" vs ".join(m["teams"])[:160], lineups=lineup_ids,
                    strength=strength_of(cat, m["competition"], m["teams"]))
                for r in m["players"]:
                    pl = Player.objects.filter(cricsheet_id=r["cid"]).first() if r["cid"] else None
                    if pl is None:
                        pl = Player.objects.filter(name=r["name"], country=r["country"] or "Unknown").first()
                    if pl is None:
                        pl = Player.objects.create(
                            name=r["name"], cricsheet_id=r["cid"] or None,
                            country=r["country"] or "Unknown", role="BAT")
                    elif r["country"] and pl.country != r["country"]:
                        pl.country = r["country"]
                        pl.save(update_fields=["country"])
                    Performance.objects.update_or_create(player=pl, match=match, defaults=dict(
                        runs=r["runs"], balls=r["balls"], wickets=r["wickets"],
                        runs_conceded=r["conceded"], overs=r["overs"], phases=r.get("phases") or {}))
            new += 1
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
