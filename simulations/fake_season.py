# simulations/fake_season.py

import random
from typing import Dict, Any

from sqlalchemy import MetaData, Table, select, delete, and_
from sqlalchemy.exc import SQLAlchemyError


def simulate_fake_season(engine, league_year: int, league_level: int = 9) -> Dict[str, Any]:
    """
    Fake-season harness:

      - Reads MLB schedule from gamelist for the given season/league_level.
      - Simulates a winner/loser and score for each game into game_results.
      - Aggregates weekly wins/losses per org into team_weekly_record.

    This will **delete** any existing game_results and team_weekly_record data
    for that league_year before re-populating them.
    """
    md = MetaData()
    gamelist = Table("gamelist", md, autoload_with=engine)
    teams = Table("teams", md, autoload_with=engine)
    league_years = Table("league_years", md, autoload_with=engine)
    game_weeks = Table("game_weeks", md, autoload_with=engine)
    game_results = Table("game_results", md, autoload_with=engine)
    weekly = Table("team_weekly_record", md, autoload_with=engine)

    with engine.begin() as conn:
        # 1) Resolve league_year row & week_index -> game_week_id map
        ly_row = conn.execute(
            select(
                league_years.c.id,
                league_years.c.league_year,
            ).where(league_years.c.league_year == league_year)
        ).first()
        if not ly_row:
            raise ValueError(f"league_year {league_year} not found in league_years")

        ly_map = ly_row._mapping
        league_year_id = ly_map["id"]

        week_rows = conn.execute(
            select(game_weeks.c.id, game_weeks.c.week_index)
            .where(game_weeks.c.league_year_id == league_year_id)
        ).all()
        week_index_to_id = {
            r._mapping["week_index"]: r._mapping["id"]
            for r in week_rows
        }
        if not week_index_to_id:
            raise ValueError(f"No game_weeks found for league_year_id={league_year_id}")

        # 2) Fetch MLB games for this season from gamelist, with orgs
        t_home = teams.alias("t_home")
        t_away = teams.alias("t_away")

        game_rows = conn.execute(
            select(
                gamelist.c.id.label("game_id"),
                gamelist.c.season,
                gamelist.c.league_level,
                gamelist.c.season_week,
                gamelist.c.season_subweek,
                gamelist.c.home_team.label("home_team_id"),
                gamelist.c.away_team.label("away_team_id"),
                t_home.c.orgID.label("home_org_id"),
                t_away.c.orgID.label("away_org_id"),
            )
            .select_from(
                gamelist
                .join(t_home, gamelist.c.home_team == t_home.c.id)
                .join(t_away, gamelist.c.away_team == t_away.c.id)
            )
            .where(
                and_(
                    gamelist.c.season == league_year,
                    gamelist.c.league_level == league_level,
                )
            )
        ).all()

        if not game_rows:
            raise ValueError(f"No games in gamelist for season={league_year}, league_level={league_level}")

        game_ids = [r._mapping["game_id"] for r in game_rows]

        # 3) Clear out any existing results + weekly records for this year
        if game_ids:
            conn.execute(
                delete(game_results).where(game_results.c.game_id.in_(game_ids))
            )

        conn.execute(
            delete(weekly).where(weekly.c.league_year_id == league_year_id)
        )

        # 4) Simulate each game
        results_inserts = []
        home_win_prob = 0.54  # small home-field advantage

        for row in game_rows:
            m = row._mapping
            game_id = m["game_id"]
            season = m["season"]
            lvl = m["league_level"]
            season_week = m["season_week"]
            season_subweek = m["season_subweek"]

            home_team_id = m["home_team_id"]
            away_team_id = m["away_team_id"]
            home_org_id = m["home_org_id"]
            away_org_id = m["away_org_id"]

            # Decide winner and scores
            if random.random() < home_win_prob:
                # home wins
                home_score = random.randint(3, 8)
                away_score = random.randint(0, max(home_score - 1, 0))
                winning_team_id = home_team_id
                losing_team_id = away_team_id
                winning_org_id = home_org_id
                losing_org_id = away_org_id
                outcome = "HOME_WIN"
            else:
                # away wins
                away_score = random.randint(3, 8)
                home_score = random.randint(0, max(away_score - 1, 0))
                winning_team_id = away_team_id
                losing_team_id = home_team_id
                winning_org_id = away_org_id
                losing_org_id = home_org_id
                outcome = "AWAY_WIN"

            results_inserts.append(
                {
                    "game_id": game_id,
                    "season": season,
                    "league_level": lvl,
                    "season_week": season_week,
                    "season_subweek": season_subweek,
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "home_score": home_score,
                    "away_score": away_score,
                    "winning_team_id": winning_team_id,
                    "losing_team_id": losing_team_id,
                    "winning_org_id": winning_org_id,
                    "losing_org_id": losing_org_id,
                    "game_outcome": outcome,
                    # completed_at will default to CURRENT_TIMESTAMP
                }
            )

        if results_inserts:
            conn.execute(game_results.insert(), results_inserts)

        # 5) Aggregate into weekly records per org
        # Key: (org_id, season_week) -> {"wins": x, "losses": y}
        agg: Dict[tuple, Dict[str, int]] = {}

        for res in results_inserts:
            week = res["season_week"]

            # Winner record
            w_org = res["winning_org_id"]
            key_w = (w_org, week)
            rec_w = agg.setdefault(key_w, {"wins": 0, "losses": 0})
            rec_w["wins"] += 1

            # Loser record
            l_org = res["losing_org_id"]
            key_l = (l_org, week)
            rec_l = agg.setdefault(key_l, {"wins": 0, "losses": 0})
            rec_l["losses"] += 1

        weekly_inserts = []
        for (org_id, week_index), wl in agg.items():
            gw_id = week_index_to_id.get(week_index)
            if gw_id is None:
                # If for some reason week index is missing, skip this
                continue

            weekly_inserts.append(
                {
                    "org_id": org_id,
                    "league_year_id": league_year_id,
                    "game_week_id": gw_id,
                    "wins": wl["wins"],
                    "losses": wl["losses"],
                }
            )

        if weekly_inserts:
            conn.execute(weekly.insert(), weekly_inserts)

        return {
            "league_year": league_year,
            "league_level": league_level,
            "games_simulated": len(results_inserts),
            "weekly_records_created": len(weekly_inserts),
        }
