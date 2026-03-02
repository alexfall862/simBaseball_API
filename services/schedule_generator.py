# services/schedule_generator.py
"""
Schedule generator for all league levels.

MLB:    162 games/team, 52 weeks (1 bye), divisional/intraleague/interleague/rivalry
MiLB:   120 games/team, ~34 weeks, round-robin, configurable start_week
College: 50 games/team, ~14 weeks, conference round-robin + OOC, starts week 1
"""

import logging
import random
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import MetaData, Table, select, delete, and_, text, func

log = logging.getLogger("app")

# ── Level IDs ───────────────────────────────────────────────────────────
LEVEL_MLB = 9
LEVEL_AAA = 8
LEVEL_AA = 7
LEVEL_HIGHA = 6
LEVEL_A = 5
LEVEL_SCRAPS = 4
LEVEL_COLLEGE = 3
MINOR_LEVELS = (LEVEL_AAA, LEVEL_AA, LEVEL_HIGHA, LEVEL_A, LEVEL_SCRAPS)

LEVEL_NAMES = {
    9: "MLB", 8: "AAA", 7: "AA", 6: "High-A", 5: "A",
    4: "Scraps", 3: "College", 2: "INTAM", 1: "HS",
}

# ── MLB constants ───────────────────────────────────────────────────────
MLB_TOTAL_WEEKS = 52
MLB_GAMES_PER_TEAM = 162
MLB_SERIES_PER_TEAM = 51  # 1 bye week out of 52
MLB_MAX_SERIES_PER_WEEK = 15  # 30 teams / 2
MLB_TOTAL_SERIES = 765

MLB_DIVISIONAL_GAMES = 52   # per team
MLB_INTRALEAGUE_GAMES = 64  # per team
MLB_INTERLEAGUE_GAMES = 44  # per team
MLB_RIVALRY_GAMES = 2       # per team

# Rivalry pairs: (team_abbrev, team_abbrev) — must match teams.team_abbrev
MLB_RIVALRY_PAIRS = [
    ("LAA", "LAD"),   # Angels-Dodgers
    ("HOU", "COL"),   # Astros-Rockies
    ("OAK", "SF"),    # Athletics-Giants
    ("TOR", "PHI"),   # Blue Jays-Phillies
    ("CLE", "CIN"),   # Guardians-Reds
    ("SEA", "SD"),    # Mariners-Padres
    ("BAL", "WAS"),   # Orioles-Nationals
    ("TEX", "ARI"),   # Rangers-Diamondbacks
    ("TB", "MIA"),    # Rays-Marlins
    ("BOS", "ATL"),   # Red Sox-Braves
    ("KC", "STL"),    # Royals-Cardinals
    ("DET", "PIT"),   # Tigers-Pirates
    ("MIN", "MIL"),   # Twins-Brewers
    ("CWS", "CHC"),   # White Sox-Cubs
    ("NYY", "NYM"),   # Yankees-Mets
]

# ── MiLB constants ──────────────────────────────────────────────────────
MILB_GAMES_PER_TEAM = 120
MILB_TEAMS_PER_LEVEL = 30

# ── College constants ───────────────────────────────────────────────────
COLLEGE_GAMES_PER_TEAM = 50

# ── Subweek labels ──────────────────────────────────────────────────────
SUBWEEK_LABELS = ["a", "b", "c", "d"]


# =====================================================================
# Table reflection (cached)
# =====================================================================
_tables_cache = None


def _get_tables(engine):
    global _tables_cache
    if _tables_cache is None:
        md = MetaData()
        _tables_cache = {
            "gamelist": Table("gamelist", md, autoload_with=engine),
            "game_results": Table("game_results", md, autoload_with=engine),
            "teams": Table("teams", md, autoload_with=engine),
            "seasons": Table("seasons", md, autoload_with=engine),
            "levels": Table("levels", md, autoload_with=engine),
        }
    return _tables_cache


def _row_to_dict(row):
    return dict(row._mapping)


# =====================================================================
# Data loading helpers
# =====================================================================

def _resolve_season_id(conn, tables, league_year: int) -> int:
    """Look up seasons.id for a given year. Raises ValueError if not found."""
    seasons = tables["seasons"]
    row = conn.execute(
        select(seasons.c.id).where(seasons.c.year == league_year)
    ).first()
    if not row:
        raise ValueError(
            "No season found for year %d. Check the seasons table." % league_year
        )
    return row[0]


