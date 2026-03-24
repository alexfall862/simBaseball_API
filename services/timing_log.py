# services/timing_log.py
"""
Lightweight timing logger for simulation performance profiling.

Writes to timing_log.txt in the project root. Each line records a timed
stage with week, subweek, level, duration, and optional detail counts
so bottlenecks can be identified across season runs.

Format:
    2026-03-23 17:22:11 | week=1 sw=a level=9 | engine_call        |  2.34s | 15 games
"""

import logging
import os
import time
from contextlib import contextmanager

_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "timing_log.txt")

_logger = logging.getLogger("sim_timing")
_logger.setLevel(logging.INFO)
_logger.propagate = False

if not _logger.handlers:
    _handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(_handler)


@contextmanager
def timed_stage(stage: str, *, week: int = 0, subweek: str = "",
                level: int | str = "", detail: str = ""):
    """Context manager that logs elapsed time for a named stage.

    Usage:
        with timed_stage("engine_call", week=1, subweek="a", level=9, detail="15 games"):
            results = simulate_games_batch(...)
    """
    t0 = time.monotonic()
    yield
    elapsed = time.monotonic() - t0
    ctx = f"week={week} sw={subweek:<1} level={str(level):<3}"
    _logger.info(
        "%s | %-28s | %7.2fs | %s",
        ctx, stage, elapsed, detail,
    )


def log_timing(stage: str, elapsed: float, *, week: int = 0,
               subweek: str = "", level: int | str = "", detail: str = ""):
    """Direct log call when a context manager isn't convenient."""
    ctx = f"week={week} sw={subweek:<1} level={str(level):<3}"
    _logger.info(
        "%s | %-28s | %7.2fs | %s",
        ctx, stage, elapsed, detail,
    )
