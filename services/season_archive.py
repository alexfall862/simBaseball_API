# services/season_archive.py
"""
End-of-season data archive / cleanup.

Prunes per-game ephemeral data (batting/pitching lines, substitutions,
play-by-play, position usage, fatigue state, ledger detail) while
preserving accumulated stats, standings, schedules, and historical records.

Admin-triggerable via POST /admin/season/archive.
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy import text

logger = logging.getLogger("app")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_ids(conn, league_year_id: int) -> Dict[str, int]:
    """Resolve league_year_id → league_year (int) → season_id."""
    row = conn.execute(
        text("SELECT league_year FROM league_years WHERE id = :id"),
        {"id": league_year_id},
    ).first()
    if not row:
        raise ValueError(f"league_year_id {league_year_id} not found")
    league_year = row[0]

    row2 = conn.execute(
        text("SELECT id FROM seasons WHERE year = :yr"),
        {"yr": league_year},
    ).first()
    if not row2:
        raise ValueError(f"No season row for year {league_year}")

    return {"league_year": league_year, "season_id": row2[0]}


def _batch_delete(engine, table: str, where: str, params: dict,
                  batch_size: int) -> int:
    """Delete rows in batches, each in its own transaction."""
    total = 0
    while True:
        with engine.begin() as conn:
            result = conn.execute(
                text(f"DELETE FROM {table} WHERE {where} LIMIT :_batch"),
                {**params, "_batch": batch_size},
            )
        total += result.rowcount
        if result.rowcount < batch_size:
            break
    return total


def _count(conn, table: str, where: str, params: dict) -> int:
    row = conn.execute(
        text(f"SELECT COUNT(*) FROM {table} WHERE {where}"),
        params,
    ).first()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Individual cleanup steps
# ---------------------------------------------------------------------------

def _clean_game_batting_lines(engine, conn, ly_id: int, dry_run: bool,
                              batch_size: int) -> Dict[str, int]:
    where = "league_year_id = :ly"
    params = {"ly": ly_id}
    counted = _count(conn, "game_batting_lines", where, params)
    deleted = 0 if dry_run else _batch_delete(
        engine, "game_batting_lines", where, params, batch_size)
    return {"counted": counted, "deleted": deleted}


def _clean_game_pitching_lines(engine, conn, ly_id: int, dry_run: bool,
                               batch_size: int) -> Dict[str, int]:
    where = "league_year_id = :ly"
    params = {"ly": ly_id}
    counted = _count(conn, "game_pitching_lines", where, params)
    deleted = 0 if dry_run else _batch_delete(
        engine, "game_pitching_lines", where, params, batch_size)
    return {"counted": counted, "deleted": deleted}


def _clean_game_substitutions(engine, conn, ly_id: int, dry_run: bool,
                              batch_size: int) -> Dict[str, int]:
    where = "league_year_id = :ly"
    params = {"ly": ly_id}
    counted = _count(conn, "game_substitutions", where, params)
    deleted = 0 if dry_run else _batch_delete(
        engine, "game_substitutions", where, params, batch_size)
    return {"counted": counted, "deleted": deleted}


def _clean_position_usage(engine, conn, ly_id: int, dry_run: bool,
                          batch_size: int) -> Dict[str, int]:
    where = "league_year_id = :ly"
    params = {"ly": ly_id}
    counted = _count(conn, "player_position_usage_week", where, params)
    deleted = 0 if dry_run else _batch_delete(
        engine, "player_position_usage_week", where, params, batch_size)
    return {"counted": counted, "deleted": deleted}


def _clean_fatigue_state(engine, conn, ly_id: int, dry_run: bool,
                         batch_size: int) -> Dict[str, int]:
    where = "league_year_id = :ly"
    params = {"ly": ly_id}
    counted = _count(conn, "player_fatigue_state", where, params)
    deleted = 0 if dry_run else _batch_delete(
        engine, "player_fatigue_state", where, params, batch_size)
    return {"counted": counted, "deleted": deleted}


def _clean_game_results_json(engine, conn, season_id: int,
                             dry_run: bool) -> Dict[str, Any]:
    """NULL out heavy JSON columns from game_results.

    - Levels 3-8: NULL both boxscore_json and play_by_play_json
    - Level 9 regular: NULL play_by_play_json only (keep boxscores)
    - Level 9 playoff: keep everything
    """
    # Count MiLB (levels 3-8)
    milb_count = conn.execute(text("""
        SELECT COUNT(*) FROM game_results gr
        JOIN gamelist gl ON gl.id = gr.game_id
        WHERE gl.season = :sid
          AND gl.league_level BETWEEN 3 AND 8
          AND (gr.boxscore_json IS NOT NULL
               OR gr.play_by_play_json IS NOT NULL)
    """), {"sid": season_id}).first()[0]

    # Count MLB regular season PBP
    mlb_reg_count = conn.execute(text("""
        SELECT COUNT(*) FROM game_results gr
        JOIN gamelist gl ON gl.id = gr.game_id
        WHERE gl.season = :sid
          AND gl.league_level = 9
          AND gr.game_type = 'regular'
          AND gr.play_by_play_json IS NOT NULL
    """), {"sid": season_id}).first()[0]

    milb_updated = 0
    mlb_reg_updated = 0

    if not dry_run:
        # NULL both columns for levels 3-8
        r = conn.execute(text("""
            UPDATE game_results gr
            JOIN gamelist gl ON gl.id = gr.game_id
            SET gr.boxscore_json = NULL,
                gr.play_by_play_json = NULL
            WHERE gl.season = :sid
              AND gl.league_level BETWEEN 3 AND 8
        """), {"sid": season_id})
        milb_updated = r.rowcount

        # NULL PBP only for MLB regular season
        r = conn.execute(text("""
            UPDATE game_results gr
            JOIN gamelist gl ON gl.id = gr.game_id
            SET gr.play_by_play_json = NULL
            WHERE gl.season = :sid
              AND gl.league_level = 9
              AND gr.game_type = 'regular'
        """), {"sid": season_id})
        mlb_reg_updated = r.rowcount

    return {
        "milb_json_nulled": {"counted": milb_count, "updated": milb_updated},
        "mlb_regular_pbp_nulled": {"counted": mlb_reg_count,
                                   "updated": mlb_reg_updated},
    }


def _clean_ledger_entries(engine, conn, ly_id: int, dry_run: bool,
                          batch_size: int) -> Dict[str, Any]:
    """Summarize ledger entries per org per entry_type, then delete detail.

    Inserts archive_<type> summary rows, then deletes originals.
    """
    # Check if archive rows already exist for this league_year
    existing_archives = conn.execute(text("""
        SELECT COUNT(*) FROM org_ledger_entries
        WHERE league_year_id = :ly AND entry_type LIKE 'archive_%'
    """), {"ly": ly_id}).first()[0]

    # Count detail rows (non-archive)
    detail_count = conn.execute(text("""
        SELECT COUNT(*) FROM org_ledger_entries
        WHERE league_year_id = :ly AND entry_type NOT LIKE 'archive_%'
    """), {"ly": ly_id}).first()[0]

    summarized = 0

    if not dry_run:
        # Only create archive rows if they don't already exist
        if existing_archives == 0:
            # Get per-org per-type sums
            rows = conn.execute(text("""
                SELECT org_id, entry_type, SUM(amount) AS total
                FROM org_ledger_entries
                WHERE league_year_id = :ly
                  AND entry_type NOT LIKE 'archive_%'
                GROUP BY org_id, entry_type
            """), {"ly": ly_id}).all()

            for r in rows:
                conn.execute(text("""
                    INSERT INTO org_ledger_entries
                        (org_id, league_year_id, game_week_id,
                         entry_type, amount, note)
                    VALUES (:org, :ly, NULL,
                            :etype, :amt, 'Season archive summary')
                """), {
                    "org": r[0],
                    "ly": ly_id,
                    "etype": f"archive_{r[1]}",
                    "amt": float(r[2]) if r[2] is not None else 0.0,
                })
                summarized += 1

        # Delete detail rows
        deleted = _batch_delete(
            engine, "org_ledger_entries",
            "league_year_id = :ly AND entry_type NOT LIKE 'archive_%'",
            {"ly": ly_id}, batch_size,
        )
    else:
        deleted = 0

    return {
        "detail_counted": detail_count,
        "archive_rows_existing": existing_archives,
        "archive_rows_created": summarized,
        "detail_deleted": deleted,
    }


def _clean_draft_eligible(engine, conn, ly_id: int, dry_run: bool,
                          batch_size: int) -> Dict[str, int]:
    where = "league_year_id = :ly"
    params = {"ly": ly_id}
    counted = _count(conn, "draft_eligible_players", where, params)
    deleted = 0 if dry_run else _batch_delete(
        engine, "draft_eligible_players", where, params, batch_size)
    return {"counted": counted, "deleted": deleted}


def _clean_recruiting(engine, conn, ly_id: int, dry_run: bool,
                      batch_size: int) -> Dict[str, Any]:
    """Delete recruiting board, investments, rankings for the season."""
    tables = ["recruiting_board", "recruiting_investments",
              "recruiting_rankings"]
    results = {}
    where = "league_year_id = :ly"
    params = {"ly": ly_id}
    for t in tables:
        counted = _count(conn, t, where, params)
        deleted = 0 if dry_run else _batch_delete(
            engine, t, where, params, batch_size)
        results[t] = {"counted": counted, "deleted": deleted}
    return results


def _clean_trade_proposals(engine, conn, ly_id: int, dry_run: bool,
                           batch_size: int) -> Dict[str, int]:
    where = "league_year_id = :ly AND status != 'executed'"
    params = {"ly": ly_id}
    counted = _count(conn, "trade_proposals", where, params)
    deleted = 0 if dry_run else _batch_delete(
        engine, "trade_proposals", where, params, batch_size)
    return {"counted": counted, "deleted": deleted}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_PRESERVED_TABLES = [
    "player_batting_stats", "player_pitching_stats", "player_fielding_stats",
    "team_weekly_record", "game_weeks", "gamelist", "game_results (rows kept)",
    "transaction_log", "draft_state", "draft_picks", "draft_signing",
    "draft_pick_trades", "recruiting_commitments", "recruiting_state",
    "scouting_budgets", "scouting_actions",
    "player_injury_events", "career_injuries",
    "playoff_series", "cws_bracket",
    "special_events", "special_event_rosters",
]


def archive_season(
    engine,
    league_year_id: int,
    dry_run: bool = True,
    batch_size: int = 5000,
) -> Dict[str, Any]:
    """
    Archive/cleanup data for a completed season.

    Args:
        engine: SQLAlchemy engine.
        league_year_id: The completed season to archive.
        dry_run: If True, only count rows — don't delete anything.
        batch_size: Rows per DELETE batch (prevents lock contention).

    Returns:
        Dict with per-table counts, preserved list, and any warnings.
    """
    warnings: List[str] = []
    tables: Dict[str, Any] = {}

    # Resolve IDs
    with engine.connect() as conn:
        ids = _resolve_ids(conn, league_year_id)
    league_year = ids["league_year"]
    season_id = ids["season_id"]

    logger.info("archive_season: ly_id=%d year=%d season_id=%d dry_run=%s",
                league_year_id, league_year, season_id, dry_run)

    # Use a single connection for counts, separate transactions for deletes
    with engine.connect() as conn:

        # 1. game_batting_lines
        try:
            tables["game_batting_lines"] = _clean_game_batting_lines(
                engine, conn, league_year_id, dry_run, batch_size)
        except Exception as e:
            logger.warning("archive: game_batting_lines failed: %s", e)
            warnings.append(f"game_batting_lines: {e}")

        # 2. game_pitching_lines
        try:
            tables["game_pitching_lines"] = _clean_game_pitching_lines(
                engine, conn, league_year_id, dry_run, batch_size)
        except Exception as e:
            logger.warning("archive: game_pitching_lines failed: %s", e)
            warnings.append(f"game_pitching_lines: {e}")

        # 3. game_substitutions
        try:
            tables["game_substitutions"] = _clean_game_substitutions(
                engine, conn, league_year_id, dry_run, batch_size)
        except Exception as e:
            logger.warning("archive: game_substitutions failed: %s", e)
            warnings.append(f"game_substitutions: {e}")

        # 4. player_position_usage_week
        try:
            tables["player_position_usage_week"] = _clean_position_usage(
                engine, conn, league_year_id, dry_run, batch_size)
        except Exception as e:
            logger.warning("archive: position_usage failed: %s", e)
            warnings.append(f"player_position_usage_week: {e}")

        # 5. player_fatigue_state
        try:
            tables["player_fatigue_state"] = _clean_fatigue_state(
                engine, conn, league_year_id, dry_run, batch_size)
        except Exception as e:
            logger.warning("archive: fatigue_state failed: %s", e)
            warnings.append(f"player_fatigue_state: {e}")

    # 6-7. game_results JSON nulling (needs its own transaction for UPDATEs)
    try:
        with engine.begin() as conn:
            gr_result = _clean_game_results_json(
                engine, conn, season_id, dry_run)
        tables.update(gr_result)
    except Exception as e:
        logger.warning("archive: game_results_json failed: %s", e)
        warnings.append(f"game_results_json: {e}")

    # 8. org_ledger_entries (summarize + delete)
    try:
        with engine.begin() as conn:
            tables["org_ledger_entries"] = _clean_ledger_entries(
                engine, conn, league_year_id, dry_run, batch_size)
    except Exception as e:
        logger.warning("archive: ledger_entries failed: %s", e)
        warnings.append(f"org_ledger_entries: {e}")

    # 9. draft_eligible_players
    try:
        with engine.connect() as conn:
            tables["draft_eligible_players"] = _clean_draft_eligible(
                engine, conn, league_year_id, dry_run, batch_size)
    except Exception as e:
        logger.warning("archive: draft_eligible failed: %s", e)
        warnings.append(f"draft_eligible_players: {e}")

    # 10. recruiting tables
    try:
        with engine.connect() as conn:
            recruiting = _clean_recruiting(
                engine, conn, league_year_id, dry_run, batch_size)
        tables.update(recruiting)
    except Exception as e:
        logger.warning("archive: recruiting failed: %s", e)
        warnings.append(f"recruiting: {e}")

    # 11. trade_proposals (non-executed)
    try:
        with engine.connect() as conn:
            tables["trade_proposals"] = _clean_trade_proposals(
                engine, conn, league_year_id, dry_run, batch_size)
    except Exception as e:
        logger.warning("archive: trade_proposals failed: %s", e)
        warnings.append(f"trade_proposals: {e}")

    return {
        "league_year_id": league_year_id,
        "league_year": league_year,
        "dry_run": dry_run,
        "tables": tables,
        "preserved": _PRESERVED_TABLES,
        "warnings": warnings,
    }