def _load_mlb_teams(conn, tables) -> Dict[str, Any]:
    """
    Load all level-9 teams grouped by conference and division.

    Returns:
        {
            "by_conf_div": {"AL": {"East": [t, ...], ...}, "NL": {...}},
            "all": [t, ...],
            "by_id": {team_id: t, ...},
            "by_abbrev": {abbrev: t, ...},
        }
    """
    teams = tables["teams"]
    rows = conn.execute(
        select(teams).where(teams.c.team_level == LEVEL_MLB)
    ).all()

    all_teams = [_row_to_dict(r) for r in rows]
    by_conf_div = {}
    by_id = {}
    by_abbrev = {}

    for t in all_teams:
        conf = t.get("conference")
        div = t.get("division")
        tid = t["id"]
        abbrev = t.get("team_abbrev")

        by_conf_div.setdefault(conf, {}).setdefault(div, []).append(t)
        by_id[tid] = t
        if abbrev:
            by_abbrev[abbrev] = t

    return {
        "by_conf_div": by_conf_div,
        "all": all_teams,
        "by_id": by_id,
        "by_abbrev": by_abbrev,
    }


def _load_college_teams(conn, tables) -> Dict[str, List[Dict]]:
    """Load level-3 teams grouped by conference name."""
    teams = tables["teams"]
    rows = conn.execute(
        select(teams).where(teams.c.team_level == LEVEL_COLLEGE)
    ).all()

    by_conf = {}
    for r in rows:
        t = _row_to_dict(r)
        conf = t.get("conference") or "Independent"
        by_conf.setdefault(conf, []).append(t)
    return by_conf


def _load_minor_teams(conn, tables, level: int) -> List[Dict]:
    """Load all teams at the given minor league level."""
    teams = tables["teams"]
    rows = conn.execute(
        select(teams).where(teams.c.team_level == level)
    ).all()
    return [_row_to_dict(r) for r in rows]


# =====================================================================
# Validation
# =====================================================================

def validate_schedule_generation(
    conn, tables, season_id: int, league_level: int,
) -> Dict[str, Any]:
    """
    Check prerequisites for schedule generation.

    Returns: {"valid": bool, "errors": [...], "warnings": [...], "team_count": N, "existing_games": N}
    """
    gamelist = tables["gamelist"]
    teams_tbl = tables["teams"]

    errors = []
    warnings = []

    # Count teams at this level
    team_count = conn.execute(
        select(func.count()).select_from(teams_tbl).where(
            teams_tbl.c.team_level == league_level
        )
    ).scalar()

    if team_count == 0:
        errors.append("No teams found at level %d" % league_level)

    # MLB-specific checks
    if league_level == LEVEL_MLB:
        if team_count != 30:
            errors.append("MLB requires exactly 30 teams, found %d" % team_count)

        # Check conference/division structure
        rows = conn.execute(
            select(teams_tbl.c.conference, teams_tbl.c.division, func.count().label("cnt"))
            .where(teams_tbl.c.team_level == LEVEL_MLB)
            .group_by(teams_tbl.c.conference, teams_tbl.c.division)
        ).all()

        for r in rows:
            m = r._mapping
            if m["cnt"] != 5:
                errors.append(
                    "%s %s has %d teams (expected 5)" % (m["conference"], m["division"], m["cnt"])
                )

    # Check for existing games
    existing = conn.execute(
        select(func.count()).select_from(gamelist).where(
            and_(gamelist.c.season == season_id, gamelist.c.league_level == league_level)
        )
    ).scalar()

    if existing > 0:
        warnings.append(
            "%d games already exist for this season/level" % existing
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "team_count": team_count,
        "existing_games": existing,
    }


# =====================================================================
# Schedule report (cross-level, cross-season)
# =====================================================================

def schedule_report(conn, tables) -> Dict[str, Any]:
    """
    Summary of existing schedules across all levels and seasons.

    Returns: {"seasons": {year: {level: {"games": N, "weeks": "1-52"}, ...}}}
    """
    gamelist = tables["gamelist"]
    seasons = tables["seasons"]

    rows = conn.execute(text("""
        SELECT s.year, g.league_level,
               COUNT(*)                       AS games,
               COUNT(DISTINCT CONCAT(g.home_team, '-', g.season_week)) AS home_slots,
               MIN(g.season_week)             AS min_week,
               MAX(g.season_week)             AS max_week,
               COUNT(DISTINCT g.home_team)    AS home_teams,
               COUNT(DISTINCT g.away_team)    AS away_teams
        FROM gamelist g
        JOIN seasons s ON s.id = g.season
        GROUP BY s.year, g.league_level
        ORDER BY s.year, g.league_level
    """)).all()

    result = {}
    for r in rows:
        m = r._mapping
        year = str(m["year"])
        level = m["league_level"]
        result.setdefault(year, {})[level] = {
            "level_name": LEVEL_NAMES.get(level, "Level %d" % level),
            "games": m["games"],
            "weeks": "%d-%d" % (m["min_week"], m["max_week"]),
            "teams": max(m["home_teams"], m["away_teams"]),
        }

    return {"seasons": result}


# =====================================================================
# Clear existing schedule
# =====================================================================

