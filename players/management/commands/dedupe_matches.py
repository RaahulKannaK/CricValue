"""Safely consolidate duplicate Match.external_id rows.

Dry run (default): python manage.py dedupe_matches
Apply safe groups: python manage.py dedupe_matches --apply

Groups with conflicting match details or conflicting player statistics are
skipped for manual review. Statistics are never added together.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from players.models import Match, Performance

CORE_FIELDS = ("date", "competition", "level", "fmt", "category", "teams")
STAT_FIELDS = ("runs", "balls", "wickets", "runs_conceded", "overs")


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="perform safe merges and deletions")
        parser.add_argument("--limit", type=int, default=0, help="inspect only the first N duplicate groups")

    def handle(self, *args, **opts):
        groups = (Match.objects.exclude(external_id__isnull=True).exclude(external_id="")
                  .values("external_id").annotate(n=Count("id")).filter(n__gt=1)
                  .order_by("external_id"))
        if opts["limit"]:
            groups = groups[:opts["limit"]]
        groups = list(groups)
        self.stdout.write(f"Duplicate external-ID groups: {len(groups)}")
        safe = conflicts = deleted = moved = removed_perfs = 0

        for group in groups:
            ext = group["external_id"]
            matches = list(Match.objects.filter(external_id=ext).order_by("id"))
            # Prefer the row with the most performances; stable lowest-PK tie break.
            counts = {m.pk: Performance.objects.filter(match=m).count() for m in matches}
            canonical = sorted(matches, key=lambda m: (-counts[m.pk], -bool(m.lineups), m.pk))[0]
            duplicates = [m for m in matches if m.pk != canonical.pk]
            reason = self._conflict(canonical, duplicates)
            if reason:
                conflicts += 1
                self.stdout.write(self.style.WARNING(f"SKIP {ext}: {reason}"))
                continue
            safe += 1
            if not opts["apply"]:
                self.stdout.write(f"SAFE {ext}: keep Match DB ID {canonical.pk}; remove {[m.pk for m in duplicates]}")
                continue

            with transaction.atomic():
                canonical = Match.objects.select_for_update().get(pk=canonical.pk)
                # Fill blank metadata from duplicate rows only; core fields were checked.
                for duplicate in duplicates:
                    duplicate = Match.objects.get(pk=duplicate.pk)
                    if not canonical.lineups and duplicate.lineups:
                        canonical.lineups = duplicate.lineups
                    perfs = list(Performance.objects.filter(match=duplicate))
                    for perf in perfs:
                        existing = Performance.objects.filter(match=canonical, player_id=perf.player_id).first()
                        if existing:
                            updates = []
                            if not existing.phases and perf.phases:
                                existing.phases = perf.phases
                                updates.append("phases")
                            if existing.opp_strength == 1.0 and perf.opp_strength != 1.0:
                                existing.opp_strength = perf.opp_strength
                                updates.append("opp_strength")
                            if updates:
                                existing.save(update_fields=updates)
                            perf.delete()
                            removed_perfs += 1
                        else:
                            perf.match = canonical
                            perf.save(update_fields=["match"])
                            moved += 1
                    duplicate.delete()
                    deleted += 1
                canonical.save(update_fields=["lineups"])

        self.stdout.write(f"Safe groups: {safe}; conflicting groups skipped: {conflicts}")
        if opts["apply"]:
            self.stdout.write(self.style.SUCCESS(
                f"Deleted duplicate matches: {deleted}; moved performances: {moved}; "
                f"removed exact duplicate performances: {removed_perfs}"))
        else:
            self.stdout.write("DRY RUN ONLY: no database rows changed. Add --apply after taking a DB backup.")

    @staticmethod
    def _conflict(canonical, duplicates):
        all_matches = [canonical] + duplicates
        for duplicate in duplicates:
            for field in CORE_FIELDS:
                if getattr(canonical, field) != getattr(duplicate, field):
                    return f"match field {field} differs (DB IDs {canonical.pk}/{duplicate.pk})"

        nonempty_lineups = [m.lineups for m in all_matches if m.lineups]
        if nonempty_lineups and any(value != nonempty_lineups[0] for value in nonempty_lineups[1:]):
            return "non-empty lineups differ across duplicate rows"

        # Compare all copies, not just each duplicate against the canonical row:
        # two duplicate rows may both contain a player absent from the canonical row.
        seen = {}
        for match in all_matches:
            for perf in Performance.objects.filter(match=match):
                previous = seen.get(perf.player_id)
                if previous is None:
                    seen[perf.player_id] = perf
                    continue
                if any(getattr(previous, f) != getattr(perf, f) for f in STAT_FIELDS):
                    return f"player {perf.player_id} has conflicting statistics"
                if previous.phases and perf.phases and previous.phases != perf.phases:
                    return f"player {perf.player_id} has conflicting phase data"
                if not previous.phases and perf.phases:
                    seen[perf.player_id] = perf
        return ""
