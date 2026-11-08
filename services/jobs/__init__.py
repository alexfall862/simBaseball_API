# services/jobs/__init__.py
"""
Job registry for the admin scheduler.

Every job type is a plain function ``fn(ctx) -> dict`` registered with
``@job(...)``.  Jobs call existing service code directly (never HTTP).  The
scheduler (services/job_scheduler.py) wraps execution with a run row,
heartbeat, log capture and phase guards; the admin UI builds its forms from
the metadata recorded here (GET /admin/jobs/types).

ctx (JobContext) offers:
    ctx.params         dict of job params (defaults applied)
    ctx.engine         SQLAlchemy engine
    ctx.log(msg)       appends to the run log (also logs at INFO)
    ctx.set_progress(n, total=None, stage=None)
    ctx.check_cancel() raises JobCancelled if cancel was requested
    ctx.skip(reason)   raises JobSkipped -> run ends as 'skipped'
    ctx.timestamp()    enhanced timestamp dict (cached per run)
    ctx.league_year_id()  resolves params['league_year_id'] or the timestamp's
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobSkipped(Exception):
    """Raised by a job (or a guard) to end the run as 'skipped' with a reason."""


class JobCancelled(Exception):
    """Raised by ctx.check_cancel() when the admin asked for cancellation."""


@dataclass
class JobSpec:
    name: str
    title: str
    fn: Callable[["JobContext"], Dict[str, Any]]
    description: str = ""
    phases: Optional[List[str]] = None          # allowed phases; None = any
    params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    group: str = "season"
    long_running: bool = False
    dangerous: bool = False
    preview: Optional[Callable[["JobContext"], Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_type": self.name,
            "title": self.title,
            "description": self.description,
            "phases": self.phases,
            "params": self.params,
            "group": self.group,
            "long_running": self.long_running,
            "dangerous": self.dangerous,
            "has_preview": self.preview is not None,
        }


_REGISTRY: Dict[str, JobSpec] = {}


def job(name: str, *, title: str, description: str = "", phases: Optional[List[str]] = None,
        params: Optional[Dict[str, Dict[str, Any]]] = None, group: str = "season",
        long_running: bool = False, dangerous: bool = False):
    def deco(fn):
        _REGISTRY[name] = JobSpec(
            name=name, title=title, fn=fn, description=description, phases=phases,
            params=params or {}, group=group, long_running=long_running, dangerous=dangerous,
        )
        return fn
    return deco


def preview_for(name: str):
    """Attach a preview function to an already-registered job type."""
    def deco(fn):
        _REGISTRY[name].preview = fn
        return fn
    return deco


def get_job(name: str) -> JobSpec:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown job_type '{name}'")


def list_jobs() -> List[JobSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: (s.group, s.title))


def apply_defaults(spec: JobSpec, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, meta in spec.params.items():
        if params and key in params and params[key] is not None:
            out[key] = _coerce(meta.get("type"), params[key])
        elif "default" in meta:
            out[key] = meta["default"]
    if params:
        for k, v in params.items():
            if k not in out and v is not None:
                out[k] = v
    return out


def _coerce(typ: Optional[str], v: Any) -> Any:
    try:
        if typ == "int":
            return int(v)
        if typ == "bool":
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "on")
            return bool(v)
        if typ == "list[int]":
            if isinstance(v, str):
                v = [p for p in v.replace(";", ",").split(",") if p.strip()]
            return [int(x) for x in v]
        if typ == "str":
            return str(v)
    except (TypeError, ValueError) as e:
        raise ValueError(f"param '{v}' is not a valid {typ}: {e}")
    return v


class JobContext:
    def __init__(self, engine, params: Dict[str, Any], *, run_id: Optional[int] = None,
                 log_fn=None, progress_fn=None, cancel_fn=None):
        self.engine = engine
        self.params = params
        self.run_id = run_id
        self._log_fn = log_fn
        self._progress_fn = progress_fn
        self._cancel_fn = cancel_fn
        self._ts = None
        self.lines: List[str] = []

    # -- plumbing -----------------------------------------------------------
    def log(self, msg: str) -> None:
        self.lines.append(msg)
        logger.info("[job run %s] %s", self.run_id, msg)
        if self._log_fn:
            try:
                self._log_fn(msg)
            except Exception:  # noqa: BLE001
                pass

    def set_progress(self, n: int, total: Optional[int] = None, stage: Optional[str] = None) -> None:
        if self._progress_fn:
            try:
                self._progress_fn(n, total, stage)
            except Exception:  # noqa: BLE001
                pass

    def check_cancel(self) -> None:
        if self._cancel_fn and self._cancel_fn():
            raise JobCancelled("cancelled by admin")

    def skip(self, reason: str):
        raise JobSkipped(reason)

    # -- league state helpers ---------------------------------------------
    def timestamp(self, refresh: bool = False) -> Dict[str, Any]:
        if self._ts is None or refresh:
            from services.timestamp import get_enhanced_timestamp
            self._ts = get_enhanced_timestamp() or {}
        return self._ts

    def phase(self) -> str:
        return self.timestamp().get("Phase", "UNKNOWN")

    def league_year_id(self) -> int:
        lyid = self.params.get("league_year_id")
        if lyid:
            return int(lyid)
        ts = self.timestamp()
        if ts.get("LeagueYearID"):
            return int(ts["LeagueYearID"])
        raise ValueError("league_year_id is required (no current league year resolved)")

    def league_year(self) -> int:
        """Year number (e.g. 2026), for the financials/books API."""
        if self.params.get("league_year"):
            return int(self.params["league_year"])
        from sqlalchemy import text
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT league_year FROM league_years WHERE id = :i"),
                               {"i": self.league_year_id()}).scalar()
        if not row:
            raise ValueError("could not resolve league_year from league_year_id")
        return int(row)


# ---------------------------------------------------------------------------
# Shared param fragments
# ---------------------------------------------------------------------------
P_LYID = {"type": "int", "label": "League year ID", "help": "Defaults to the current league year.", "optional": True}
P_LEVEL_OPT = {"type": "int", "label": "League level", "help": "Blank = all levels.", "optional": True,
               "choices": [9, 8, 7, 6, 5, 3]}
SUBWEEKS = ("a", "b", "c", "d")


def _flags(ts: Dict[str, Any]) -> Dict[str, bool]:
    return {"a": bool(ts.get("GamesARan")), "b": bool(ts.get("GamesBRan")),
            "c": bool(ts.get("GamesCRan")), "d": bool(ts.get("GamesDRan"))}


def _next_subweek(ts: Dict[str, Any]) -> Optional[str]:
    f = _flags(ts)
    for k in SUBWEEKS:
        if not f[k]:
            return k
    return None


def _sim_one_subweek(ctx: JobContext, lyid: int, week: int, subweek: str,
                     league_level: Optional[int], mark_empty_complete: bool) -> Dict[str, Any]:
    from services.game_payload import build_week_payloads
    from services.timestamp import update_timestamp, set_subweek_completed, set_run_games

    update_timestamp({"week": week, "run_games": True})
    games = 0
    empty = False
    try:
        with ctx.engine.connect() as conn:
            result = build_week_payloads(
                conn=conn, league_year_id=lyid, season_week=week,
                league_level=league_level, subweek_filter=subweek,
            )
        games = len(result.get("subweeks", {}).get(subweek, []))
        set_subweek_completed(subweek, broadcast=False)
    except ValueError as e:
        # build_week_payloads raises ValueError when the subweek has no games.
        msg = str(e)
        if "no games" in msg.lower() or "not found" in msg.lower():
            empty = True
            ctx.log(f"subweek {subweek}: no games ({msg})")
            if mark_empty_complete:
                set_subweek_completed(subweek, broadcast=False)
        else:
            raise
    finally:
        set_run_games(False, broadcast=True)
    return {"subweek": subweek, "games": games, "empty": empty}


# ---------------------------------------------------------------------------
# In-season simulation jobs
# ---------------------------------------------------------------------------
@job("sim_next_subweek",
     title="Simulate next subweek",
     description="Simulates the first incomplete subweek (a→d) of the current week. After subweek d it "
                 "advances the week (books, injuries, waivers, FA phases) when auto_advance is on. "
                 "Skips if the RunGames flag is set or the league is not in the regular season/postseason.",
     phases=["REGULAR_SEASON"],
     params={
         "league_level": P_LEVEL_OPT,
         "auto_advance": {"type": "bool", "default": True, "label": "Advance week after subweek d"},
         "mark_empty_complete": {"type": "bool", "default": True, "label": "Treat a subweek with no games as complete"},
         "auto_advance_playoffs": {"type": "bool", "default": False,
                                   "label": "Also advance playoff rounds (levels below) when a round is complete"},
         "playoff_levels": {"type": "list[int]", "default": [9], "label": "Playoff levels to auto-advance"},
     })
def sim_next_subweek(ctx: JobContext) -> Dict[str, Any]:
    ts = ctx.timestamp(refresh=True)
    if ts.get("RunGames"):
        ctx.skip("RunGames flag is set (a simulation is already running or crashed mid-run)")
    week = int(ts.get("Week") or 0)
    lyid = ctx.league_year_id()
    nxt = _next_subweek(ts)
    summary: Dict[str, Any] = {"week": week, "league_year_id": lyid}

    if nxt is None:
        if not ctx.params.get("auto_advance"):
            ctx.skip("all four subweeks already complete and auto_advance is off")
        ctx.log(f"week {week}: all subweeks complete, advancing")
        from services.timestamp import advance_week
        ok = advance_week(broadcast=True)
        summary.update({"advanced": bool(ok), "advanced_to": week + 1})
        return summary

    ctx.set_progress(0, 2, f"simulating week {week} subweek {nxt}")
    ctx.log(f"week {week}: simulating subweek {nxt}")
    res = _sim_one_subweek(ctx, lyid, week, nxt, ctx.params.get("league_level"),
                           bool(ctx.params.get("mark_empty_complete", True)))
    summary.update(res)
    ctx.set_progress(1, 2, "simulated")
    ctx.check_cancel()

    if ctx.params.get("auto_advance_playoffs"):
        summary["playoffs"] = _maybe_advance_playoffs(ctx, lyid, ctx.params.get("playoff_levels") or [9])

    if nxt == "d" and ctx.params.get("auto_advance"):
        ts2 = ctx.timestamp(refresh=True)
        if _next_subweek(ts2) is None:
            ctx.log(f"week {week}: subweek d done, advancing week")
            from services.timestamp import advance_week
            ok = advance_week(broadcast=True)
            summary.update({"advanced": bool(ok), "advanced_to": week + 1})
    ctx.set_progress(2, 2, "done")
    return summary


@preview_for("sim_next_subweek")
def _preview_sim_next_subweek(ctx: JobContext) -> Dict[str, Any]:
    ts = ctx.timestamp(refresh=True)
    nxt = _next_subweek(ts)
    out = {"phase": ts.get("Phase"), "week": ts.get("Week"), "run_games": bool(ts.get("RunGames")),
           "flags": _flags(ts)}
    if ts.get("RunGames"):
        out["would"] = "skip: RunGames flag set"
    elif nxt is None:
        out["would"] = "advance week" if ctx.params.get("auto_advance") else "skip: all subweeks complete"
    else:
        out["would"] = f"simulate week {ts.get('Week')} subweek {nxt}" + \
            (" then advance week" if nxt == "d" and ctx.params.get("auto_advance") else "")
    return out


def _maybe_advance_playoffs(ctx: JobContext, lyid: int, levels: List[int]) -> Dict[str, Any]:
    from services.playoffs import process_completed_playoff_games, advance_round
    out: Dict[str, Any] = {}
    for lvl in levels:
        try:
            with ctx.engine.begin() as conn:
                processed = process_completed_playoff_games(conn, lyid, int(lvl))
                advanced = advance_round(conn, lyid, int(lvl))
            out[str(lvl)] = {"processed": len(processed), "advanced": advanced}
            ctx.log(f"playoffs level {lvl}: processed {len(processed)}, advanced={advanced}")
        except Exception as e:  # noqa: BLE001
            out[str(lvl)] = {"error": str(e)}
            ctx.log(f"playoffs level {lvl}: {e}")
    return out


@job("sim_subweek",
     title="Simulate a specific subweek",
     description="Simulates one explicit week/subweek (makeup or manual control). Marks that subweek complete.",
     phases=["REGULAR_SEASON"],
     params={"league_year_id": P_LYID,
             "week": {"type": "int", "label": "Season week"},
             "subweek": {"type": "str", "label": "Subweek", "choices": ["a", "b", "c", "d"]},
             "league_level": P_LEVEL_OPT})
def sim_subweek(ctx: JobContext) -> Dict[str, Any]:
    sw = str(ctx.params.get("subweek") or "").lower()
    if sw not in SUBWEEKS:
        raise ValueError("subweek must be a, b, c or d")
    week = int(ctx.params["week"])
    return _sim_one_subweek(ctx, ctx.league_year_id(), week, sw, ctx.params.get("league_level"), False)


@job("advance_week",
     title="Advance week",
     description="Runs weekly books, injury tick, waiver expiry, FA phase advance, listed positions, then week+1. "
                 "Guard: all four subweeks must be complete.",
     phases=["REGULAR_SEASON"],
     params={"force": {"type": "bool", "default": False, "label": "Advance even if subweeks are incomplete"}})
def advance_week_job(ctx: JobContext) -> Dict[str, Any]:
    ts = ctx.timestamp(refresh=True)
    if ts.get("RunGames"):
        ctx.skip("RunGames flag is set")
    if _next_subweek(ts) is not None and not ctx.params.get("force"):
        ctx.skip(f"subweek {_next_subweek(ts)} has not run yet")
    from services.timestamp import advance_week
    ok = advance_week(broadcast=True)
    return {"advanced": bool(ok), "from_week": ts.get("Week"), "to_week": (ts.get("Week") or 0) + 1}


@job("run_week",
     title="Run full week (sim a–d + advance)",
     description="Same as POST /games/run-week: simulate all four subweeks then advance. Idempotency-guarded "
                 "by the game_weeks claim columns.",
     phases=["REGULAR_SEASON"],
     params={"league_year_id": P_LYID, "league_level": P_LEVEL_OPT},
     long_running=True)
def run_week_job(ctx: JobContext) -> Dict[str, Any]:
    from services.game_payload import build_week_payloads
    from services.timestamp import update_timestamp, set_subweek_completed, set_run_games, advance_week
    ts = ctx.timestamp(refresh=True)
    if ts.get("RunGames"):
        ctx.skip("RunGames flag is set")
    lyid = ctx.league_year_id()
    week = int(ts.get("Week") or 0)
    steps: Dict[str, Any] = {}
    update_timestamp({"week": week, "run_games": True})
    try:
        ctx.set_progress(0, 2, f"simulating week {week}")
        with ctx.engine.connect() as conn:
            sim = build_week_payloads(conn=conn, league_year_id=lyid, season_week=week,
                                      league_level=ctx.params.get("league_level"))
        for k in SUBWEEKS:
            if sim.get("subweeks", {}).get(k):
                set_subweek_completed(k, broadcast=False)
        steps["simulate"] = {"total_games": sim.get("total_games", 0)}
    except ValueError as e:
        steps["simulate"] = {"ran": False, "error": str(e)}
        ctx.log(f"simulate: {e}")
    finally:
        set_run_games(False, broadcast=True)
    ctx.check_cancel()
    ctx.set_progress(1, 2, "advancing week")
    ok = advance_week(broadcast=True)
    steps["advance"] = {"ran": bool(ok)}
    ctx.set_progress(2, 2, "done")
    return {"week": week, "steps": steps}


@job("playoffs_process_and_advance",
     title="Playoffs: process results and advance round",
     description="Processes completed-but-untracked playoff games and advances the bracket for a level "
                 "(no-op if the round is not finished). Level 3 advances conference tournaments and the CWS.",
     phases=["REGULAR_SEASON"],
     params={"league_year_id": P_LYID,
             "league_level": {"type": "int", "default": 9, "label": "League level", "choices": [9, 8, 7, 6, 5, 3]}})
def playoffs_process_and_advance(ctx: JobContext) -> Dict[str, Any]:
    from services.playoffs import (process_completed_playoff_games, advance_round,
                                   advance_conf_tournaments, advance_cws_round)
    lyid = ctx.league_year_id()
    lvl = int(ctx.params.get("league_level") or 9)
    with ctx.engine.begin() as conn:
        processed = process_completed_playoff_games(conn, lyid, lvl)
        if lvl == 3:
            advanced = {"conf": advance_conf_tournaments(conn, lyid), "cws": advance_cws_round(conn, lyid)}
        else:
            advanced = advance_round(conn, lyid, lvl)
    return {"processed": len(processed), "advanced": advanced, "league_level": lvl}


# ---------------------------------------------------------------------------
# Offseason / market jobs
# ---------------------------------------------------------------------------
@job("fa_advance_round", title="Free agency: advance round",
     description="Advances every open FA auction one phase (a bid signs on the third advance after it).",
     phases=["FREE_AGENCY"], group="market")
def fa_advance_round(ctx: JobContext) -> Dict[str, Any]:
    from services.timestamp import advance_fa_round
    return advance_fa_round()


@job("fa_end", title="Free agency: close window",
     description="Resolves every auction (offers sign, empty auctions expire with fallback deals) and locks FA.",
     phases=["FREE_AGENCY"], group="market", dangerous=True)
def fa_end(ctx: JobContext) -> Dict[str, Any]:
    from services.timestamp import end_free_agency
    return end_free_agency()


@job("fa_advance_phases", title="FA auctions: advance in-season phases",
     description="Runs services.fa_auction.advance_auction_phases for the league year (normally part of advance_week).",
     group="market",
     params={"league_year_id": P_LYID, "current_week": {"type": "int", "default": 0, "label": "Current week"}})
def fa_advance_phases(ctx: JobContext) -> Dict[str, Any]:
    from services.fa_auction import advance_auction_phases
    with ctx.engine.begin() as conn:
        return advance_auction_phases(conn, int(ctx.params.get("current_week") or 0), ctx.league_year_id())


@job("recruiting_advance_week", title="Recruiting: advance week",
     description="Advances college recruiting by N weeks (20 total; week 0→1 computes rankings, 19→20 assigns everyone).",
     phases=["RECRUITING"], group="market",
     params={"league_year_id": P_LYID, "times": {"type": "int", "default": 1, "label": "Weeks to advance"}})
def recruiting_advance_week(ctx: JobContext) -> Dict[str, Any]:
    from services.recruiting import advance_recruiting_week
    lyid = ctx.league_year_id()
    n = max(1, int(ctx.params.get("times") or 1))
    results = []
    for i in range(n):
        ctx.check_cancel()
        ctx.set_progress(i, n, f"recruiting week advance {i + 1}/{n}")
        with ctx.engine.begin() as conn:
            r = advance_recruiting_week(conn, lyid)
        results.append(r)
        ctx.log(f"recruiting advanced: {r.get('week', r)}")
        if r.get("complete") or r.get("is_complete"):
            break
    ctx.set_progress(n, n, "done")
    return {"advances": len(results), "last": results[-1] if results else None}


@job("ifa_advance_week", title="IFA: advance week",
     description="Advances the international signing period by one week.",
     group="market", params={"league_year_id": P_LYID})
def ifa_advance_week(ctx: JobContext) -> Dict[str, Any]:
    from services.ifa_signing import advance_ifa_week
    with ctx.engine.begin() as conn:
        return advance_ifa_week(conn, ctx.league_year_id())


@job("draft_auto_pick_expired", title="Draft: auto-pick expired picks",
     description="Runs the pick-clock expiry check once (the draft clock thread does this every 3s when live).",
     phases=["DRAFT"], group="market", params={"league_year_id": P_LYID})
def draft_auto_pick_expired(ctx: JobContext) -> Dict[str, Any]:
    from services.draft import check_timer_expiry
    with ctx.engine.begin() as conn:
        made = check_timer_expiry(conn, ctx.league_year_id())
    return {"auto_picked": len(made), "picks": made}


# ---------------------------------------------------------------------------
# Financials
# ---------------------------------------------------------------------------
@job("books_run_week", title="Books: run week", group="finance",
     description="Weekly financial books for a week (claim-guarded via game_weeks.books_run_at).",
     params={"league_year": {"type": "int", "label": "League year (e.g. 2026)", "optional": True},
             "week_index": {"type": "int", "label": "Week index", "optional": True}})
def books_run_week(ctx: JobContext) -> Dict[str, Any]:
    from financials.books import run_week_books
    week = ctx.params.get("week_index") or ctx.timestamp().get("Week")
    return run_week_books(ctx.engine, ctx.league_year(), int(week))


@job("books_playoff_revenue", title="Books: playoff revenue", group="finance",
     description="One-shot playoff revenue distribution for the league year (claims league_years.playoff_revenue_run_at).",
     params={"league_year": {"type": "int", "label": "League year (e.g. 2026)", "optional": True}})
def books_playoff_revenue(ctx: JobContext) -> Dict[str, Any]:
    from financials.books import process_playoff_revenue
    return process_playoff_revenue(ctx.engine, ctx.league_year())


@job("books_year_end_interest", title="Books: year-end interest", group="finance",
     description="One-shot year-end interest (claims league_years.interest_run_at). Run after all other ledger entries.",
     params={"league_year": {"type": "int", "label": "League year (e.g. 2026)", "optional": True}})
def books_year_end_interest(ctx: JobContext) -> Dict[str, Any]:
    from financials.books import run_year_end_interest
    return run_year_end_interest(ctx.engine, ctx.league_year())


@job("books_year_start", title="Books: year-start", group="finance",
     description="Year-start financial books for the league year.",
     params={"league_year": {"type": "int", "label": "League year (e.g. 2027)", "optional": True}})
def books_year_start(ctx: JobContext) -> Dict[str, Any]:
    from financials.books import run_year_start_books
    return run_year_start_books(ctx.engine, ctx.league_year())


@job("init_next_league_year", title="Initialize next league year", group="rollover",
     description="Creates the Y+1 league_years row and game_weeks. Cannot be re-run.", dangerous=True,
     params={"league_year": {"type": "int", "label": "Current league year (e.g. 2026)", "optional": True}})
def init_next_league_year(ctx: JobContext) -> Dict[str, Any]:
    from financials.books import initialize_next_league_year
    return initialize_next_league_year(ctx.engine, ctx.league_year())


# ---------------------------------------------------------------------------
# Rollover (long-running) jobs
# ---------------------------------------------------------------------------
@job("end_season", title="End season", group="rollover", long_running=True, dangerous=True,
     description="One-shot season rollover: contracts, graduation/retirements, draft pool, training camp, "
                 "progression, new amateur classes, Y+1 tables, calendar → offseason. ~2–3 minutes.",
     phases=["REGULAR_SEASON"],
     params={"league_year_id": P_LYID,
             "force": {"type": "bool", "default": False, "label": "Force (skip World Series check)"}})
def end_season_job(ctx: JobContext) -> Dict[str, Any]:
    from services.timestamp import end_regular_season
    ctx.set_progress(0, 1, "end_regular_season running")
    res = end_regular_season(ctx.league_year_id(), force=bool(ctx.params.get("force")))
    ctx.set_progress(1, 1, "done")
    return res


@job("archive_season", title="Archive season", group="rollover", long_running=True, dangerous=True,
     description="Deletes per-game ephemeral data (lines, PBP, substitutions, fatigue, ledger detail) for a "
                 "finished league year. Irreversible unless dry_run. ~4–5 minutes.",
     params={"league_year_id": {"type": "int", "label": "League year ID to archive"},
             "dry_run": {"type": "bool", "default": True, "label": "Dry run (count only)"}})
def archive_season_job(ctx: JobContext) -> Dict[str, Any]:
    from services.season_archive import archive_season
    ctx.set_progress(0, 1, "archiving")
    res = archive_season(ctx.engine, league_year_id=int(ctx.params["league_year_id"]),
                         dry_run=bool(ctx.params.get("dry_run", True)))
    ctx.set_progress(1, 1, "done")
    return res


@job("schedule_generate", title="Generate schedule", group="rollover", long_running=True,
     description="Generates the gamelist schedule for one or more levels of a league year.",
     params={"league_year": {"type": "int", "label": "League year (e.g. 2027)"},
             "levels": {"type": "list[int]", "default": [9, 8, 7, 6, 5, 3], "label": "Levels"},
             "start_week": {"type": "int", "default": 1, "label": "Start week"},
             "clear_existing": {"type": "bool", "default": False, "label": "Clear existing games first"}})
def schedule_generate_job(ctx: JobContext) -> Dict[str, Any]:
    from services.schedule_generator import (
        LEVEL_MLB, LEVEL_COLLEGE, MINOR_LEVELS,
        generate_mlb_schedule, generate_college_schedule, generate_minor_league_schedule,
    )
    year = int(ctx.params["league_year"])
    levels = [int(x) for x in (ctx.params.get("levels") or [9, 8, 7, 6, 5, 3])]
    start_week = int(ctx.params.get("start_week") or 1)
    clear = bool(ctx.params.get("clear_existing"))
    out: Dict[str, Any] = {}
    for i, lvl in enumerate(levels):
        ctx.check_cancel()
        ctx.set_progress(i, len(levels), f"generating level {lvl}")
        if lvl == LEVEL_MLB:
            out[str(lvl)] = generate_mlb_schedule(ctx.engine, year, clear_existing=clear)
        elif lvl == LEVEL_COLLEGE:
            out[str(lvl)] = generate_college_schedule(ctx.engine, year, start_week=start_week, clear_existing=clear)
        elif lvl in MINOR_LEVELS:
            out[str(lvl)] = generate_minor_league_schedule(ctx.engine, year, lvl, start_week=start_week, clear_existing=clear)
        else:
            out[str(lvl)] = {"error": f"level {lvl} has no generator"}
        ctx.log(f"level {lvl}: {str(out[str(lvl)])[:200]}")
    ctx.set_progress(len(levels), len(levels), "done")
    return out


@job("start_new_season", title="Start new season", group="rollover", dangerous=True,
     description="Runs year-start books, refreshes listed positions, sets week 1. Requires schedule + FA/draft/recruiting closed.",
     phases=["OFFSEASON"],
     params={"league_year_id": {"type": "int", "label": "New league year ID"}})
def start_new_season_job(ctx: JobContext) -> Dict[str, Any]:
    from services.timestamp import start_new_season
    return start_new_season(int(ctx.params["league_year_id"]))


@job("training_camp_apply", title="Apply preseason training camp", group="rollover", dangerous=True,
     description="Replays this offseason's progression dice at the camp grade for every focus skill, "
                 "records results and locks focus. One-shot per season; run before opening day.",
     params={"league_year_id": {"type": "int", "label": "Camp league year ID (the season about to start)"}})
def training_camp_apply_job(ctx: JobContext) -> Dict[str, Any]:
    from services.training_camp import apply_camp
    with ctx.engine.begin() as conn:
        return apply_camp(conn, int(ctx.params["league_year_id"]))


@job("phase_action", title="Phase action (start/end FA, draft, recruiting)", group="rollover",
     description="Runs one of the timestamp phase transitions.",
     params={"action": {"type": "str", "label": "Action",
                        "choices": ["start_free_agency", "end_free_agency", "start_draft", "end_draft",
                                    "start_recruiting", "end_recruiting"]}})
def phase_action_job(ctx: JobContext) -> Dict[str, Any]:
    from services import timestamp as ts_svc
    action = str(ctx.params.get("action") or "")
    allowed = {"start_free_agency", "end_free_agency", "start_draft", "end_draft", "start_recruiting", "end_recruiting"}
    if action not in allowed:
        raise ValueError(f"action must be one of {sorted(allowed)}")
    res = getattr(ts_svc, action)()
    return res if isinstance(res, dict) else {"ok": bool(res), "action": action}


# ---------------------------------------------------------------------------
# Digests (read-only, feed the command center)
# ---------------------------------------------------------------------------
@job("trade_queue_digest", title="Trade queue digest", group="digest",
     description="Counts trade proposals awaiting admin approval.")
def trade_queue_digest(ctx: JobContext) -> Dict[str, Any]:
    from sqlalchemy import text
    with ctx.engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM trade_proposals WHERE status = 'counterparty_accepted'")).scalar()
    return {"awaiting_approval": int(n or 0)}


@job("offseason_checklist_step", title="Run an offseason checklist step", group="rollover",
     description="Runs the server-described action of one checklist step (same as the Run button).",
     params={"league_year_id": P_LYID, "step_key": {"type": "str", "label": "Step key"}})
def offseason_checklist_step(ctx: JobContext) -> Dict[str, Any]:
    from admin import _build_offseason_checklist
    key = str(ctx.params.get("step_key") or "")
    with ctx.engine.connect() as conn:
        data = _build_offseason_checklist(conn, ctx.league_year_id())
    step = next((s for s in data.get("steps", []) if s.get("key") == key), None)
    if not step:
        raise ValueError(f"unknown step '{key}'")
    if step.get("done") is True:
        ctx.skip("step already done")
    a = step.get("action")
    if not a or a.get("blocked"):
        ctx.skip(a.get("blocked") if a else "step has no runnable action")
    mapping = {
        "/api/v1/awards/sync-postseason": ("awards", None),
        "/admin/run-playoff-revenue": ("books_playoff_revenue", None),
        "/admin/run-year-end-interest": ("books_year_end_interest", None),
        "/admin/initialize-next-league-year": ("init_next_league_year", None),
    }
    url = a.get("url", "")
    if url == "/api/v1/awards/sync-postseason":
        from services.awards import sync_postseason_awards
        with ctx.engine.begin() as conn:
            return sync_postseason_awards(conn, ctx.league_year_id())
    if url == "/admin/training-camp/apply":
        from services.training_camp import apply_camp
        with ctx.engine.begin() as conn:
            return apply_camp(conn, int((a.get("body") or {})["league_year_id"]))
    target = mapping.get(url)
    if not target:
        raise ValueError(f"step action {url} has no job mapping")
    sub = get_job(target[0])
    sub_params = apply_defaults(sub, {"league_year": (a.get("body") or {}).get("league_year")})
    sub_ctx = JobContext(ctx.engine, sub_params, run_id=ctx.run_id, log_fn=ctx._log_fn,
                         progress_fn=ctx._progress_fn, cancel_fn=ctx._cancel_fn)
    return sub.fn(sub_ctx)