def _clear_existing_schedule(conn, tables, season_id: int, league_level: int) -> int:
    """Delete gamelist + game_results for a season/level. Returns deleted game count."""
    gamelist = tables["gamelist"]

    # Get game IDs
    ids = [r[0] for r in conn.execute(
        select(gamelist.c.id).where(and_(
            gamelist.c.season == season_id,
            gamelist.c.league_level == league_level,
        ))
    ).all()]

    if not ids:
        return 0

    # Build parameterized IN clause
    ph = ", ".join(":g%d" % i for i in range(len(ids)))
    params = {"g%d" % i: gid for i, gid in enumerate(ids)}

    # Delete game_results first (FK to gamelist)
    conn.execute(text("DELETE FROM game_results WHERE game_id IN (%s)" % ph), params)

    # Delete gamelist rows
    conn.execute(text("DELETE FROM gamelist WHERE id IN (%s)" % ph), params)

    log.info("schedule: cleared %d games for season_id=%d level=%d", len(ids), season_id, league_level)
    return len(ids)


# =====================================================================
# MLB matchup pool builder
# =====================================================================

def _build_mlb_matchup_pool(
    teams_data: Dict[str, Any],
    rng: random.Random,
) -> List[Dict]:
    """
    Build all 765 unique series for an MLB season.

    Returns list of series dicts:
        {"team_a": id, "team_b": id, "length": 2|3|4, "category": str}
    """
    by_conf_div = teams_data["by_conf_div"]
    by_abbrev = teams_data["by_abbrev"]

    # ── Resolve rivalry pairs to IDs ─────────────────────────────────
    rivalry_set = set()  # frozensets of (id_a, id_b)
    rivalry_by_team = {}  # team_id → rival_team_id
    for abbrev_a, abbrev_b in MLB_RIVALRY_PAIRS:
        ta = by_abbrev.get(abbrev_a)
        tb = by_abbrev.get(abbrev_b)
        if not ta:
            raise ValueError("Rivalry: team_abbrev '%s' not found in DB" % abbrev_a)
        if not tb:
            raise ValueError("Rivalry: team_abbrev '%s' not found in DB" % abbrev_b)
        pair = frozenset([ta["id"], tb["id"]])
        rivalry_set.add(pair)
        rivalry_by_team[ta["id"]] = tb["id"]
        rivalry_by_team[tb["id"]] = ta["id"]

    all_series = []

    # ── Divisional: 60 pairs × 4 series each ────────────────────────
    # Each pair plays 13 games = [3, 3, 3, 4]
    for conf in by_conf_div:
        for div in by_conf_div[conf]:
            div_teams = by_conf_div[conf][div]
            for ta, tb in combinations(div_teams, 2):
                for length in [3, 3, 3, 4]:
                    all_series.append({
                        "team_a": ta["id"],
                        "team_b": tb["id"],
                        "length": length,
                        "category": "divisional",
                    })

    # ── Intraleague non-division: 150 pairs × 2 series each ─────────
    # 64 games per team from 10 opponents, 2 series per opponent.
    # Need 4 four-game + 16 three-game series per team (20 total).
    # Per pair: some get [3,4] (7 games), some get [3,3] (6 games).
    # Across 10 opponents: 4×7 + 6×6 = 28+36 = 64. ✓
    for conf in by_conf_div:
        divisions = list(by_conf_div[conf].keys())
        for i, div_a in enumerate(divisions):
            for div_b in divisions[i + 1:]:
                for ta in by_conf_div[conf][div_a]:
                    for tb in by_conf_div[conf][div_b]:
                        # Default [3, 3]; some will be upgraded to [3, 4] below
                        all_series.append({
                            "team_a": ta["id"],
                            "team_b": tb["id"],
                            "length": 3,
                            "category": "intraleague",
                        })
                        all_series.append({
                            "team_a": ta["id"],
                            "team_b": tb["id"],
                            "length": 3,
                            "category": "intraleague",
                        })

    # Upgrade some intraleague series from 3→4 to hit 64 games/team.
    # Each team needs exactly 4 of their 20 intraleague series to be 4-game.
    # That means each team goes from 20×3=60 → 16×3+4×4=64. ✓
    _upgrade_intraleague_series(all_series, teams_data, rng)

    # ── Interleague non-rival: 210 pairs × 1 series each ────────────
    # 44 games per team from 14 opponents (excluding rival).
    # 14 series per team: 12×3 + 2×4 = 36+8 = 44. ✓
    confs = list(by_conf_div.keys())
    if len(confs) != 2:
        raise ValueError("MLB requires exactly 2 conferences, found %d" % len(confs))

    conf_a_teams = []
    for div in by_conf_div[confs[0]].values():
        conf_a_teams.extend(div)
    conf_b_teams = []
    for div in by_conf_div[confs[1]].values():
        conf_b_teams.extend(div)

    for ta in conf_a_teams:
        for tb in conf_b_teams:
            pair = frozenset([ta["id"], tb["id"]])
            if pair in rivalry_set:
                continue  # rival handled separately
            all_series.append({
                "team_a": ta["id"],
                "team_b": tb["id"],
                "length": 3,  # default; some upgraded below
                "category": "interleague",
            })

    # Upgrade some interleague series from 3→4 to hit 44 games/team.
    # Each team needs 2 of their 14 interleague series to be 4-game.
    _upgrade_interleague_series(all_series, teams_data, rng)

    # ── Rivalry: 15 pairs × 1 series of 2 games ─────────────────────
    for pair in rivalry_set:
        ids = list(pair)
        all_series.append({
            "team_a": ids[0],
            "team_b": ids[1],
            "length": 2,
            "category": "rivalry",
        })

    # ── Validate totals ──────────────────────────────────────────────
    _validate_mlb_pool(all_series, teams_data)

    return all_series


