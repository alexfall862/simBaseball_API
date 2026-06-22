"""Bulk game-data export helpers.

Powers the /games/export* suite (see docs/bulk_export_design.md). All output is
built from explicit ALLOWLISTS — engine-internal columns (stamina_cost,
league_year_id, raw JSON blobs, RNG seeds) are never selected — so nothing
player-private can leak. Incremental pulls use game_id as a gap-free watermark.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text as sa_text


# --- Allowlisted columns per source (NEVER add stamina_cost / league_year_id) ---

_BAT_BASE = [
    "at_bats", "runs", "hits", "doubles_hit", "triples", "home_runs",
    "inside_the_park_hr", "rbi", "walks", "hbp", "strikeouts",
    "stolen_bases", "caught_stealing", "plate_appearances",
]
_BAT_OPT = [  # added by migrations/add_engine_expansion_columns.sql
    "sacrifice_flies", "gidp", "ground_balls", "fly_balls", "popups",
    "contact_barrel", "contact_solid", "contact_flare", "contact_burner",
    "contact_under", "contact_topped", "contact_weak",
]
_PIT_BASE = [
    "pitch_appearance_order", "games_started", "win", "loss", "save_recorded",
    "hold", "blown_save", "quality_start", "innings_pitched_outs",
    "hits_allowed", "runs_allowed", "earned_runs", "walks", "strikeouts",
    "home_runs_allowed", "inside_the_park_hr_allowed", "pitches_thrown",
    "balls", "strikes", "hbp", "wildpitches",
]
_PIT_OPT = [
    "batters_faced", "sacrifice_flies_allowed", "gidp_induced",
    "ground_balls_allowed", "fly_balls_allowed", "popups_allowed",
    "inherited_runners", "inherited_runners_scored",
    "contact_barrel", "contact_solid", "contact_flare", "contact_burner",
    "contact_under", "contact_topped", "contact_weak",
]
_FLD_BASE = ["position_code", "innings", "putouts", "assists", "errors"]
_FLD_OPT = ["double_plays"]
_SUB_COLS = [
    "inning", "half", "sub_type", "new_position", "entry_score_diff",
    "entry_runners_on", "entry_inning", "entry_outs", "entry_is_save_situation",
]


# --- Filters / where-clause -------------------------------------------------

def build_where(filters: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Build the shared game_results WHERE clause (no since — the caller pages
    on game_id). game_type defaults to 'regular'; pass 'all' for every type."""
    clauses = ["1=1"]
    params: Dict[str, Any] = {}
    if filters.get("season"):
        clauses.append("gr.season = :season")
        params["season"] = filters["season"]
    if filters.get("season_week"):
        clauses.append("gr.season_week = :sw")
        params["sw"] = filters["season_week"]
    if filters.get("league_level"):
        clauses.append("gr.league_level = :ll")
        params["ll"] = filters["league_level"]
    if filters.get("team_id"):
        clauses.append("(gr.home_team_id = :tid OR gr.away_team_id = :tid)")
        params["tid"] = filters["team_id"]
    gt = filters.get("game_type", "regular")
    if gt and str(gt).lower() != "all":
        clauses.append("gr.game_type = :gt")
        params["gt"] = gt
    return " AND ".join(clauses), params


def export_cursor(engine, filters: Dict[str, Any]) -> Dict[str, Any]:
    """Cheap 'is there new data?' check — MAX(game_id) and COUNT for the filter."""
    where, params = build_where(filters)
    with engine.connect() as conn:
        row = conn.execute(sa_text(
            f"SELECT MAX(gr.game_id) AS mx, COUNT(*) AS cnt "
            f"FROM game_results gr WHERE {where}"
        ), params).mappings().first()
    mx = int(row["mx"]) if row and row["mx"] is not None else 0
    cnt = int(row["cnt"]) if row else 0
    return {"max_game_id": mx, "count": cnt}


# --- Column presence (migration-added columns may not be live) --------------

def optional_columns(conn, table: str, candidates: List[str]) -> List[str]:
    rows = conn.execute(sa_text(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
    ), {"t": table}).all()
    existing = {r[0] for r in rows}
    return [c for c in candidates if c in existing]


def _in_clause(ids: List[int], prefix: str) -> Tuple[str, Dict[str, Any]]:
    ph = ", ".join(f":{prefix}{i}" for i in range(len(ids)))
    return ph, {f"{prefix}{i}": gid for i, gid in enumerate(ids)}


def _ip_str(outs) -> Optional[str]:
    if outs is None:
        return None
    outs = int(outs)
    return f"{outs // 3}.{outs % 3}"


def _name(r) -> str:
    return f"{r['firstName']} {r['lastName']}"


# --- Per-chunk line fetches -------------------------------------------------

