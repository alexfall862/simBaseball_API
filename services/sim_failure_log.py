# services/sim_failure_log.py
"""
Dedicated file logger for simulation failures.

Writes to sim_failures.log in the project root. Each entry includes
timestamp, level, subweek, game IDs, and the failure reason so issues
can be reviewed after a long season run without digging through the
full application log or DB diagnostic table.
"""

import logging
import os

_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sim_failures.log")

_logger = logging.getLogger("sim_failures")
_logger.setLevel(logging.WARNING)
_logger.propagate = False  # don't duplicate into root/console handler

if not _logger.handlers:
    _handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(_handler)


def log_engine_failure(
    *,
    subweek: str,
    league_level: int | None = None,
    season_week: int | None = None,
    game_count: int = 0,
    error: str,
):
    """Log an engine-level failure (HTTP error, timeout, bad response)."""
    _logger.error(
        "ENGINE FAILURE | level=%s week=%s subweek=%s games=%d | %s",
        league_level, season_week, subweek, game_count, error,
    )


def log_missing_games(
    *,
    subweek: str,
    league_level: int,
    season_week: int,
    sent_ids: list,
    missing_ids: list,
):
    """Log games that were sent to the engine but not returned."""
    _logger.warning(
        "MISSING GAMES | level=%d week=%d subweek=%s | sent=%d missing=%d | missing_ids=%s",
        league_level, season_week, subweek, len(sent_ids), len(missing_ids), missing_ids,
    )


def log_phase2_failure(
    *,
    subweek: str,
    league_level: int,
    season_week: int | None = None,
    stage: str,
    error: str,
):
    """Log a Phase 2 (post-engine write) failure."""
    _logger.error(
        "PHASE2 FAILURE | level=%d week=%s subweek=%s stage=%s | %s",
        league_level, season_week, subweek, stage, error,
    )