def _upgrade_intraleague_series(
    all_series: List[Dict], teams_data: Dict, rng: random.Random
):
    """
    Upgrade intraleague 3-game series to 4-game so each team gets exactly
    4 four-game intraleague series (total 64 games from intraleague).

    Modifies series in-place.
    """
    # Collect indices of intraleague series
    intra_indices = [i for i, s in enumerate(all_series) if s["category"] == "intraleague"]

    # Count how many 4-game intraleague series each team already has
    team_4game = {}
    for t in teams_data["all"]:
        team_4game[t["id"]] = 0

    # Shuffle and greedily upgrade
    rng.shuffle(intra_indices)
    for idx in intra_indices:
        s = all_series[idx]
        if s["length"] == 4:
            continue
        a, b = s["team_a"], s["team_b"]
        if team_4game.get(a, 0) < 4 and team_4game.get(b, 0) < 4:
            s["length"] = 4
            team_4game[a] = team_4game.get(a, 0) + 1
            team_4game[b] = team_4game.get(b, 0) + 1


def _upgrade_interleague_series(
    all_series: List[Dict], teams_data: Dict, rng: random.Random
):
    """
    Upgrade interleague 3-game series to 4-game so each team gets exactly
    2 four-game interleague series (total 44 games from interleague).

    Modifies series in-place.
    """
    inter_indices = [i for i, s in enumerate(all_series) if s["category"] == "interleague"]

    team_4game = {}
    for t in teams_data["all"]:
        team_4game[t["id"]] = 0

    rng.shuffle(inter_indices)
    for idx in inter_indices:
        s = all_series[idx]
        if s["length"] == 4:
            continue
        a, b = s["team_a"], s["team_b"]
        if team_4game.get(a, 0) < 2 and team_4game.get(b, 0) < 2:
            s["length"] = 4
            team_4game[a] = team_4game.get(a, 0) + 1
            team_4game[b] = team_4game.get(b, 0) + 1


def _validate_mlb_pool(all_series: List[Dict], teams_data: Dict):
    """Assert that the matchup pool has the correct totals."""
    if len(all_series) != MLB_TOTAL_SERIES:
        raise RuntimeError(
            "Expected %d series, got %d" % (MLB_TOTAL_SERIES, len(all_series))
        )

    # Per-team game count
    team_games = {}
    for s in all_series:
        team_games[s["team_a"]] = team_games.get(s["team_a"], 0) + s["length"]
        team_games[s["team_b"]] = team_games.get(s["team_b"], 0) + s["length"]

    for t in teams_data["all"]:
        tid = t["id"]
        count = team_games.get(tid, 0)
        if count != MLB_GAMES_PER_TEAM:
            raise RuntimeError(
                "Team %s (%d) has %d games, expected %d"
                % (t.get("team_abbrev"), tid, count, MLB_GAMES_PER_TEAM)
            )

    log.info("schedule: MLB pool validated — %d series, 162 games/team", len(all_series))


# =====================================================================
# Home/Away balancing
# =====================================================================