def _fetch_lines(conn, table: str, cols: List[str], gids: List[int],
                 order_extra: str) -> Dict[int, List[dict]]:
    ph, params = _in_clause(gids, "g")
    col_sql = ", ".join(f"t.{c}" for c in cols)
    rows = conn.execute(sa_text(f"""
        SELECT t.game_id, t.player_id, t.team_id, p.firstName, p.lastName, {col_sql}
        FROM {table} t
        JOIN simbbPlayers p ON p.id = t.player_id
        WHERE t.game_id IN ({ph})
        ORDER BY t.game_id, t.team_id, {order_extra}
    """), params).mappings().all()
    out: Dict[int, List[dict]] = {}
    for r in rows:
        out.setdefault(int(r["game_id"]), []).append(r)
    return out


def _fetch_subs(conn, gids: List[int]) -> Dict[int, List[dict]]:
    ph, params = _in_clause(gids, "g")
    col_sql = ", ".join(f"gs.{c}" for c in _SUB_COLS)
    rows = conn.execute(sa_text(f"""
        SELECT gs.game_id, {col_sql},
               gs.player_in_id, pin.firstName AS in_first, pin.lastName AS in_last,
               gs.player_out_id, pout.firstName AS out_first, pout.lastName AS out_last
        FROM game_substitutions gs
        JOIN simbbPlayers pin ON pin.id = gs.player_in_id
        JOIN simbbPlayers pout ON pout.id = gs.player_out_id
        WHERE gs.game_id IN ({ph})
        ORDER BY gs.game_id, gs.inning, gs.id
    """), params).mappings().all()
    out: Dict[int, List[dict]] = {}
    for r in rows:
        out.setdefault(int(r["game_id"]), []).append(r)
    return out


# --- Row formatters (allowlist) ---------------------------------------------

def _fmt_line(r, cols: List[str]) -> dict:
    d = {"player_id": int(r["player_id"]), "team_id": int(r["team_id"]),
         "name": _name(r)}
    for c in cols:
        v = r[c]
        d[c] = int(v) if isinstance(v, (int,)) or (isinstance(v, bool)) else v
    if "innings_pitched_outs" in d and d["innings_pitched_outs"] is not None:
        d["innings_pitched"] = _ip_str(d["innings_pitched_outs"])
    return d


def _fmt_sub(r) -> dict:
    return {
        "inning": r["inning"], "half": r["half"], "sub_type": r["sub_type"],
        "player_in_id": int(r["player_in_id"]),
        "player_in_name": f"{r['in_first']} {r['in_last']}",
        "player_out_id": int(r["player_out_id"]),
        "player_out_name": f"{r['out_first']} {r['out_last']}",
        "new_position": r["new_position"],
        "entry_score_diff": r["entry_score_diff"],
        "entry_runners_on": r["entry_runners_on"],
        "entry_inning": r["entry_inning"], "entry_outs": r["entry_outs"],
        "entry_is_save_situation": r["entry_is_save_situation"],
    }


def _split_home_away(lines: List[dict], home_tid: int, away_tid: int):
    home = [x for x in lines if x.get("team_id") == home_tid]
    away = [x for x in lines if x.get("team_id") == away_tid]
    return home, away


def _linescore_innings(pbp_json) -> Optional[List[Dict[str, int]]]:
    """Per-inning runs from PBP (MLB only). None when no PBP stored."""
    if not pbp_json:
        return None
    try:
        plays = json.loads(pbp_json) if isinstance(pbp_json, str) else pbp_json
    except (ValueError, TypeError):
        return None
    end = {}
    for pl in plays:
        inn, half = pl.get("Inning"), pl.get("Inning Half")
        if inn is None or half is None:
            continue
        end[(inn, half)] = (int(pl.get("Home Score", 0)), int(pl.get("Away Score", 0)))
    if not end:
        return None
    max_inn = max(k[0] for k in end)
    innings, prev_h, prev_a = [], 0, 0
    for i in range(1, max_inn + 1):
        a = prev_a
        if (i, "Top") in end:
            a = end[(i, "Top")][1]
        h = prev_h
        if (i, "Bottom") in end:
            h = end[(i, "Bottom")][0]
        innings.append({"home": h - prev_h, "away": a - prev_a})
        prev_h, prev_a = h, a
    return innings


