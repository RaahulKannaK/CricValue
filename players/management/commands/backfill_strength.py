
import json
from pathlib import Path
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from players.models import Match, Player
from players.categories import category_of
from players.strength import strength_of


class Command(BaseCommand):

    help = (
        "Safely backfill match categories, teams, "
        "lineups and competition strength."
    )

    def add_arguments(self, parser):

        parser.add_argument(
            "--data",
            default=str(settings.BASE_DIR / "data"),
            help="Directory containing Cricsheet JSON files.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without saving.",
        )

    def handle(self, *args, **options):

        data_dir = Path(options["data"])
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN: no database changes will be saved."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "LIVE RUN: all changes will be saved transactionally."
                )
            )

        if not data_dir.exists():
            self.stdout.write(
                self.style.ERROR(
                    f"Data directory does not exist: {data_dir}"
                )
            )
            return

        # --------------------------------------------------
        # 1. INDEX CRICSHEET JSON FILES
        # --------------------------------------------------

        self.stdout.write("\nIndexing Cricsheet JSON files...")

        json_index = {
            file.stem: file
            for file in data_dir.rglob("*.json")
        }

        self.stdout.write(
            f"Found {len(json_index)} JSON files."
        )

        # --------------------------------------------------
        # 2. LOAD DATABASE MATCHES
        # --------------------------------------------------

        matches = list(Match.objects.all())

        self.stdout.write(
            f"Processing {len(matches)} matches..."
        )

        changed_fields = set()
        changed_matches = []

        counts = Counter()
        category_counts = Counter()

        incomplete_lineup_details = []

        # Cache players by Cricsheet ID.
        player_cache = {}

        def find_player(player_name, team, cricsheet_id):

            cache_key = cricsheet_id or (
                f"{team}|{player_name}"
            )

            if cache_key in player_cache:
                return player_cache[cache_key]

            player = None

            # FIRST: Exact Cricsheet ID match.
            if cricsheet_id:

                player = Player.objects.filter(
                    cricsheet_id=cricsheet_id
                ).first()

            # SECOND: Exact name + country match.
            if player is None:

                player = Player.objects.filter(
                    name__iexact=player_name,
                    country__iexact=team,
                ).first()

            # THIRD: Create only with a verified Cricsheet ID.
            if player is None and cricsheet_id and not dry_run:

                player = Player.objects.create(
                    name=player_name,
                    cricsheet_id=cricsheet_id,
                    country=team,
                    role="BAT",
                )

                counts["players_created"] += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created player: {player_name} ({team}) "
                        f"[{cricsheet_id}]"
                    )
                )

            player_cache[cache_key] = player

            return player

        # --------------------------------------------------
        # 3. PROCESS EVERYTHING TRANSACTIONALLY
        # --------------------------------------------------

        try:

            with transaction.atomic():

                for match in matches:

                    old_category = match.category
                    old_strength = match.strength
                    old_teams = match.teams
                    old_lineups = match.lineups

                    match_changed_fields = set()

                    # --------------------------------------
                    # 3A. CATEGORY
                    # --------------------------------------

                    calculated_category = category_of(
                        match.level,
                        match.fmt,
                        match.competition,
                    )

                    effective_category = (
                        calculated_category or old_category
                    )

                    if calculated_category:

                        if calculated_category != old_category:

                            match.category = calculated_category

                            match_changed_fields.add(
                                "category"
                            )

                            counts["category_changes"] += 1

                    # --------------------------------------
                    # 3B. INTERNATIONAL TEAMS AND LINEUPS
                    # --------------------------------------

                    if effective_category in (
                        "T20",
                        "ODI",
                        "TEST",
                    ):

                        json_file = json_index.get(
                            str(match.external_id)
                        )

                        if json_file:

                            try:

                                content = json.loads(
                                    json_file.read_text(
                                        encoding="utf-8"
                                    )
                                )

                            except (
                                OSError,
                                ValueError,
                                TypeError,
                            ) as exc:

                                counts["json_errors"] += 1

                                self.stdout.write(
                                    self.style.WARNING(
                                        f"JSON issue for match "
                                        f"{match.external_id}: {exc}"
                                    )
                                )

                                continue

                            info = content.get("info", {})

                            json_teams = (
                                info.get("teams") or []
                            )

                            json_players = (
                                info.get("players") or {}
                            )

                            registry = (
                                info.get("registry") or {}
                            ).get("people", {})

                            # ----------------------------------
                            # TEAM UPDATE
                            # ----------------------------------

                            if (
                                isinstance(json_teams, list)
                                and json_teams
                                and all(
                                    isinstance(team, str)
                                    and team.strip()
                                    for team in json_teams
                                )
                            ):

                                new_teams = " vs ".join(
                                    json_teams
                                )[:160]

                                if new_teams != old_teams:

                                    match.teams = new_teams

                                    match_changed_fields.add(
                                        "teams"
                                    )

                                    counts["teams_updated"] += 1

                            # ----------------------------------
                            # LINEUP UPDATE
                            # ----------------------------------

                            if (
                                isinstance(json_players, dict)
                                and json_players
                                and isinstance(registry, dict)
                            ):

                                new_lineups = {}
                                unresolved_players = []

                                for team, names in json_players.items():

                                    if not isinstance(names, list):

                                        unresolved_players.append(
                                            f"{team}: Invalid player list"
                                        )

                                        continue

                                    player_ids = []

                                    for player_name in names:

                                        if (
                                            not isinstance(player_name, str)
                                            or not player_name.strip()
                                        ):

                                            unresolved_players.append(
                                                f"{team}: Invalid player name"
                                            )

                                            continue

                                        # Cricsheet registry maps:
                                        # PLAYER NAME -> CRICSHEET ID
                                        cricsheet_id = registry.get(
                                            player_name
                                        )

                                        player = find_player(
                                            player_name,
                                            team,
                                            cricsheet_id,
                                        )

                                        if player is None:

                                            unresolved_players.append(
                                                f"{team}: {player_name}"
                                            )

                                            continue

                                        player_ids.append(
                                            player.pk
                                        )

                                    if player_ids:

                                        new_lineups[team] = player_ids

                                # ----------------------------------
                                # ALL-OR-NOTHING LINEUP UPDATE
                                # ----------------------------------

                                if unresolved_players:

                                    counts["incomplete_lineups"] += 1

                                    incomplete_lineup_details.append(
                                        {
                                            "match_id": match.external_id,
                                            "competition": match.competition,
                                            "players": unresolved_players,
                                        }
                                    )

                                elif (
                                    new_lineups
                                    and new_lineups != (old_lineups or {})
                                ):

                                    match.lineups = new_lineups

                                    match_changed_fields.add(
                                        "lineups"
                                    )

                                    counts["lineups_updated"] += 1

                            counts["json_found"] += 1

                        else:

                            counts["json_missing"] += 1

                    # --------------------------------------
                    # 3C. COMPETITION STRENGTH
                    # --------------------------------------

                    if effective_category:

                        new_strength = strength_of(
                            effective_category,
                            match.competition,
                        )

                        if new_strength != old_strength:

                            match.strength = new_strength

                            match_changed_fields.add(
                                "strength"
                            )

                            counts["strength_changes"] += 1

                        category_counts[
                            effective_category
                        ] += 1

                    else:

                        counts["unclassified"] += 1

                    # --------------------------------------
                    # 3D. TRACK CHANGED MATCHES
                    # --------------------------------------

                    if match_changed_fields:

                        changed_matches.append(match)

                        changed_fields.update(
                            match_changed_fields
                        )

                # ------------------------------------------
                # 4. SAVE MATCHES
                # ------------------------------------------

                if not dry_run and changed_matches:

                    fields = sorted(changed_fields)

                    Match.objects.bulk_update(
                        changed_matches,
                        fields,
                        batch_size=500,
                    )

                if dry_run:

                    # No writes are performed in dry-run mode.
                    pass

        except Exception as exc:

            self.stdout.write(
                self.style.ERROR(
                    "\nBACKFILL FAILED. Transaction rolled back."
                )
            )

            raise exc

        # --------------------------------------------------
        # 5. COMPLETION MESSAGE
        # --------------------------------------------------

        if dry_run:

            self.stdout.write(
                self.style.WARNING(
                    "\nDRY RUN COMPLETE - nothing was saved."
                )
            )

        else:

            self.stdout.write(
                self.style.SUCCESS(
                    "\nDatabase backfill completed successfully."
                )
            )

        # --------------------------------------------------
        # 6. SUMMARY
        # --------------------------------------------------

        self.stdout.write(
            "\n========== BACKFILL SUMMARY =========="
        )

        summary_keys = [
            "category_changes",
            "strength_changes",
            "teams_updated",
            "lineups_updated",
            "incomplete_lineups",
            "players_created",
            "json_found",
            "json_missing",
            "json_errors",
            "unclassified",
        ]

        for key in summary_keys:

            self.stdout.write(
                f"{key}: {counts[key]}"
            )

        # --------------------------------------------------
        # 7. CATEGORY TOTALS
        # --------------------------------------------------

        self.stdout.write(
            "\n========== CATEGORY TOTALS =========="
        )

        for category, total in sorted(
            category_counts.items()
        ):

            self.stdout.write(
                f"{category}: {total}"
            )

        # --------------------------------------------------
        # 8. INCOMPLETE LINEUPS
        # --------------------------------------------------

        self.stdout.write(
            "\n========== INCOMPLETE LINEUP DETAILS =========="
        )

        if incomplete_lineup_details:

            for item in incomplete_lineup_details:

                self.stdout.write(
                    f"\nMatch ID: {item['match_id']}"
                )

                self.stdout.write(
                    f"Competition: {item['competition']}"
                )

                for player in item["players"]:

                    self.stdout.write(
                        f"  UNRESOLVED: {player}"
                    )

        else:

            self.stdout.write(
                "No incomplete lineups found."
            )

        # --------------------------------------------------
        # 9. FINAL CHANGE DETAILS
        # --------------------------------------------------

        self.stdout.write(
            "\n========== CHANGE DETAILS =========="
        )

        self.stdout.write(
            f"Matches changed: {len(changed_matches)}"
        )

        self.stdout.write(
            "Fields prepared for update: "
            + (
                ", ".join(sorted(changed_fields))
                if changed_fields
                else "None"
            )
        )

        if dry_run:

            self.stdout.write(
                self.style.WARNING(
                    "\nNo database records were modified."
                )
            )