def _balance_home_away(all_series: List[Dict], rng: random.Random) -> List[Dict]:
    """
    Assign home/away for each series. Replaces team_a/team_b with
    home_team/away_team. Modifies in-place and returns the list.

    Strategy:
    - Multi-series pairs: alternate home/away evenly.
    - Single-series pairs: assign home to team with fewer home games so far.
    """
    # Group series by pair
    pair_series = {}  # frozenset(a,b) → [series_indices]
    for i, s in enumerate(all_series):
        pair = frozenset([s["team_a"], s["team_b"]])
        pair_series.setdefault(pair, []).append(i)

    home_game_count = {}  # team_id → total home games so far

    def _add_home(tid, games):
        home_game_count[tid] = home_game_count.get(tid, 0) + games

    # Process multi-series pairs first (divisional=4, intraleague=2)
    for pair, indices in pair_series.items():
        if len(indices) < 2:
            continue
        ids = list(pair)
        rng.shuffle(ids)
        # Alternate: first half → ids[0] home, second half → ids[1] home
        for j, idx in enumerate(indices):
            s = all_series[idx]
            if j < len(indices) // 2:
                s["home_team"] = ids[0]
                s["away_team"] = ids[1]
                _add_home(ids[0], s["length"])
            else:
                s["home_team"] = ids[1]
                s["away_team"] = ids[0]
                _add_home(ids[1], s["length"])

    # Process single-series pairs (interleague + rivalry)
    single_indices = [
        idx for pair, indices in pair_series.items()
        if len(indices) == 1
        for idx in indices
    ]
    rng.shuffle(single_indices)

    for idx in single_indices:
        s = all_series[idx]
        a, b = s["team_a"], s["team_b"]
        a_home = home_game_count.get(a, 0)
        b_home = home_game_count.get(b, 0)

        if a_home <= b_home:
            s["home_team"] = a
            s["away_team"] = b
            _add_home(a, s["length"])
        else:
            s["home_team"] = b
            s["away_team"] = a
            _add_home(b, s["length"])

    return all_series


# =====================================================================
# Week assignment (constraint satisfaction)
# =====================================================================

def _assign_series_to_weeks(
    all_series: List[Dict],
    num_weeks: int,
    max_per_week: int,
    start_week: int = 1,
    rng: random.Random = None,
    max_attempts: int = 100,
) -> Dict[int, List[Dict]]:
    """
    Assign each series to a week such that:
    - Each week has at most max_per_week series
    - No team appears in more than one series per week

    Returns: {week_number: [series_dicts]}
    """
    if rng is None:
        rng = random.Random()

    end_week = start_week + num_weeks - 1
    weeks = list(range(start_week, end_week + 1))

    for attempt in range(max_attempts):
        series_list = list(all_series)
        rng.shuffle(series_list)

        week_slots = {w: [] for w in weeks}
        week_counts = {w: 0 for w in weeks}
        team_week_used = set()  # (team_id, week)

        success = True
        for s in series_list:
            home = s["home_team"]
            away = s["away_team"]

            candidates = [
                w for w in weeks
                if week_counts[w] < max_per_week
                and (home, w) not in team_week_used
                and (away, w) not in team_week_used
            ]

            if not candidates:
                success = False
                break

            # Weight toward emptier weeks for better convergence
            weights = [max_per_week - week_counts[w] + 1 for w in candidates]
            chosen = rng.choices(candidates, weights=weights, k=1)[0]

            week_slots[chosen].append(s)
            week_counts[chosen] += 1
            team_week_used.add((home, chosen))
            team_week_used.add((away, chosen))

        if success:
            log.info(
                "schedule: week assignment succeeded on attempt %d/%d",
                attempt + 1, max_attempts,
            )
            return week_slots

    raise RuntimeError(
        "Failed to assign %d series to %d weeks after %d attempts"
        % (len(all_series), num_weeks, max_attempts)
    )


# =====================================================================
# Subweek expansion → gamelist rows
# =====================================================================

def _expand_to_game_rows(
    week_assignments: Dict[int, List[Dict]],
    season_id: int,
    league_level: int,
) -> List[Dict]:
    """
    Expand series into individual gamelist rows.

    Each game in a series fills subweeks a, b, c, d sequentially.
    """
    rows = []
    for week_num in sorted(week_assignments.keys()):
        for s in week_assignments[week_num]:
            length = s["length"]
            for game_idx in range(length):
                rows.append({
                    "away_team": s["away_team"],
                    "home_team": s["home_team"],
                    "season_week": week_num,
                    "season_subweek": SUBWEEK_LABELS[game_idx],
                    "league_level": league_level,
                    "season": season_id,
                    "random_seed": None,
                })
    return rows


# =====================================================================
# Minor league matchup pool
# =====================================================================

