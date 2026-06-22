"""
Unit tests for services.pbp_normalize.

Runs with pytest *or* standalone (`python tests/test_pbp_normalize.py`).
Validates against the real engine sample at repo-root pbp_sample.json when
present, plus hand-built fixtures for the tricky cases (malformed Error List,
"None" sentinels, baserunning actions, dangling at-bats, the read allowlist).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import pbp_normalize as N  # noqa: E402

SAMPLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pbp_sample.json"
)


# --------------------------------------------------------------------------- #
# Low-level cleaners
# --------------------------------------------------------------------------- #

def test_none_to_null_sentinels():
    assert N.none_to_null("None") is None
    assert N.none_to_null("none") is None
    assert N.none_to_null("NONE") is None
    assert N.none_to_null("") is None
    assert N.none_to_null("single") == "single"
    assert N.none_to_null(0) == 0


def test_player_object_and_sentinel():
    assert N._player({"player_id": 5, "player_name": "Ed Foo"}) == {"id": 5, "name": "Ed Foo"}
    assert N._player("None") is None
    assert N._player(None) is None
    assert N._player({"player_name": "no id"}) is None
    assert N._player({"player_id": "12", "player_name": "Str Id"}) == {"id": 12, "name": "Str Id"}


def test_parse_outcomes():
    assert N.parse_outcomes("['Ball', 'Looking', 'Fastball']") == {
        "result": "Ball", "swing": "Looking", "pitch": "Fastball"}
    assert N.parse_outcomes("None") is None
    assert N.parse_outcomes("") is None
    # malformed -> None, never raises
    assert N.parse_outcomes("['x', unquoted]") is None


def test_parse_string_list_valid():
    assert N.parse_string_list("['home run']") == ["home run"]
    assert N.parse_string_list("[]") == []
    assert N.parse_string_list(["already", "list"]) == ["already", "list"]


def test_parse_string_list_malformed_never_raises():
    # Real engine value: unquoted tokens -> not valid Python, must degrade.
    val = "['starter Max Knox catching error!', starter Max Knox]"
    out = N.parse_string_list(val)
    assert isinstance(out, list)
    assert any("catching error" in x for x in out)


# --------------------------------------------------------------------------- #
# Read allowlist (the security boundary)
# --------------------------------------------------------------------------- #

def test_allowlist_blocks_engine_internals():
    for blocked in ("Interaction_Data", "At_Bat_Modifiers", "Timing_Diagnostics",
                    "Pre_R1", "Pre_R2", "Pre_R3", "Catch Probability"):
        assert not N._is_allowed_key(blocked), blocked
    for ok in ("Inning", "Batter", "Defensive Outcome", "On First",
               "AB_Over", "Is_Homerun"):
        assert N._is_allowed_key(ok), ok


def test_normalize_action_never_copies_internals():
    raw = {
        "ID": 1, "Inning": 1, "Inning Half": "Top", "Batter": {"player_id": 1, "player_name": "X"},
        "Interaction_Data": {"secret": 1}, "At_Bat_Modifiers": {"rng": 0.5},
        "Pre_R1": {"player_id": 9, "player_name": "Leak"},
    }
    out = N.normalize_action(raw)
    blob = json.dumps(out)
    assert "secret" not in blob and "rng" not in blob and "Leak" not in blob


# --------------------------------------------------------------------------- #
# Classification & result enum
# --------------------------------------------------------------------------- #

def test_classify_action():
    assert N.classify_action({"Is_Pickoff": True}) == "pickoff"
    assert N.classify_action({"Is_StealAttempt": True}) == "steal"
    assert N.classify_action({}) == "pitch"


def test_result_enum_pitch_variants():
    base = {"AB_Over": True, "Defensive Outcome": "out"}
    assert N._result_enum({**base, "Air or Ground": "ground"}, "pitch") == "groundout"
    assert N._result_enum({**base, "Air or Ground": "air"}, "pitch") == "flyout"
    assert N._result_enum({"AB_Over": True, "Is_Walk": True}, "pitch") == "walk"
    assert N._result_enum({"AB_Over": True, "Is_HBP": True}, "pitch") == "hbp"
    assert N._result_enum({"AB_Over": True, "Is_Strikeout": True}, "pitch") == "strikeout"
    assert N._result_enum({"AB_Over": True, "Defensive Outcome": "homerun"}, "pitch") == "home_run"
    # Non-terminal pitch has no plate result
    assert N._result_enum({"AB_Over": False, "Defensive Outcome": "None"}, "pitch") is None


def test_result_enum_baserunning():
    assert N._result_enum({"Defensive Outcome": "stolen base"}, "steal") == "stolen_base"
    assert N._result_enum({"Defensive Outcome": "caught stealing"}, "steal") == "caught_stealing"
    assert N._result_enum({"Defensive Outcome": "unsuccessful pickoff"}, "pickoff") == "unsuccessful_pickoff"


# --------------------------------------------------------------------------- #
# Descriptions
# --------------------------------------------------------------------------- #

def test_describe_home_run_with_runs():
    ab = {
        "batter": {"id": 1, "name": "Drew Hale"}, "result": "home_run",
        "rbi": 2, "result_detail": {"hit_direction": "center", "batted_ball": "solid"},
        "events": [],
    }
    desc = N.describe(ab)
    assert "Drew Hale homers" in desc
    assert "center" in desc
    assert "2 runs score" in desc


def test_describe_groundout_with_fielder():
    ab = {
        "batter": {"id": 1, "name": "Sam Vance"}, "result": "groundout",
        "rbi": 0, "result_detail": {"fielder": {"id": 9, "name": "Riley Cole"}},
        "events": [],
    }
    assert N.describe(ab) == "Sam Vance grounds out to Riley Cole."


def test_describe_with_error():
    ab = {
        "batter": {"id": 1, "name": "Jordan Park"}, "result": "single",
        "rbi": 0,
        "result_detail": {"hit_direction": "right", "batted_ball": "flare",
                          "errors": ["catching error by Max Knox"]},
        "events": [],
    }
    desc = N.describe(ab)
    assert "Jordan Park singles" in desc
    assert "catching error by Max Knox" in desc


def test_describe_dangling_caught_stealing():
    ab = {
        "batter": {"id": 1, "name": "X"}, "result": None, "rbi": 0,
        "events": [{"kind": "steal", "result": "caught_stealing",
                    "runner": {"id": 3, "name": "Casey Reed"}}],
    }
    assert N.describe(ab) == "Casey Reed is caught stealing."


# --------------------------------------------------------------------------- #
# End-to-end against the real sample
# --------------------------------------------------------------------------- #

def test_real_sample_normalizes():
    if not os.path.exists(SAMPLE_PATH):
        print("SKIP real-sample test (pbp_sample.json not found)")
        return
    raw = json.load(open(SAMPLE_PATH))
    game = N.normalize_game(raw, 999, "HOM", "AWY",
                            granularity="at_bat", include_events=True)

    assert game["schema_version"] == 2
    assert game["game_id"] == 999
    assert game["teams"] == {"home": "HOM", "away": "AWY"}
    at_bats = game["at_bats"]
    assert len(at_bats) > 0

    # Every at-bat has a non-empty description and no "None"-string leakage.
    for ab in at_bats:
        assert ab["description"] and isinstance(ab["description"], str)
        for fld in ("batted_ball", "hit_depth", "hit_direction"):
            d = ab.get("result_detail") or {}
            assert d.get(fld) != "None"

    # Events attached (guards the cur-aliasing bug); every raw action lands in
    # exactly one at-bat's event stream.
    total_events = sum(len(ab["events"]) for ab in at_bats)
    assert total_events == len(raw), f"{total_events} events != {len(raw)} raw actions"

    # The known home run in the sample is captured.
    assert any(ab["result"] == "home_run" for ab in at_bats)

    # All three action kinds survive in the flat view.
    flat = N.normalize_game(raw, 999, "HOM", "AWY", granularity="action")["actions"]
    kinds = {a["kind"] for a in flat}
    assert {"pitch", "pickoff", "steal"} <= kinds

    # include_events=False (the module default) drops the stream.
    light = N.normalize_game(raw, 999, "HOM", "AWY", granularity="at_bat")
    assert all("events" not in ab for ab in light["at_bats"])

    print(f"OK: {len(raw)} actions -> {len(at_bats)} at-bats")
    print("   sample lines:")
    for ab in at_bats[:6]:
        print("    -", ab["description"])


def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"PASS {fn.__name__}")
    print(f"\n{passed}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run_standalone()
