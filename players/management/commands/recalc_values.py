
import datetime as dt
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from players.categories import GROUPS, TAB_BY_KEY, group_of
from players.engine import opposition_factors
from players.models import CategoryValue, Match, Performance, Player
from players.rating import infer_role
from players.strength import nation_scale
from players.tiers import (
    tier_of,
    band_price,
    price_band_of,
    ceiling_for,
    final_price,
)
from players.valuation import (
    INTL_CATS,
    SETTINGS,
    raw_from_stats,
    rating_of,
    recent_level,
    form_pct,
    quality_score,
    consistency_score,
    confidence_score,
    experience_score,
)

LOOKBACK = 8


class Command(BaseCommand):
    help = (
        "Recalculate opposition strength, player quality, form, "
        "confidence, tiers and prices."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--base",
            action="store_true",
            help="Compatibility flag; locked manual values remain locked.",
        )

    def opposition(self):
        total = 0

        for cat in INTL_CATS:
            rows = Performance.objects.filter(
                match__category=cat
            ).values_list(
                "id",
                "player_id",
                "match_id",
                "runs",
                "balls",
                "wickets",
                "runs_conceded",
                "overs",
                "match__date",
                "match__fmt",
                "match__teams",
                "player__country",
            )

            perfs = []
            match_teams = {}
            match_lineups = {}

            for match in Match.objects.filter(
                category=cat
            ).values("id", "teams", "lineups").iterator(
                chunk_size=2000
            ):
                ts = tuple(
                    t.strip()
                    for t in (match["teams"] or "").split(" vs ")
                    if t.strip()
                )

                if len(ts) == 2:
                    match_teams[match["id"]] = ts
                    match_lineups[match["id"]] = (
                        match.get("lineups") or {}
                    )

            for (
                performance_id,
                player_id,
                match_id,
                runs,
                balls,
                wickets,
                conceded,
                overs,
                date,
                fmt,
                teams,
                country,
            ) in rows.iterator(chunk_size=5000):

                ts = tuple(
                    t.strip()
                    for t in teams.split(" vs ")
                    if t.strip()
                ) if teams else ()

                if len(ts) != 2 or country not in ts:
                    continue

                match_teams.setdefault(match_id, ts)

                perfs.append({
                    "id": performance_id,
                    "pid": player_id,
                    "mid": match_id,
                    "team": country,
                    "date": date,
                    "raw": raw_from_stats(
                        runs,
                        balls,
                        wickets,
                        conceded,
                        overs,
                        fmt,
                    ),
                })

            settings = SETTINGS[cat]

            factors = opposition_factors(
                perfs,
                match_teams,
                match_lineups,
                window=settings["window"],
                prior_w=settings["prior_w"],
            )

            objs = [
                Performance(id=performance_id, opp_strength=factor)
                for performance_id, factor in factors.items()
            ]

            Performance.objects.bulk_update(
                objs,
                ["opp_strength"],
                batch_size=500,
            )

            total += len(objs)

            with_lineups = sum(
                bool(value)
                for value in match_lineups.values()
            )

            self.stdout.write(
                f"  {cat}: opposition strength updated for "
                f"{len(objs)} performances; "
                f"{with_lineups} matches have saved XIs"
            )

        return total

    def collect_records(self, today):
        self.stdout.write("Step 2/3: collecting player records")

        fixtures = defaultdict(list)

        for match in (
            Match.objects.filter(
                category__in=INTL_CATS
            )
            .exclude(teams="")
            .order_by("-date")
            .values("id", "category", "teams")
        ):
            for team in match["teams"].split(" vs "):
                team = team.strip()

                if team:
                    fixtures[(match["category"], team)].append(
                        match["id"]
                    )

        recs = []

        players = Player.objects.prefetch_related(
            "performances__match"
        ).all()

        for player in players:
            role = infer_role(player)

            if role and role != player.role:
                player.role = role
                player.save(update_fields=["role"])

            role_class = {
                "AR": "AR",
                "BOWL": "BOWL",
            }.get(player.role, "BAT")

            performances = list(
                player.performances.select_related("match")
                .order_by("-match__date")
            )

            by_cat = defaultdict(list)

            for performance in performances:
                category = performance.match.category

                if category:
                    by_cat[category].append(performance)

            for cat, all_cat in by_cat.items():

                buckets = {"": all_cat}

                if cat in GROUPS:
                    for performance in all_cat:
                        group = group_of(
                            cat,
                            performance.match.competition,
                        )

                        buckets.setdefault(group, []).append(
                            performance
                        )

                for group, items in buckets.items():

                    availability = 1.0

                    if cat in INTL_CATS and player.country:
                        team_matches = fixtures.get(
                            (cat, player.country),
                            [],
                        )[:LOOKBACK]

                        if team_matches:
                            played = {
                                performance.match_id
                                for performance in items
                            }

                            availability = (
                                sum(
                                    match_id in played
                                    for match_id in team_matches
                                )
                                / len(team_matches)
                            )

                    last = items[0].match.date

                    recs.append({
                        "player": player,
                        "pid": player.pk,
                        "cat": cat,
                        "group": group,
                        "items": items,
                        "n": len(items),
                        "last": last,
                        "rc": role_class,
                        "rating": rating_of(items, cat),
                        "quality": quality_score(items, cat),
                        "consistency": consistency_score(items),
                        "level": recent_level(items, today),
                        "avail": availability,
                        "confidence": confidence_score(len(items)),
                        "scale": (
                            nation_scale(player.country)
                            if cat in INTL_CATS
                            else 1.0
                        ),
                        "active": (
                            today - last
                        ).days <= TAB_BY_KEY.get(
                            cat,
                            {"active_days": 365},
                        )["active_days"],
                    })

        return recs

    def calculate_scarcity(self, recs):
        role_counts = defaultdict(int)
        pool_counts = defaultdict(int)

        for record in recs:
            key = (
                record["cat"],
                record["group"],
            )

            role_counts[
                (
                    record["cat"],
                    record["group"],
                    record["rc"],
                )
            ] += 1

            pool_counts[key] += 1

        role_totals = defaultdict(int)
        role_kinds = defaultdict(int)

        for (cat, group, role), count in role_counts.items():
            role_totals[(cat, group)] += count
            role_kinds[(cat, group)] += 1

        for record in recs:
            key = (
                record["cat"],
                record["group"],
            )

            average = (
                role_totals[key]
                / max(1, role_kinds[key])
            )

            own_count = role_counts[
                (
                    record["cat"],
                    record["group"],
                    record["rc"],
                )
            ]

            record["scarcity"] = min(
                1.05,
                1.0 + (
                    max(0.0, average - own_count)
                    / max(1.0, average)
                ) * 0.05,
            )

    def calculate_form(self, recs):
        peers = defaultdict(list)

        for record in recs:
            record["tier"] = tier_of(
                record["cat"],
                record["n"],
                record["rating"],
                (0, 52, 76, 100),
                record["quality"],
            )

            record["eff"] = (
                record["level"]
                * (
                    0.90
                    + 0.10 * record["avail"]
                )
            )

        for record in recs:
            if record["active"] and record["avail"] >= 0.35:
                peers[
                    (
                        record["cat"],
                        record["group"],
                        record["rc"],
                    )
                ].append(record["eff"])

        for record in recs:
            pool = peers.get(
                (
                    record["cat"],
                    record["group"],
                    record["rc"],
                ),
                [],
            )

            if len(pool) < 5:
                pool = peers.get(
                    (
                        record["cat"],
                        record["group"],
                        "BAT",
                    ),
                    [],
                )

            record["form_pct"] = form_pct(
                record["eff"],
                pool,
            )

    def calculate_potential(self, record, today):
        player = record["player"]

        age = None

        if player.date_of_birth:
            age = (
                today - player.date_of_birth
            ).days / 365.2425

        automatic = (
            0.55 * record["quality"]
            + 0.30 * min(
                100.0,
                max(0.0, record["level"] * 1.5),
            )
            + 0.15 * experience_score(record["n"])
        )

        if age is not None and age <= 23:
            automatic += 5.0
        elif age is not None and age <= 27:
            automatic += 2.0

        potential = (
            player.potential_rating
            if player.potential_rating is not None
            else automatic
        )

        return max(
            0.0,
            min(100.0, float(potential)),
        )

    def calculate_price(self, record, today):
        player = record["player"]

        potential = self.calculate_potential(
            record,
            today,
        )

        valuation_quality = (
            0.85 * record["quality"]
            + 0.15 * potential
        )

        base_band = price_band_of(
            record["tier"],
            valuation_quality,
        )

        cv, created = CategoryValue.objects.get_or_create(
            player=player,
            category=record["cat"],
            group=record["group"],
        )

        locked = cv.locked

        if locked:
            # Never overwrite a manually locked starting price.
            base = float(cv.base_value)

        else:
            base = band_price(
                record["tier"],
                valuation_quality,
                (0, 52, 76, 100),
                record["scale"],
                record["n"],
                record["cat"],
                quality=valuation_quality,
                price_band=base_band,
                role_scarcity=record["scarcity"],
            )

        band_ceiling = ceiling_for(
            record["tier"],
            record["scale"],
            base,
            base_band,
            matches=record["n"],
        )

        if locked:
            # A manually locked price may intentionally be outside
            # the automatic price band. Preserve it.
            ceiling = max(base, band_ceiling)

        else:
            if base > band_ceiling:
                raise CommandError(
                    "Automatic base price exceeds its band ceiling: "
                    f"player={record['pid']}, "
                    f"category={record['cat']}, "
                    f"group={record['group']}, "
                    f"base={base}, "
                    f"ceiling={band_ceiling}, "
                    f"band={base_band}"
                )

            ceiling = band_ceiling

        total = final_price(
            base,
            record["form_pct"],
            ceiling,
            confidence=record["confidence"],
        )

        final_band = (
            "premium"
            if total >= 16.0
            else "balanced"
            if total >= 8.0
            else "value"
        )

        cv.tier = record["tier"]
        cv.rating = round(record["rating"], 2)
        cv.quality_score = round(record["quality"], 1)
        cv.potential_score = round(potential, 1)
        cv.consistency_score = round(
            record["consistency"],
            1,
        )
        cv.confidence_score = record["confidence"]

        # This field represents the final auction-price band.
        cv.price_band = final_band

        cv.ceiling = round(ceiling, 2)
        cv.base_value = Decimal(str(round(base, 2)))
        cv.form_score = round(
            record["form_pct"],
            1,
        )
        cv.form_premium = Decimal(
            str(round(total - base, 2))
        )

        cv.matches = record["n"]
        cv.last_played = record["last"]

        cv.save()

        return {
            "created": created,
            "locked": locked,
            "base_band": base_band,
            "final_band": final_band,
            "base": base,
            "total": total,
        }

    def handle(self, *args, **opts):
        today = dt.date.today()

        self.stdout.write(
            "Step 1/3: opposition strength"
        )

        self.opposition()

        recs = self.collect_records(today)

        self.stdout.write(
            "Step 3/3: independent class, form and price calculations"
        )

        self.calculate_scarcity(recs)
        self.calculate_form(recs)

        updated = 0
        locked_count = 0
        created_count = 0
        category_counts = defaultdict(int)

        for record in recs:
            result = self.calculate_price(
                record,
                today,
            )

            updated += 1
            locked_count += int(result["locked"])
            created_count += int(result["created"])

            category_counts[record["cat"]] += 1

        self.stdout.write("\n========== RECALCULATION SUMMARY ==========")

        for category, count in sorted(category_counts.items()):
            self.stdout.write(
                f"{category}: {count} category values"
            )

        self.stdout.write(
            f"Updated category values: {updated}"
        )

        self.stdout.write(
            f"Locked values preserved: {locked_count}"
        )

        self.stdout.write(
            f"New category values created: {created_count}"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Recalculated {len({r['pid'] for r in recs})} "
                f"players and {updated} category values."
            )
        )
<<<<<<< HEAD

        from players.intel_data import clear_cache
        clear_cache()
        self.stdout.write("Cleared cached player pools and discovery analysis.")
=======
>>>>>>> 32c894519d1d3703c8124559016ca18af8eb90d6