def _build_minor_matchup_pool(
    all_teams: List[Dict],
    games_per_team: int,
    rng: random.Random,
) -> List[Dict]:
    """
    Build round-robin matchup pool for a minor league level.

    Each team plays games_per_team games in series of 3 and 4.
    Distributes series across all opponent pairs to stay balanced.
    """
    n = len(all_teams)
    if n < 2:
        raise ValueError("Need at least 2 teams, got %d" % n)

    # Total series per team = games_per_team / avg_series_length
    # We need to figure out how many series each pair plays.
    # With n teams, each team has n-1 opponents.
    # Total games from s series of avg length L: s * L = games_per_team
    # Pairs = C(n, 2). Total series across league = n * series_per_team / 2

    # Start with 1 series per pair, assign 3 or 4 to reach target
    pairs = list(combinations(range(n), 2))

    # Each team appears in n-1 pairs.
    # Start all at 3 games → each team gets (n-1)*3 games.
    # Need games_per_team - (n-1)*3 extra games distributed as upgrades to 4.
    base_games = (n - 1) * 3
    extra_needed = games_per_team - base_games

    if extra_needed < 0:
        raise ValueError(
            "Cannot fit %d games with %d opponents using series of 3 minimum"
            % (games_per_team, n - 1)
        )

    # Each upgrade adds 1 game to both teams. Need extra_needed upgrades per team,
    # but each upgrade touches 2 teams. Total upgrades = n * extra_needed / 2.
    total_upgrades = n * extra_needed // 2
    if total_upgrades > len(pairs):
        # Need multiple series per pair
        return _build_multi_round_robin(all_teams, games_per_team, rng)

    # Single round with selective upgrades
    series = []
    pair_indices = list(range(len(pairs)))
    rng.shuffle(pair_indices)

    team_upgrades = {i: 0 for i in range(n)}
    upgrade_target = extra_needed  # per team

    for pi in pair_indices:
        a, b = pairs[pi]
        length = 3
        if team_upgrades[a] < upgrade_target and team_upgrades[b] < upgrade_target:
            length = 4
            team_upgrades[a] += 1
            team_upgrades[b] += 1

        series.append({
            "team_a": all_teams[a]["id"],
            "team_b": all_teams[b]["id"],
            "length": length,
            "category": "round_robin",
        })

    # Validate per-team totals
    team_games = {}
    for s in series:
        team_games[s["team_a"]] = team_games.get(s["team_a"], 0) + s["length"]
        team_games[s["team_b"]] = team_games.get(s["team_b"], 0) + s["length"]

    for t in all_teams:
        count = team_games.get(t["id"], 0)
        if count != games_per_team:
            log.warning(
                "schedule: minor team %s has %d games (target %d)",
                t.get("team_abbrev"), count, games_per_team,
            )

    return series


def _build_multi_round_robin(
    all_teams: List[Dict],
    games_per_team: int,
    rng: random.Random,
) -> List[Dict]:
    """
    Build matchup pool when games_per_team requires multiple series per pair.
    Used when single round-robin isn't enough games.
    """
    n = len(all_teams)
    pairs = list(combinations(range(n), 2))

    # Determine base series per pair and extras
    # Each pair gets at least base_series; some get base_series + 1
    series_per_team = games_per_team  # approximate, refined below

    # Calculate: with s series per pair, each team plays (n-1)*s series.
    # Total games ≈ (n-1)*s * 3.5
    # We want total games = games_per_team
    # series_per_pair_avg = games_per_team / ((n-1) * 3.5)

    # Start with floor, add extras
    base_per_pair = games_per_team // (n - 1)
    base_length = 3 if base_per_pair == 3 else 4

    # For each pair: determine how many series and their lengths
    # Target: each team gets exactly games_per_team
    # Strategy: give each pair ceil(games_per_team / (n-1)) or floor series

    games_from_base = (n - 1) * base_per_pair
    remainder = games_per_team - games_from_base

    series = []
    team_extra = {i: 0 for i in range(n)}

    for a, b in pairs:
        # Base series: split into series of 3 and 4
        total_for_pair = base_per_pair
        if team_extra[a] < remainder and team_extra[b] < remainder:
            total_for_pair += 1
            team_extra[a] += 1
            team_extra[b] += 1

        # Split total_for_pair into series of 3 and 4
        while total_for_pair > 0:
            if total_for_pair >= 4:
                length = 4 if rng.random() < 0.5 else 3
            elif total_for_pair == 3:
                length = 3
            elif total_for_pair == 2:
                length = 3  # overshoot slightly, will adjust
            else:
                break
            length = min(length, total_for_pair)
            if length < 2:
                break
            series.append({
                "team_a": all_teams[a]["id"],
                "team_b": all_teams[b]["id"],
                "length": length,
                "category": "round_robin",
            })
            total_for_pair -= length

    return series


# =====================================================================
# College matchup pool
# =====================================================================