def _assemble_game(g, bat, pit, fld, subs) -> dict:
    gid = int(g["game_id"])
    home_tid, away_tid = int(g["home_team_id"]), int(g["away_team_id"])
    bat_cols = list(g["_bat_cols"]); pit_cols = list(g["_pit_cols"]); fld_cols = list(g["_fld_cols"])

    b = [_fmt_line(r, bat_cols) for r in bat.get(gid, [])]
    p = [_fmt_line(r, pit_cols) for r in pit.get(gid, [])]
    f = [_fmt_line(r, fld_cols) for r in fld.get(gid, [])]
    s = [_fmt_sub(r) for r in subs.get(gid, [])]

    bh, ba = _split_home_away(b, home_tid, away_tid)
    ph, pa = _split_home_away(p, home_tid, away_tid)
    fh, fa = _split_home_away(f, home_tid, away_tid)

    def _sum(lines, key):
        return sum(int(x.get(key) or 0) for x in lines)

    innings = _linescore_innings(g.get("play_by_play_json"))
    home_score, away_score = int(g["home_score"]), int(g["away_score"])

    return {
        "game_id": gid,
        "season": int(g["season"]) if g["season"] is not None else None,
        "season_week": int(g["season_week"]) if g["season_week"] is not None else None,
        "season_subweek": g["season_subweek"],
        "league_level": int(g["league_level"]) if g["league_level"] is not None else None,
        "game_type": g["game_type"],
        "completed_at": str(g["completed_at"]) if g["completed_at"] else None,
        "venue": g["venue"],
        "home_team": {
            "id": home_tid, "abbrev": g["home_abbrev"],
            "name": (f"{g['home_city']} {g['home_name']}").strip(),
            "score": home_score, "won": int(g["winning_team_id"] or 0) == home_tid,
        },
        "away_team": {
            "id": away_tid, "abbrev": g["away_abbrev"],
            "name": (f"{g['away_city']} {g['away_name']}").strip(),
            "score": away_score, "won": int(g["winning_team_id"] or 0) == away_tid,
        },
        "game_outcome": g["game_outcome"],
        "linescore": {
            "innings": innings,
            "home": {"R": home_score, "H": _sum(bh, "hits"), "E": _sum(fa, "errors")},
            "away": {"R": away_score, "H": _sum(ba, "hits"), "E": _sum(fh, "errors")},
        },
        "batting": {"home": bh, "away": ba},
        "pitching": {"home": ph, "away": pa},
        "fielding": {"home": fh, "away": fa},
        "substitutions": s,
    }


def iter_boxscore_games(engine, *, filters: Dict[str, Any], since: int,
                        limit: int, chunk: int = 200) -> Iterable[dict]:
    """Yield one structured boxscore dict per game, in game_id ASC order,
    paging internally so memory and IN-list sizes stay bounded even uncapped."""
    where, params = build_where(filters)
    after = since or 0
    emitted = 0
    bat_cols = pit_cols = fld_cols = None

    while True:
        if limit and limit > 0 and emitted >= limit:
            break
        take = chunk
        if limit and limit > 0:
            take = min(chunk, limit - emitted)

        with engine.connect() as conn:
            if bat_cols is None:
                bat_cols = _BAT_BASE + optional_columns(conn, "game_batting_lines", _BAT_OPT)
                pit_cols = _PIT_BASE + optional_columns(conn, "game_pitching_lines", _PIT_OPT)
                fld_cols = _FLD_BASE + optional_columns(conn, "game_fielding_lines", _FLD_OPT)

            games = conn.execute(sa_text(f"""
                SELECT gr.game_id, gr.season, gr.season_week, gr.season_subweek,
                       gr.league_level, gr.game_type, gr.completed_at,
                       gr.home_team_id, gr.away_team_id, gr.home_score, gr.away_score,
                       gr.winning_team_id, gr.game_outcome, gr.play_by_play_json,
                       ht.team_abbrev AS home_abbrev, ht.team_city AS home_city,
                       ht.team_name AS home_name, ht.ballpark_name AS venue,
                       at2.team_abbrev AS away_abbrev, at2.team_city AS away_city,
                       at2.team_name AS away_name
                FROM game_results gr
                JOIN teams ht ON ht.id = gr.home_team_id
                JOIN teams at2 ON at2.id = gr.away_team_id
                WHERE {where} AND gr.game_id > :after
                ORDER BY gr.game_id ASC
                LIMIT :take
            """), {**params, "after": after, "take": take}).mappings().all()

            if not games:
                break

            gids = [int(g["game_id"]) for g in games]
            bat = _fetch_lines(conn, "game_batting_lines", bat_cols, gids,
                               "t.batting_order, t.id")
            pit = _fetch_lines(conn, "game_pitching_lines", pit_cols, gids,
                               "t.pitch_appearance_order, t.id")
            fld = _fetch_lines(conn, "game_fielding_lines", fld_cols, gids, "t.id")
            subs = _fetch_subs(conn, gids)

        for g in games:
            gm = dict(g)
            gm["_bat_cols"] = bat_cols
            gm["_pit_cols"] = pit_cols
            gm["_fld_cols"] = fld_cols
            yield _assemble_game(gm, bat, pit, fld, subs)
            after = int(g["game_id"])
            emitted += 1

        if len(games) < take:
            break
