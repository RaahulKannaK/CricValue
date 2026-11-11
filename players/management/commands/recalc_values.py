import datetime as dt
import math
import statistics
from bisect import bisect_left
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from players.categories import GROUPS, TAB_BY_KEY, group_of
from players.models import CategoryValue, Match, Performance, Player
from players.strength import nation_scale, normalize_name
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
    impact as valuation_impact,
    freshness,
    experience_score,
    confidence_score,
    FORM_CAP,
    FORM_SOFTNESS,
)

LOOKBACK = 8
BATCH_SIZE = 2000
OPPOSITION_BATCH_SIZE = 3000
XI_HISTORY_WINDOW = 30
XI_PRIOR_WEIGHT = 8.0
XI_PRIOR = 20.0
COUNTRY_PRIOR_WEIGHT = 0.40
FACTOR_MIN = 0.65
FACTOR_MAX = 1.25
DEFAULT_REFERENCE = 25.0

CV_UPDATE_FIELDS = [
    "tier",
    "rating",
    "quality_score",
    "potential_score",
    "consistency_score",
    "confidence_score",
    "price_band",
    "ceiling",
    "base_value",
    "form_score",
    "form_premium",
    "matches",
    "last_played",
]


class Command(BaseCommand):
    help = (
        "Fast recalculation of opposition strength, player quality, "
        "form, confidence, tiers and category prices."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--base",
            action="store_true",
            help="Compatibility flag; locked manual values remain locked.",
        )

    # A short-lived per-player cache avoids recalculating the same match impact
    # for rating, quality, consistency and recent level without retaining every
    # Performance model instance for the whole command.
    def _impact(self, performance):
        cache = self._impact_cache
        key = performance.pk
        if key not in cache:
            cache[key] = valuation_impact(performance)
        return cache[key]

    @staticmethod
    def _infer_role_from_loaded(items):
        """Exact infer_role() logic, using already-loaded performances."""
        recent = items[:40]
        if len(recent) < 5:
            return None
        bat = sum(1 for p in recent if p.balls >= 8) / len(recent)
        bowl = sum(1 for p in recent if p.overs >= 2) / len(recent)
        if bat >= 0.35 and bowl >= 0.35:
            return "AR"
        return "BOWL" if bowl >= 0.35 else "BAT"

    def _consistency(self, items, window=30):
        values = [self._impact(p) for p in items[:window]]
        if len(values) < 3:
            return 50.0
        avg = sum(values) / len(values)
        if avg <= 0:
            return 0.0
        deviation = statistics.pstdev(values)
        cv = deviation / max(avg, 1.0)
        return max(0.0, min(100.0, 100.0 - cv * 55.0))

    def _rating(self, items, cat):
        settings = SETTINGS.get(cat, SETTINGS["T20"])
        values = [self._impact(p) for p in items[:settings["window"]]]
        if not values:
            return 20.0
        count = len(values)
        average = sum(values) / count
        return (
            count * average + settings["prior_w"] * 20.0
        ) / (count + settings["prior_w"])

    def _quality(self, items, cat):
        if not items:
            return 0.0
        settings = SETTINGS.get(cat, SETTINGS["T20"])
        career = [self._impact(p) for p in items[:settings["window"]]]
        medium = [self._impact(p) for p in items[:15]]
        career_avg = sum(career) / len(career) if career else 20.0
        medium_avg = sum(medium) / len(medium) if medium else 20.0
        consistency = self._consistency(items)
        score = (
            0.60 * career_avg
            + 0.25 * medium_avg
            + 0.15 * consistency
        )
        sample_factor = min(1.0, len(items) / 20.0)
        score = 50.0 + (score - 50.0) * sample_factor
        return round(max(0.0, min(100.0, score)), 2)

    def _recent_level(self, items, today):
        if not items:
            return 0.0
        # The original function only uses the first 30 values (5 + 10 + 15).
        values = [self._impact(p) for p in items[:30]]
        blended = 0.0
        used = 0.0
        for start, end, weight in ((0, 5, 0.50), (5, 15, 0.30), (15, 30, 0.20)):
            sample = values[start:end]
            if sample:
                blended += (sum(sample) / len(sample)) * weight
                used += weight
        blended = blended / used if used else 20.0
        fresh = freshness(items[0].match.date, today)
        return 20.0 + (blended - 20.0) * fresh

    @staticmethod
    def _fast_opposition_factors(perfs, match_teams, lineups, fallback_ref=DEFAULT_REFERENCE):
        """Same opposition formula as players.engine, with O(1) history means."""
        if not perfs:
            return {}

        by_player = defaultdict(list)
        match_dates = {}
        for perf in perfs:
            by_player[int(perf["pid"])].append(perf)
            match_dates[perf["mid"]] = perf["date"]

        dates_by_player = {}
        prefix_by_player = {}
        career_averages = []

        for player_id, rows in by_player.items():
            rows.sort(key=lambda row: (row["date"], row["id"]))
            dates = [row["date"] for row in rows]
            values = [float(row["raw"]) for row in rows]
            dates_by_player[player_id] = dates
            prefix = [0.0]
            running = 0.0
            for value in values:
                running += value
                prefix.append(running)
            prefix_by_player[player_id] = prefix
            if len(rows) >= 8:
                career_averages.append(statistics.mean(values))

        if career_averages:
            ordered = sorted(career_averages)
            index = round((len(ordered) - 1) * 0.85)
            reference = ordered[index]
        else:
            reference = fallback_ref
        reference = max(10.0, float(reference or fallback_ref))

        nation_cache = {}

        def country_scale(team):
            value = nation_cache.get(team)
            if value is None:
                value = nation_scale(team)
                nation_cache[team] = value
            return value

        def historical_quality(player_id, match_date):
            dates = dates_by_player.get(player_id, ())
            if match_date is None or not dates:
                return XI_PRIOR
            end = bisect_left(dates, match_date)
            start = max(0, end - XI_HISTORY_WINDOW)
            count = end - start
            if count <= 0:
                return XI_PRIOR
            prefix = prefix_by_player[player_id]
            sample_mean = (prefix[end] - prefix[start]) / count
            return (
                count * sample_mean + XI_PRIOR_WEIGHT * XI_PRIOR
            ) / (count + XI_PRIOR_WEIGHT)

        side_strength = {}
        for mid, teams in match_teams.items():
            date = match_dates.get(mid)
            match_lineups = lineups.get(mid) or {}
            normalised_lineups = {}
            for team, ids in match_lineups.items():
                selected_ids = []
                for player_id in (ids or []):
                    try:
                        selected_ids.append(int(player_id))
                    except (TypeError, ValueError):
                        continue
                normalised_lineups[normalize_name(team)] = selected_ids
            for team in teams:
                team_key = normalize_name(team)
                selected = normalised_lineups.get(team_key, [])
                if selected and date is not None:
                    qualities = [historical_quality(pid, date) for pid in selected]
                    xi_quality = (sum(qualities) / len(qualities)) / reference
                    xi_quality = max(0.25, min(1.35, xi_quality))
                    country_prior = country_scale(team)
                    blended = (
                        COUNTRY_PRIOR_WEIGHT * country_prior
                        + (1.0 - COUNTRY_PRIOR_WEIGHT) * xi_quality
                    )
                else:
                    blended = country_scale(team)
                side_strength[(mid, team_key)] = max(0.25, min(1.35, blended))

        result = {}
        for perf in perfs:
            teams = match_teams.get(perf["mid"]) or ()
            own_team = normalize_name(perf["team"])
            opponent = next(
                (team for team in teams if normalize_name(team) != own_team),
                None,
            )
            if opponent is None:
                factor = 1.0
            else:
                opponent_key = normalize_name(opponent)
                strength = side_strength.get(
                    (perf["mid"], opponent_key), country_scale(opponent)
                )
                factor = 0.55 + 0.65 * strength
                factor = max(FACTOR_MIN, min(FACTOR_MAX, factor))
            result[perf["id"]] = round(factor, 3)
        return result

    def opposition(self):
        total = 0
        for cat in INTL_CATS:
            self.stdout.write(f"  Processing opposition: {cat}")
            rows = Performance.objects.filter(
                match__category=cat
            ).values_list(
                "id", "player_id", "match_id", "runs", "balls", "wickets",
                "runs_conceded", "overs", "match__date", "match__fmt",
                "match__teams", "player__country",
            )

            perfs = []
            match_teams = {}
            match_lineups = {}

            for match in Match.objects.filter(category=cat).values(
                "id", "teams", "lineups"
            ).iterator(chunk_size=5000):
                teams = tuple(
                    team.strip()
                    for team in (match["teams"] or "").split(" vs ")
                    if team.strip()
                )
                if len(teams) == 2:
                    match_teams[match["id"]] = teams
                    match_lineups[match["id"]] = match.get("lineups") or {}

            for (
                performance_id, player_id, match_id, runs, balls, wickets,
                conceded, overs, date, fmt, teams, country,
            ) in rows.iterator(chunk_size=10000):
                teams = tuple(
                    team.strip() for team in (teams or "").split(" vs ") if team.strip()
                )
                if len(teams) != 2 or country not in teams:
                    continue
                match_teams.setdefault(match_id, teams)
                perfs.append({
                    "id": performance_id,
                    "pid": player_id,
                    "mid": match_id,
                    "team": country,
                    "date": date,
                    "raw": raw_from_stats(runs, balls, wickets, conceded, overs, fmt),
                })

            factors = self._fast_opposition_factors(
                perfs,
                match_teams,
                match_lineups,
            )
            objs = [
                Performance(id=performance_id, opp_strength=factor)
                for performance_id, factor in factors.items()
            ]
            Performance.objects.bulk_update(
                objs,
                ["opp_strength"],
                batch_size=OPPOSITION_BATCH_SIZE,
            )
            total += len(objs)
            with_lineups = sum(bool(value) for value in match_lineups.values())
            self.stdout.write(
                f"  {cat}: {len(objs)} performances updated; "
                f"{with_lineups} matches have saved XIs"
            )
        self.stdout.write(f"Opposition strength updated: {total}")
        return total

    def collect_records(self, today):
        self.stdout.write("Step 2/3: collecting player records")

        fixtures = defaultdict(list)
        for match in (
            Match.objects.filter(category__in=INTL_CATS)
            .exclude(teams="")
            .order_by("-date")
            .values("id", "category", "teams")
            .iterator(chunk_size=10000)
        ):
            for team in (match["teams"] or "").split(" vs "):
                team = team.strip()
                if team:
                    fixtures[(match["category"], team)].append(match["id"])

        players = list(
            Player.objects.only(
                "id", "country", "role", "date_of_birth", "potential_rating"
            ).order_by("pk").iterator(chunk_size=5000)
        )
        self.stdout.write(f"  Loaded {len(players)} players")

        self._impact_cache = {}
        performance_qs = (
            Performance.objects.select_related("match")
            .order_by("player_id", "-match__date", "-id")
        )
        performance_iter = iter(performance_qs.iterator(chunk_size=10000))
        current_performance = next(performance_iter, None)

        recs = []
        changed_players = []
        for player_index, player in enumerate(players, 1):
            # Consume this player's rows from the single ordered DB cursor.
            while (
                current_performance is not None
                and current_performance.player_id < player.pk
            ):
                current_performance = next(performance_iter, None)

            all_performances = []
            while (
                current_performance is not None
                and current_performance.player_id == player.pk
            ):
                all_performances.append(current_performance)
                current_performance = next(performance_iter, None)

            inferred = self._infer_role_from_loaded(all_performances)
            if inferred and inferred != player.role:
                player.role = inferred
                changed_players.append(player)

            role_class = {"AR": "AR", "BOWL": "BOWL"}.get(player.role, "BAT")
            by_cat = defaultdict(list)
            for performance in all_performances:
                category = performance.match.category
                if category:
                    by_cat[category].append(performance)

            for cat, all_cat in by_cat.items():
                buckets = {"": all_cat}
                if cat in GROUPS:
                    for performance in all_cat:
                        group = group_of(cat, performance.match.competition)
                        buckets.setdefault(group, []).append(performance)

                for group, items in buckets.items():
                    availability = 1.0
                    if cat in INTL_CATS and player.country:
                        team_matches = fixtures.get((cat, player.country), [])[:LOOKBACK]
                        if team_matches:
                            played_ids = {p.match_id for p in items}
                            availability = (
                                sum(match_id in played_ids for match_id in team_matches)
                                / len(team_matches)
                            )

                    last = items[0].match.date
                    recs.append({
                        "player": player,
                        "pid": player.pk,
                        "cat": cat,
                        "group": group,
                        "n": len(items),
                        "last": last,
                        "rc": role_class,
                        "rating": self._rating(items, cat),
                        "quality": self._quality(items, cat),
                        "consistency": self._consistency(items),
                        "level": self._recent_level(items, today),
                        "avail": availability,
                        "confidence": confidence_score(len(items)),
                        "scale": nation_scale(player.country) if cat in INTL_CATS else 1.0,
                        "active": (today - last).days <= TAB_BY_KEY.get(
                            cat, {"active_days": 365}
                        )["active_days"],
                    })

            # Every player's performances have now been reduced to scalar
            # record values, so release model objects and cached impacts.
            self._impact_cache.clear()

            if player_index % 1000 == 0:
                self.stdout.write(
                    f"  Processed {player_index}/{len(players)} players; "
                    f"{len(recs)} records collected"
                )

        if changed_players:
            Player.objects.bulk_update(
                changed_players,
                ["role"],
                batch_size=BATCH_SIZE,
            )
        self.stdout.write(
            f"  Player records collected: {len(recs)}; "
            f"roles corrected: {len(changed_players)}"
        )
        return recs

    def calculate_scarcity(self, recs):
        role_counts = defaultdict(int)
        for record in recs:
            role_counts[(record["cat"], record["group"], record["rc"])] += 1

        role_totals = defaultdict(int)
        role_kinds = defaultdict(int)
        for (cat, group, role), count in role_counts.items():
            role_totals[(cat, group)] += count
            role_kinds[(cat, group)] += 1

        for record in recs:
            key = (record["cat"], record["group"])
            average = role_totals[key] / max(1, role_kinds[key])
            own_count = role_counts[(record["cat"], record["group"], record["rc"])]
            record["scarcity"] = min(
                1.05,
                1.0 + (
                    max(0.0, average - own_count) / max(1.0, average)
                ) * 0.05,
            )

    def calculate_form(self, recs):
        peers = defaultdict(list)
        for record in recs:
            record["tier"] = tier_of(
                record["cat"], record["n"], record["rating"],
                (0, 52, 76, 100), record["quality"],
            )
            record["eff"] = record["level"] * (0.90 + 0.10 * record["avail"])

        for record in recs:
            if record["active"] and record["avail"] >= 0.35:
                peers[(record["cat"], record["group"], record["rc"])].append(record["eff"])

        peer_stats = {}
        for key, pool in peers.items():
            if len(pool) >= 5:
                peer_stats[key] = (
                    statistics.median(pool),
                    max(statistics.pstdev(pool), 3.0),
                )

        for record in recs:
            key = (record["cat"], record["group"], record["rc"])
            stats = peer_stats.get(key)
            if stats is None:
                stats = peer_stats.get((record["cat"], record["group"], "BAT"))
            if stats is None:
                record["form_pct"] = 0.0
            else:
                median, deviation = stats
                value = FORM_CAP * math.tanh(
                    (record["eff"] - median) / deviation / FORM_SOFTNESS
                )
                record["form_pct"] = max(-FORM_CAP, min(FORM_CAP, value))

    def calculate_potential(self, record, today):
        player = record["player"]
        age = None
        if player.date_of_birth:
            age = (today - player.date_of_birth).days / 365.2425
        automatic = (
            0.55 * record["quality"]
            + 0.30 * min(100.0, max(0.0, record["level"] * 1.5))
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
        return max(0.0, min(100.0, float(potential)))

    def calculate_price(self, record, today, cv):
        player = record["player"]
        potential = self.calculate_potential(record, today)
        valuation_quality = 0.85 * record["quality"] + 0.15 * potential
        base_band = price_band_of(record["tier"], valuation_quality)
        locked = cv.locked

        if locked:
            base = float(cv.base_value)
        else:
            base = band_price(
                record["tier"], valuation_quality, (0, 52, 76, 100),
                record["scale"], record["n"], record["cat"],
                quality=valuation_quality, price_band=base_band,
                role_scarcity=record["scarcity"],
            )

        band_ceiling = ceiling_for(
            record["tier"], record["scale"], base, base_band,
            matches=record["n"],
        )
        if locked:
            ceiling = max(base, band_ceiling)
        else:
            if base > band_ceiling:
                raise CommandError(
                    "Automatic base price exceeds its band ceiling: "
                    f"player={record['pid']}, category={record['cat']}, "
                    f"group={record['group']}, base={base}, "
                    f"ceiling={band_ceiling}, band={base_band}"
                )
            ceiling = band_ceiling

        total = final_price(
            base, record["form_pct"], ceiling,
            confidence=record["confidence"],
        )
        final_band = "premium" if total >= 16.0 else "balanced" if total >= 8.0 else "value"

        cv.tier = record["tier"]
        cv.rating = round(record["rating"], 2)
        cv.quality_score = round(record["quality"], 1)
        cv.potential_score = round(potential, 1)
        cv.consistency_score = round(record["consistency"], 1)
        cv.confidence_score = record["confidence"]
        cv.price_band = final_band
        cv.ceiling = round(ceiling, 2)
        cv.base_value = Decimal(str(round(base, 2)))
        cv.form_score = round(record["form_pct"], 1)
        cv.form_premium = Decimal(str(round(total - base, 2)))
        cv.matches = record["n"]
        cv.last_played = record["last"]
        return {"locked": locked, "base_band": base_band, "final_band": final_band}

    def save_category_values(self, recs, today):
        self.stdout.write("  Loading existing category values")
        existing = {}
        for cv in CategoryValue.objects.all().iterator(chunk_size=10000):
            existing[(cv.player_id, cv.category, cv.group)] = cv

        to_create = []
        to_update = []
        locked_count = 0
        created_count = 0
        updated_count = 0
        category_counts = defaultdict(int)

        def flush_create():
            nonlocal created_count
            if to_create:
                CategoryValue.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
                created_count += len(to_create)
                to_create.clear()

        def flush_update():
            nonlocal updated_count
            if to_update:
                CategoryValue.objects.bulk_update(
                    to_update, CV_UPDATE_FIELDS, batch_size=BATCH_SIZE
                )
                updated_count += len(to_update)
                to_update.clear()

        for record in recs:
            key = (record["pid"], record["cat"], record["group"])
            cv = existing.get(key)
            is_new = cv is None
            if is_new:
                cv = CategoryValue(
                    player_id=record["pid"],
                    category=record["cat"],
                    group=record["group"],
                )
                existing[key] = cv
            result = self.calculate_price(record, today, cv)
            locked_count += int(result["locked"])
            category_counts[record["cat"]] += 1
            if is_new:
                to_create.append(cv)
            else:
                to_update.append(cv)

            if len(to_create) >= BATCH_SIZE:
                flush_create()
            if len(to_update) >= BATCH_SIZE:
                flush_update()

        flush_create()
        flush_update()
        return updated_count + created_count, locked_count, created_count, category_counts

    def handle(self, *args, **opts):
        today = dt.date.today()
        self.stdout.write(self.style.SUCCESS("Starting optimized CricValue recalculation"))
        self.stdout.write("Step 1/3: opposition strength")
        self.opposition()

        recs = self.collect_records(today)
        self.stdout.write("Step 3/3: independent class, form and price calculations")
        self.calculate_scarcity(recs)
        self.calculate_form(recs)

        self.stdout.write("  Saving category values in batches")
        with transaction.atomic():
            updated, locked_count, created_count, category_counts = (
                self.save_category_values(recs, today)
            )

        self.stdout.write("\n========== RECALCULATION SUMMARY ==========")
        for category, count in sorted(category_counts.items()):
            self.stdout.write(f"{category}: {count} category values")
        self.stdout.write(f"Updated category values: {updated}")
        self.stdout.write(f"Locked values preserved: {locked_count}")
        self.stdout.write(f"New category values created: {created_count}")
        self.stdout.write(self.style.SUCCESS(
            f"Recalculated {len({r['pid'] for r in recs})} players "
            f"and {updated} category values."
        ))