def _build_college_matchup_pool(
    teams_by_conf: Dict[str, List[Dict]],
    games_per_team: int,
    rng: random.Random,
) -> List[Dict]:
    """
    Build college schedule: conference round-robin + OOC to hit total.
    """
    all_series = []
    team_game_count = {}

    # ── Conference round-robin ───────────────────────────────────────
    for conf, teams in teams_by_conf.items():
        if len(teams) < 2:
            continue
        for ta, tb in combinations(teams, 2):
            # One 3-game series per conference pair
            all_series.append({
                "team_a": ta["id"],
                "team_b": tb["id"],
                "length": 3,
                "category": "conference",
            })
            team_game_count[ta["id"]] = team_game_count.get(ta["id"], 0) + 3
            team_game_count[tb["id"]] = team_game_count.get(tb["id"], 0) + 3

    # ── OOC matchups to fill remaining ───────────────────────────────
    all_teams = []
    team_conf = {}
    for conf, teams in teams_by_conf.items():
        for t in teams:
            all_teams.append(t)
            team_conf[t["id"]] = conf

    # Build list of teams needing more games, sorted by need
    remaining = {
        t["id"]: max(0, games_per_team - team_game_count.get(t["id"], 0))
        for t in all_teams
    }

    # Pair up teams from different conferences who need games
    needy = [tid for tid, r in remaining.items() if r >= 3]
    rng.shuffle(needy)

    used_ooc_pairs = set()
    i = 0
    while i < len(needy) - 1:
        a = needy[i]
        if remaining[a] < 3:
            i += 1
            continue

        # Find a partner from a different conference
        paired = False
        for j in range(i + 1, len(needy)):
            b = needy[j]
            if remaining[b] < 3:
                continue
            if team_conf[a] == team_conf[b]:
                continue
            pair = frozenset([a, b])
            if pair in used_ooc_pairs:
                continue

            length = 4 if remaining[a] >= 4 and remaining[b] >= 4 and rng.random() < 0.3 else 3
            all_series.append({
                "team_a": a,
                "team_b": b,
                "length": length,
                "category": "ooc",
            })
            remaining[a] -= length
            remaining[b] -= length
            used_ooc_pairs.add(pair)
            paired = True
            break

        if not paired:
            i += 1
        # Re-sort needy list
        needy = [tid for tid in needy if remaining.get(tid, 0) >= 3]
        rng.shuffle(needy)
        i = 0  # restart scan

    return all_series


# =====================================================================
# Top-level generators
# =====================================================================

def generate_mlb_schedule(
    engine,
    league_year: int,
    seed: int = None,
    clear_existing: bool = False,
) -> Dict[str, Any]:
    """Generate a complete MLB season schedule (level 9)."""
    rng = random.Random(seed)
    tables = _get_tables(engine)

    with engine.begin() as conn:
        season_id = _resolve_season_id(conn, tables, league_year)

        validation = validate_schedule_generation(conn, tables, season_id, LEVEL_MLB)
        if not validation["valid"]:
            raise ValueError("Validation failed: %s" % "; ".join(validation["errors"]))

        if clear_existing:
            cleared = _clear_existing_schedule(conn, tables, season_id, LEVEL_MLB)
            log.info("schedule: cleared %d existing MLB games", cleared)
        elif validation["existing_games"] > 0:
            raise ValueError(
                "%d games already exist. Use clear_existing=true to replace."
                % validation["existing_games"]
            )

        teams_data = _load_mlb_teams(conn, tables)

        # Build pool → balance → assign weeks → expand → insert
        pool = _build_mlb_matchup_pool(teams_data, rng)
        _balance_home_away(pool, rng)
        week_assignments = _assign_series_to_weeks(
            pool, MLB_TOTAL_WEEKS, MLB_MAX_SERIES_PER_WEEK, start_week=1, rng=rng,
        )
        rows = _expand_to_game_rows(week_assignments, season_id, LEVEL_MLB)

        # Bulk insert
        gamelist = tables["gamelist"]
        conn.execute(gamelist.insert(), rows)

        log.info("schedule: inserted %d MLB games for year %d", len(rows), league_year)

        return {
            "league_year": league_year,
            "league_level": LEVEL_MLB,
            "season_id": season_id,
            "total_games": len(rows),
            "total_series": len(pool),
            "weeks": MLB_TOTAL_WEEKS,
            "games_per_team": MLB_GAMES_PER_TEAM,
        }


