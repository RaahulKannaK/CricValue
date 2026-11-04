"""Pre-match opposition strength using historical player quality."""

from bisect import bisect_left
from collections import defaultdict
from statistics import mean

from .strength import nation_scale, normalize_name

FACTOR_MIN = 0.65
FACTOR_MAX = 1.25

COUNTRY_PRIOR_WEIGHT = 0.40

XI_HISTORY_WINDOW = 30
XI_PRIOR_WEIGHT = 8.0
XI_PRIOR = 20.0

DEFAULT_REFERENCE = 25.0


def _percentile(values, fraction):
    values = sorted(values)

    if not values:
        return DEFAULT_REFERENCE

    index = round((len(values) - 1) * fraction)

    return values[index]


def _normalise_lineup(lineup):
    """
    Accept either integer or string player IDs.
    """

    result = []

    for player_id in lineup or []:
        try:
            result.append(int(player_id))
        except (TypeError, ValueError):
            continue

    return result


def opposition_factors(
    perfs,
    match_teams,
    lineups=None,
    window=40,
    prior_w=12.0,
    prior=20.0,
    iterations=2,
    vip_pct=0.85,
    fallback_ref=DEFAULT_REFERENCE,
):
    """
    Calculate the strength of the opposition faced by each performance.

    perfs:
        List of dictionaries containing:
        id, pid, mid, team, raw, date

    match_teams:
        {match_id: (team1, team2)}

    lineups:
        {
            match_id: {
                team_name: [player_id, ...]
            }
        }

    Returns:
        {performance_id: opposition_factor}
    """

    if not perfs:
        return {}

    lineups = lineups or {}

    by_player = defaultdict(list)
    match_dates = {}

    for perf in perfs:
        player_id = int(perf["pid"])

        by_player[player_id].append(perf)
        match_dates[perf["mid"]] = perf["date"]

    for rows in by_player.values():
        rows.sort(
            key=lambda row: (row["date"], row["id"])
        )

    # Historical performance arrays.
    dates_by_player = {}
    raw_by_player = {}

    for player_id, rows in by_player.items():
        dates_by_player[player_id] = [
            row["date"] for row in rows
        ]

        raw_by_player[player_id] = [
            float(row["raw"])
            for row in rows
        ]

    # Establish a reference level from established players.
    career_averages = []

    for rows in by_player.values():
        if len(rows) >= 8:
            career_averages.append(
                mean(float(row["raw"]) for row in rows)
            )

    reference = _percentile(
        career_averages,
        vip_pct,
    ) if career_averages else fallback_ref

    reference = max(10.0, float(reference or fallback_ref))

    def historical_player_quality(player_id, match_date):
        dates = dates_by_player.get(player_id, [])
        values = raw_by_player.get(player_id, [])

        if match_date is None or not dates:
            return XI_PRIOR

        # Exclude the current match and same-day performances.
        end = bisect_left(dates, match_date)

        sample = values[
            max(0, end - XI_HISTORY_WINDOW):end
        ]

        if not sample:
            return XI_PRIOR

        sample_mean = mean(sample)

        # Shrink small histories toward a neutral prior.
        return (
            len(sample) * sample_mean
            + XI_PRIOR_WEIGHT * XI_PRIOR
        ) / (
            len(sample) + XI_PRIOR_WEIGHT
        )

    # Canonical team lookup.
    canonical_teams = {}

    for mid, teams in match_teams.items():
        canonical_teams[mid] = tuple(
            normalize_name(team)
            for team in teams
        )

    # Evaluate each side before the match.
    side_strength = {}

    for mid, teams in match_teams.items():
        date = match_dates.get(mid)
        match_lineups = lineups.get(mid) or {}

        normalised_lineups = {
            normalize_name(team): _normalise_lineup(ids)
            for team, ids in match_lineups.items()
        }

        for team in teams:
            team_key = normalize_name(team)

            selected = normalised_lineups.get(
                team_key, []
            )

            if selected and date is not None:
                qualities = [
                    historical_player_quality(pid, date)
                    for pid in selected
                ]

                xi_quality = mean(qualities) / reference

                xi_quality = max(
                    0.25,
                    min(1.35, xi_quality),
                )

                country_prior = nation_scale(team)

                blended = (
                    COUNTRY_PRIOR_WEIGHT * country_prior
                    + (1.0 - COUNTRY_PRIOR_WEIGHT) * xi_quality
                )

            else:
                # No XI: explicitly use country-level evidence.
                blended = nation_scale(team)

            side_strength[(mid, team_key)] = max(
                0.25,
                min(1.35, blended),
            )

    def opponent_factor(perf):
        teams = match_teams.get(perf["mid"]) or ()

        own_team = normalize_name(perf["team"])

        opponent = next(
            (
                team for team in teams
                if normalize_name(team) != own_team
            ),
            None,
        )

        if opponent is None:
            return 1.0

        opponent_key = normalize_name(opponent)

        strength = side_strength.get(
            (perf["mid"], opponent_key),
            nation_scale(opponent),
        )

        # 1.0 represents an average international challenge.
        # Stronger opposition increases performance credit.
        factor = 0.55 + 0.65 * strength

        return max(
            FACTOR_MIN,
            min(FACTOR_MAX, factor),
        )

    return {
        perf["id"]: round(opponent_factor(perf), 3)
        for perf in perfs
    }