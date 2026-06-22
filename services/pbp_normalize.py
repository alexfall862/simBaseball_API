"""
Play-by-play normalization (pure transform, normalize-on-read).

The Rust engine emits a raw play-by-play array where each element is one
*action* -- a pitch, a pickoff attempt, or a steal attempt -- carrying ~66
keys with inconsistent naming (space-separated PascalCase mixed with
``Is_*``/``Pre_*``), ``"None"`` sentinel strings, stringified Python lists
(some malformed/unparseable), and the full fielding roster repeated on every
action.

This module turns that raw array into a clean, versioned v2 shape with real
``null``, real arrays, ``snake_case`` keys, and a generated ``description`` per
at-bat. See ``docs/play_by_play_schema.md`` (sections 2-3) for the authoritative
raw schema and target shape.

SAFETY: the raw actions also carry engine-internal fields (raw player ratings,
probability tables, RNG, internal model floats). This module reads ONLY an
explicit allowlist of keys (see the ``_ALLOWED_*`` sets / the per-field reads in
``normalize_action``) and never copies anything else through to the output. It
is pure stdlib (``ast``/``json`` only), does no DB or Flask work, and must never
raise on real engine data -- every parse is wrapped in a safe fallback.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 2

# --------------------------------------------------------------------------- #
# Allowlist of raw keys we are permitted to read.
#
# This is the security boundary. NEVER read a raw key that is not in one of
# these sets. In particular NEVER read: Interaction_Data, At_Bat_Modifiers,
# Timing_Diagnostics, Pre_R1, Pre_R2, Pre_R3, "Catch Probability" -- they carry
# raw ratings, probability tables, RNG, and internal model floats.
# --------------------------------------------------------------------------- #

_ALLOWED_CONTEXT_KEYS = frozenset({
    "ID", "Inning", "Inning Half", "Home Team", "Away Team",
    "Home Score", "Away Score", "Ball Count", "Strike Count",
    "Out Count", "Outs this Action", "Pre_Outs",
})

_ALLOWED_PARTICIPANT_KEYS = frozenset({
    "Batter", "Pitcher", "Catcher", "First Base", "Second Base", "Third Base",
    "Shortstop", "Left Field", "Center Field", "Right Field",
    "Targeted Defender",
})

_ALLOWED_OUTCOME_KEYS = frozenset({
    "Outcomes", "Batted Ball", "Air or Ground", "Hit Depth", "Hit Direction",
    "Hit Situation", "Defensive Outcome", "Defensive Actions", "Error List",
    "Error_Count",
})

_ALLOWED_BASERUNNER_KEYS = frozenset({
    "On First", "On Second", "On Third", "Home",
    "Runners_Scored", "Runners_Scored_IDs",
})

# Flags: every Is_* key plus these two are allowed.
_ALLOWED_FLAG_KEYS = frozenset({"AB_Over", "WP_Descriptions"})


def _is_allowed_key(key: str) -> bool:
    """True if ``key`` is a raw key this module is permitted to read."""
    if key in _ALLOWED_CONTEXT_KEYS:
        return True
    if key in _ALLOWED_PARTICIPANT_KEYS:
        return True
    if key in _ALLOWED_OUTCOME_KEYS:
        return True
    if key in _ALLOWED_BASERUNNER_KEYS:
        return True
    if key in _ALLOWED_FLAG_KEYS:
        return True
    return isinstance(key, str) and key.startswith("Is_")


def _get(raw: Dict[str, Any], key: str) -> Any:
    """Read a raw key, but only if it is on the allowlist (else None)."""
    if not _is_allowed_key(key):
        return None
    return raw.get(key)


# --------------------------------------------------------------------------- #
# Low-level cleaners / parsers
# --------------------------------------------------------------------------- #

def none_to_null(v: Any) -> Any:
    """
    Map the engine's ``"None"``/``""`` sentinel strings to real ``None``.

    Passthrough for everything else. Applied to all sentinel-string fields and
    to ``Targeted Defender``.
    """
    if isinstance(v, str) and v.strip() in ("None", "none", "NONE", ""):
        return None
    return v


def _player(obj: Any) -> Optional[Dict[str, Any]]:
    """Normalize a raw ``{player_id, player_name}`` (or sentinel) -> {id, name}."""
    obj = none_to_null(obj)
    if not isinstance(obj, dict):
        return None
    pid = obj.get("player_id")
    if pid is None:
        return None
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    return {"id": pid, "name": obj.get("player_name")}


def parse_outcomes(raw: Any) -> Optional[Dict[str, Optional[str]]]:
    """
    Parse the ``Outcomes`` field.

    ``Outcomes`` is a stringified Python list of the form
    ``"['Ball', 'Looking', 'Fastball']"`` meaning
    ``[pitch_result, swing/look, pitch_type]``.

    Returns ``{"result": ..., "swing": ..., "pitch": ...}`` on success, or
    ``None`` if the value is the ``"None"`` sentinel, empty, or malformed.
    Never raises.
    """
    raw = none_to_null(raw)
    if raw is None:
        return None

    parsed: Any
    if isinstance(raw, (list, tuple)):
        parsed = list(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            parsed = ast.literal_eval(s)
        except (ValueError, SyntaxError, TypeError):
            return None
    else:
        return None

    if not isinstance(parsed, (list, tuple)) or not parsed:
        return None

    parsed = list(parsed)

    def _at(i: int) -> Optional[str]:
        if i < len(parsed) and parsed[i] is not None:
            val = str(parsed[i]).strip()
            return val or None
        return None

    return {"result": _at(0), "swing": _at(1), "pitch": _at(2)}


def parse_string_list(raw: Any) -> List[str]:
    """
    Safe parser for stringified Python lists such as ``Defensive Actions`` and
    the frequently *malformed* ``Error List``.

    Examples handled:
      * proper list (already parsed)              -> stringified items
      * valid repr ``"['home run']"``             -> ``ast.literal_eval``
      * malformed repr with unquoted elements,
        e.g. ``"['x error!', starter Max Knox]"`` -> best-effort comma split

    Never raises; returns ``[]`` on hopeless / empty / sentinel input.
    """
    raw = none_to_null(raw)
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(v) for v in raw]
    if not isinstance(raw, str):
        return [str(raw)]

    s = raw.strip()
    if not s:
        return []
    if not (s.startswith("[") and s.endswith("]")):
        # Not a list literal at all -- treat the whole thing as one item.
        return [s]

    try:
        parsed = ast.literal_eval(s)
        if isinstance(parsed, (list, tuple)):
            return [str(v) for v in parsed]
        return [str(parsed)]
    except (ValueError, SyntaxError, TypeError):
        # Malformed (unquoted tokens). Best-effort: strip the brackets, split on
        # commas, and strip surrounding quotes/whitespace from each fragment.
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip().strip("'\"").strip() for p in inner.split(",")]
        return [p for p in parts if p]


# --------------------------------------------------------------------------- #
# Action classification & result enum
# --------------------------------------------------------------------------- #

def classify_action(raw: Dict[str, Any]) -> str:
    """Return the action kind: ``pickoff`` | ``steal`` | ``pitch``."""
    if _get(raw, "Is_Pickoff"):
        return "pickoff"
    if _get(raw, "Is_StealAttempt"):
        return "steal"
    return "pitch"


# Raw "Defensive Outcome" -> normalized hit result enum (snake_case).
_HIT_RESULTS = {
    "single": "single",
    "double": "double",
    "triple": "triple",
    "homerun": "home_run",
    "inside_the_park_hr": "inside_the_park_hr",
}


def _result_enum(raw: Dict[str, Any], kind: str) -> Optional[str]:
    """
    Single snake_case result enum derived from ``Defensive Outcome`` plus the
    ``Is_*`` flags.

    Returns ``None`` for a pitch that does not end the at-bat (a mid-count
    pitch). Pickoff/steal actions always resolve from ``Defensive Outcome``.
    """
    dout = none_to_null(_get(raw, "Defensive Outcome"))

    if kind in ("steal", "pickoff"):
        if dout:
            return str(dout).replace(" ", "_").lower()
        return None

    # Pitch: only a plate result when the at-bat ends.
    if not _get(raw, "AB_Over"):
        return None
    if _get(raw, "Is_HBP"):
        return "hbp"
    if _get(raw, "Is_Walk"):
        return "walk"
    if _get(raw, "Is_Strikeout"):
        return "strikeout"
    if dout in _HIT_RESULTS:
        return _HIT_RESULTS[dout]
    if dout == "out":
        aog = none_to_null(_get(raw, "Air or Ground"))
        if aog == "ground":
            return "groundout"
        if aog == "air":
            return "flyout"
        return "out"
    if dout:
        return str(dout).replace(" ", "_").lower()
    return None


def _errors(raw: Dict[str, Any]) -> List[str]:
    """Clean error string list parsed/repaired from Error List + Error_Count."""
    errs = parse_string_list(_get(raw, "Error List"))
    # Degrade silently to [] -- never propagate a broken string.
    return errs


def _runner_for_baserunning(raw: Dict[str, Any], kind: str) -> Optional[Dict[str, Any]]:
    """
    Resolve the runner (the actor) for a pickoff/steal action.

    The raw entry carries the ``Batter`` at the plate, NOT the runner being
    thrown out / stealing, and ``Pre_R1/R2/R3`` are not on the allowlist (they
    are stripped before storage and carry no value we may read). We infer the
    actor from the post-action base state where reasonable:

      * a successful steal leaves the runner on the base they reached;
      * for the common case (steal/pickoff of 2nd), the actor is the runner now
        (or formerly) on first.

    This is a best-effort heuristic; when no defensible inference exists we fall
    back to ``None`` rather than fabricate an identity.

    TODO(engine, docs/play_by_play_schema.md S5 #6): have the engine emit the
    actor's player_id directly so this inference can be removed.
    """
    on_first = _player(_get(raw, "On First"))
    on_second = _player(_get(raw, "On Second"))
    on_third = _player(_get(raw, "On Third"))
    dout = none_to_null(_get(raw, "Defensive Outcome"))
    success = bool(_get(raw, "Is_StealSuccess")) or dout == "stolen base"

    if kind == "steal" and success:
        # Runner reached the next base; prefer the deepest occupied base.
        return on_second or on_third or on_first
    # Caught stealing / unsuccessful pickoff / failed steal: the lead trailing
    # runner (typically on first) is the most defensible actor.
    return on_first or on_second or on_third


# --------------------------------------------------------------------------- #
# Normalize one raw action -> one v2 action
# --------------------------------------------------------------------------- #

def normalize_action(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turn one raw action dict into a clean, flat v2 action (snake_case, real
    null/arrays), reading ONLY allowlisted keys, tagged with ``kind``.
    """
    if not isinstance(raw, dict):
        raw = {}

    kind = classify_action(raw)
    half_raw = none_to_null(_get(raw, "Inning Half"))
    half = half_raw.lower() if isinstance(half_raw, str) else None

    action: Dict[str, Any] = {
        "id": _get(raw, "ID"),
        "kind": kind,
        "inning": _get(raw, "Inning"),
        "half": half,
        "outs_before": none_to_null(_get(raw, "Pre_Outs")),
        "outs_recorded": _get(raw, "Outs this Action") or 0,
        "count": {
            "balls": _get(raw, "Ball Count"),
            "strikes": _get(raw, "Strike Count"),
        },
        "batter": _player(_get(raw, "Batter")),
        "pitcher": _player(_get(raw, "Pitcher")),
        "result": _result_enum(raw, kind),
        "runs_scored": _get(raw, "Runners_Scored") or 0,
        "runs_scored_ids": list(_get(raw, "Runners_Scored_IDs") or []),
        "runners_after": {
            "1B": _player(_get(raw, "On First")),
            "2B": _player(_get(raw, "On Second")),
            "3B": _player(_get(raw, "On Third")),
        },
        "score_after": {
            "home": _get(raw, "Home Score"),
            "away": _get(raw, "Away Score"),
        },
        "ab_over": bool(_get(raw, "AB_Over")),
    }

    if action["outs_before"] is None:
        action["outs_before"] = _get(raw, "Out Count")

    if kind == "pitch":
        outcomes = parse_outcomes(_get(raw, "Outcomes"))
        action["pitch"] = outcomes  # {result, swing, pitch} or None
        if _get(raw, "Is_InPlay"):
            action["contact"] = {
                "batted_ball": none_to_null(_get(raw, "Batted Ball")),
                "air_or_ground": none_to_null(_get(raw, "Air or Ground")),
                "hit_depth": none_to_null(_get(raw, "Hit Depth")),
                "hit_direction": none_to_null(_get(raw, "Hit Direction")),
                "hit_situation": none_to_null(_get(raw, "Hit Situation")),
                "fielder": _player(_get(raw, "Targeted Defender")),
                "errors": _errors(raw),
            }
        else:
            action["contact"] = None
    else:
        # Baserunning action: actor is the runner, not the batter at the plate.
        action["runner"] = _runner_for_baserunning(raw, kind)
        action["contact"] = None

    return action


# --------------------------------------------------------------------------- #
# At-bat grouping
# --------------------------------------------------------------------------- #

def group_at_bats(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group normalized actions into at-bats.

    An at-bat is an ordered stream of events: pitches plus any interleaved
    pickoff/steal attempts. Only a *pitch* with ``ab_over`` ends an at-bat.
    A half-inning that ends on a baserunning out leaves a dangling at-bat with
    no plate result; it is closed on the inning/half change.
    """
    at_bats: List[Dict[str, Any]] = []
    cur: List[Dict[str, Any]] = []
    cur_key = None

    def flush() -> None:
        if cur:
            at_bats.append(_finalize_at_bat(list(cur)))

    for act in actions:
        key = (act.get("inning"), act.get("half"))
        if cur and key != cur_key:
            flush()
            cur.clear()
        cur_key = key
        cur.append(act)
        if act.get("ab_over"):
            flush()
            cur.clear()
            cur_key = None
    flush()
    return at_bats


def _finalize_at_bat(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build an at-bat summary (the section 3 fields) from its event stream."""
    closing = next((e for e in reversed(events) if e.get("ab_over")), None)
    anchor = closing or next(
        (e for e in events if e["kind"] == "pitch"), events[0]
    )
    last = events[-1]

    runs = sum(e.get("runs_scored") or 0 for e in events)
    run_ids: List[int] = []
    runs_scored: List[int] = []
    for e in events:
        run_ids.extend(e.get("runs_scored_ids") or [])
    runs_scored = run_ids

    contact = closing.get("contact") if closing else None
    result = closing.get("result") if closing else None

    result_detail: Optional[Dict[str, Any]] = None
    if contact:
        result_detail = {
            "batted_ball": contact.get("batted_ball"),
            "air_or_ground": contact.get("air_or_ground"),
            "hit_depth": contact.get("hit_depth"),
            "hit_direction": contact.get("hit_direction"),
            "fielder": contact.get("fielder"),
            "errors": contact.get("errors") or [],
        }

    outs_before = events[0].get("outs_before") or 0
    outs_after = (last.get("outs_before") or 0) + (last.get("outs_recorded") or 0)

    ab: Dict[str, Any] = {
        "seq": anchor.get("id"),
        "inning": anchor.get("inning"),
        "half": anchor.get("half"),
        "outs_before": outs_before,
        "outs_after": outs_after,
        "batter": anchor.get("batter"),
        "pitcher": anchor.get("pitcher"),
        "result": result,
        "result_detail": result_detail,
        "rbi": runs,            # runs driven in on this at-bat (== runs scored)
        "runs_scored": [        # [{id}] of runners who scored
            {"id": rid} for rid in runs_scored
        ],
        "runners_after": last.get("runners_after"),
        "score_after": last.get("score_after"),
        "events": events,
    }
    ab["description"] = describe(ab)
    return ab


# --------------------------------------------------------------------------- #
# Narrative description (pure)
# --------------------------------------------------------------------------- #

_RESULT_VERBS = {
    "single": "singles",
    "double": "doubles",
    "triple": "triples",
    "home_run": "homers",
    "inside_the_park_hr": "hits an inside-the-park home run",
    "walk": "walks",
    "hbp": "is hit by the pitch",
    "strikeout": "strikes out",
    "groundout": "grounds out",
    "flyout": "flies out",
    "out": "is out",
}

_HIT_RESULT_KEYS = ("single", "double", "triple", "home_run", "inside_the_park_hr")


def _name(player: Optional[Dict[str, Any]]) -> str:
    if player and player.get("name"):
        return str(player["name"])
    return "Unknown"


def describe(at_bat: Dict[str, Any]) -> str:
    """Generate a short human-readable line for an at-bat (pure, deterministic)."""
    batter = _name(at_bat.get("batter"))
    result = at_bat.get("result")
    detail = at_bat.get("result_detail") or {}
    runs = at_bat.get("rbi") or 0

    if result is None:
        # Dangling at-bat (inning ended on a baserunning out, no plate result).
        steals = [e for e in at_bat.get("events", []) if e.get("kind") == "steal"]
        if steals:
            return _describe_baserunning(steals[-1])
        return f"{batter} -- at-bat incomplete."

    verb = _RESULT_VERBS.get(result, result.replace("_", " "))
    sentence = f"{batter} {verb}"

    if result in _HIT_RESULT_KEYS:
        direction = detail.get("hit_direction")
        bb = detail.get("batted_ball")
        bits = []
        if bb:
            bits.append(str(bb))
        if direction:
            bits.append(f"to {direction}")
        if bits:
            sentence += " (" + " ".join(bits) + ")"
    elif result in ("groundout", "flyout", "out"):
        fielder = detail.get("fielder")
        if fielder and fielder.get("name"):
            sentence += f" to {fielder['name']}"

    sentence += "."

    errors = detail.get("errors") or []
    if errors:
        sentence += " (" + "; ".join(str(e) for e in errors) + ")"

    if runs:
        plural = "s" if runs != 1 else ""
        verb_s = "" if runs != 1 else "s"
        sentence += f" {runs} run{plural} score{verb_s}."

    return sentence


def _describe_baserunning(event: Dict[str, Any]) -> str:
    runner = event.get("runner")
    who = runner["name"] if runner and runner.get("name") else "Runner"
    result = event.get("result") or ""
    if result == "stolen_base":
        return f"{who} steals a base."
    if result == "caught_stealing":
        return f"{who} is caught stealing."
    if "pickoff" in result:
        return f"Pickoff attempt ({result.replace('_', ' ')})."
    if result:
        return f"{who}: {result.replace('_', ' ')}."
    return f"{who} on the bases."


# --------------------------------------------------------------------------- #
# Top-level entry point
# --------------------------------------------------------------------------- #

def normalize_game(
    raw_actions: Any,
    game_id: Any,
    home_abbrev: Optional[str],
    away_abbrev: Optional[str],
    granularity: str = "at_bat",
    include_events: bool = False,
) -> Dict[str, Any]:
    """
    Normalize a raw play-by-play array into the v2 shape.

    Returns::

        {
          "schema_version": 2,
          "game_id": <game_id>,
          "teams": {"home": <home_abbrev>, "away": <away_abbrev>},
          "at_bats": [...]            # granularity == "at_bat"
        }

    For ``granularity == "action"`` the ``at_bats`` key is replaced with a flat
    ``actions`` list (one normalized action per raw entry).

    When ``include_events`` is False (the default) and granularity is
    ``"at_bat"``, the per-action ``events`` stream is dropped from each at-bat.

    Never raises on real engine data; non-list / unparseable input yields an
    empty result list.
    """
    if isinstance(raw_actions, str):
        import json
        try:
            raw_actions = json.loads(raw_actions)
        except (ValueError, TypeError):
            raw_actions = []
    if not isinstance(raw_actions, list):
        raw_actions = []

    actions = [normalize_action(p) for p in raw_actions if isinstance(p, dict)]

    out: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "game_id": game_id,
        "teams": {"home": home_abbrev, "away": away_abbrev},
    }

    if granularity == "action":
        out["actions"] = actions
        return out

    at_bats = group_at_bats(actions)
    if not include_events:
        for ab in at_bats:
            ab.pop("events", None)
    out["at_bats"] = at_bats
    return out