def generate_minor_league_schedule(
    engine,
    league_year: int,
    level: int,
    start_week: int = 10,
    seed: int = None,
    clear_existing: bool = False,
) -> Dict[str, Any]:
    """Generate a minor league schedule (levels 4-8)."""
    if level not in MINOR_LEVELS:
        raise ValueError("Level %d is not a minor league level" % level)

    rng = random.Random(seed)
    tables = _get_tables(engine)

    with engine.begin() as conn:
        season_id = _resolve_season_id(conn, tables, league_year)

        validation = validate_schedule_generation(conn, tables, season_id, level)
        if not validation["valid"]:
            raise ValueError("Validation failed: %s" % "; ".join(validation["errors"]))

        if clear_existing:
            _clear_existing_schedule(conn, tables, season_id, level)
        elif validation["existing_games"] > 0:
            raise ValueError(
                "%d games already exist. Use clear_existing=true to replace."
                % validation["existing_games"]
            )

        all_teams = _load_minor_teams(conn, tables, level)
        if len(all_teams) < 2:
            raise ValueError("Need at least 2 teams at level %d, found %d" % (level, len(all_teams)))

        pool = _build_minor_matchup_pool(all_teams, MILB_GAMES_PER_TEAM, rng)
        _balance_home_away(pool, rng)

        # Calculate weeks needed
        series_per_team = len([s for s in pool if s["team_a"] == all_teams[0]["id"]
                               or s["team_b"] == all_teams[0]["id"]])
        num_weeks = series_per_team + 1  # +1 for a bye week
        max_per_week = len(all_teams) // 2

        week_assignments = _assign_series_to_weeks(
            pool, num_weeks, max_per_week, start_week=start_week, rng=rng,
        )
        rows = _expand_to_game_rows(week_assignments, season_id, level)

        gamelist = tables["gamelist"]
        conn.execute(gamelist.insert(), rows)

        log.info(
            "schedule: inserted %d level-%d games for year %d",
            len(rows), level, league_year,
        )

        return {
            "league_year": league_year,
            "league_level": level,
            "season_id": season_id,
            "total_games": len(rows),
            "total_series": len(pool),
            "weeks": num_weeks,
            "start_week": start_week,
            "games_per_team": MILB_GAMES_PER_TEAM,
        }


def generate_college_schedule(
    engine,
    league_year: int,
    start_week: int = 1,
    seed: int = None,
    clear_existing: bool = False,
) -> Dict[str, Any]:
    """Generate a college baseball schedule (level 3)."""
    rng = random.Random(seed)
    tables = _get_tables(engine)

    with engine.begin() as conn:
        season_id = _resolve_season_id(conn, tables, league_year)

        validation = validate_schedule_generation(conn, tables, season_id, LEVEL_COLLEGE)
        if not validation["valid"]:
            raise ValueError("Validation failed: %s" % "; ".join(validation["errors"]))

        if clear_existing:
            _clear_existing_schedule(conn, tables, season_id, LEVEL_COLLEGE)
        elif validation["existing_games"] > 0:
            raise ValueError(
                "%d games already exist. Use clear_existing=true to replace."
                % validation["existing_games"]
            )

        teams_by_conf = _load_college_teams(conn, tables)
        all_teams = [t for teams in teams_by_conf.values() for t in teams]

        pool = _build_college_matchup_pool(teams_by_conf, COLLEGE_GAMES_PER_TEAM, rng)
        _balance_home_away(pool, rng)

        # Calculate weeks needed based on the team with most series
        team_series_count = {}
        for s in pool:
            team_series_count[s["team_a"]] = team_series_count.get(s["team_a"], 0) + 1
            team_series_count[s["team_b"]] = team_series_count.get(s["team_b"], 0) + 1
        max_series = max(team_series_count.values()) if team_series_count else 0
        num_weeks = max_series + 1  # +1 buffer

        # Max simultaneous series = half the teams
        max_per_week = len(all_teams) // 2

        week_assignments = _assign_series_to_weeks(
            pool, num_weeks, max_per_week, start_week=start_week, rng=rng,
        )
        rows = _expand_to_game_rows(week_assignments, season_id, LEVEL_COLLEGE)

        gamelist = tables["gamelist"]
        conn.execute(gamelist.insert(), rows)

        log.info("schedule: inserted %d college games for year %d", len(rows), league_year)

        return {
            "league_year": league_year,
            "league_level": LEVEL_COLLEGE,
            "season_id": season_id,
            "total_games": len(rows),
            "total_series": len(pool),
            "weeks": num_weeks,
            "start_week": start_week,
        }


# =====================================================================
# Utility: single-series insertion (future playoff / specialty hook)
# =====================================================================

def add_series(
    engine,
    league_year: int,
    league_level: int,
    home_team_id: int,
    away_team_id: int,
    week: int,
    games: int = 3,
) -> Dict[str, Any]:
    """
    Insert a single series into the schedule. Useful for playoffs,
    exhibition games, and specialty matchups.
    """
    if games < 1 or games > 4:
        raise ValueError("games must be 1-4, got %d" % games)

    tables = _get_tables(engine)

    with engine.begin() as conn:
        season_id = _resolve_season_id(conn, tables, league_year)

        rows = []
        for i in range(games):
            rows.append({
                "away_team": away_team_id,
                "home_team": home_team_id,
                "season_week": week,
                "season_subweek": SUBWEEK_LABELS[i],
                "league_level": league_level,
                "season": season_id,
                "random_seed": None,
            })

        gamelist = tables["gamelist"]
        conn.execute(gamelist.insert(), rows)

        log.info(
            "schedule: added %d-game series week %d: team %d vs %d",
            games, week, home_team_id, away_team_id,
        )

        return {
            "games_added": games,
            "week": week,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
        }
