"""
Unit tests for the draft bonus negotiation math (services/draft.py) and the
retirement rule (services/graduation.py). Pure functions, no database.

Run:  python -m pytest tests/test_draft_negotiation.py
"""
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.draft import (  # noqa: E402
    acceptance_probability,
    compute_bonus_ask,
    offer_roll,
    talent_multiplier,
    CLASS_MULT,
    WILLINGNESS,
    MAX_SIGNING_OFFERS,
)
from services.graduation import retirement_reason, class_year_for_remaining  # noqa: E402
from services.league_config import LEAGUE_CONFIG_DEFAULTS  # noqa: E402


# ── talent multiplier ─────────────────────────────────────────────────────

def test_talent_multiplier_endpoints():
    assert talent_multiplier(1, 1000) == Decimal("1.3000")
    assert talent_multiplier(1000, 1000) == Decimal("0.9000")


def test_talent_multiplier_midpoint_and_guards():
    mid = talent_multiplier(500, 999)
    assert Decimal("1.09") < mid < Decimal("1.11")
    assert talent_multiplier(None, 1000) == Decimal("1.00")
    assert talent_multiplier(5, 1) == Decimal("1.00")
    # ranks past the pool size clamp to the bottom
    assert talent_multiplier(5000, 1000) == Decimal("0.9000")


# ── bonus ask ─────────────────────────────────────────────────────────────

def test_ask_senior_at_bottom_is_90_pct_of_slot():
    assert compute_bonus_ask(5_000_000, "senior", 1000, 1000) == Decimal("4500000.00")


def test_ask_freshman_top_pick():
    # 5M * 1.60 * 1.30
    assert compute_bonus_ask(5_000_000, "freshman", 1, 1000) == Decimal("10400000.00")


def test_ask_hs_senior_uses_hs_multiplier():
    ask = compute_bonus_ask(1_000_000, "hs_senior", None, 100)
    assert ask == (Decimal("1000000") * CLASS_MULT["hs_senior"]).quantize(Decimal("0.01"))


def test_ask_unknown_class_falls_back_to_senior():
    assert compute_bonus_ask(100, "redshirt-whatever", None, 10) == Decimal("100.00")


# ── acceptance probability ────────────────────────────────────────────────

def test_offer_at_or_above_ask_always_accepts():
    assert acceptance_probability(100, 100, "freshman") == 1.0
    assert acceptance_probability(150, 100, "freshman") == 1.0


def test_offer_below_60_pct_never_accepts():
    assert acceptance_probability(59, 100, "senior") == 0.0
    assert acceptance_probability(0, 100, "senior") == 0.0


def test_offer_midway_scales_by_willingness():
    # 80% of ask -> base 0.5
    assert acceptance_probability(80, 100, "senior") == pytest.approx(0.5)
    assert acceptance_probability(80, 100, "junior") == pytest.approx(0.5 * WILLINGNESS["junior"])
    assert acceptance_probability(80, 100, "freshman") == pytest.approx(0.5 * 0.2)


def test_zero_ask_accepts():
    assert acceptance_probability(0, 0, "senior") == 1.0


# ── deterministic roll ────────────────────────────────────────────────────

def test_offer_roll_is_deterministic_and_distinct_per_offer():
    a = offer_roll(123, 1)
    assert a == offer_roll(123, 1)
    assert 0.0 <= a < 1.0
    rolls = {offer_roll(123, n) for n in range(1, MAX_SIGNING_OFFERS + 1)}
    assert len(rolls) == MAX_SIGNING_OFFERS
    assert offer_roll(124, 1) != a


# ── class year from remaining eligibility ─────────────────────────────────

def test_class_year_for_remaining():
    assert class_year_for_remaining(0) == "senior"
    assert class_year_for_remaining(1) == "junior"
    assert class_year_for_remaining(2) == "sophomore"
    assert class_year_for_remaining(3) == "freshman"
    assert class_year_for_remaining(4) == "freshman"   # redshirt freshman


# ── retirement rule ───────────────────────────────────────────────────────

CFG = dict(LEAGUE_CONFIG_DEFAULTS)


def test_retire_hard_age_is_off_by_default():
    # nobody retires on age alone unless retire_age_hard is set above 0
    assert retirement_reason(40, True, 80, CFG) is None
    assert retirement_reason(49, True, 80, CFG) is None
    cfg = dict(CFG, retire_age_hard="40")
    assert retirement_reason(40, True, 80, cfg) == "age"
    assert retirement_reason(39, True, 80, cfg) is None


def test_retire_unsigned_36():
    assert retirement_reason(36, False, 70, CFG) == "unsigned"
    assert retirement_reason(36, True, 70, CFG) is None


def test_retire_marginal_33_below_threshold_only_when_unsigned():
    assert retirement_reason(33, False, 35, CFG) == "unsigned_marginal"
    assert retirement_reason(33, False, 40, CFG) is None          # at threshold stays
    assert retirement_reason(33, False, None, CFG) is None        # unknown ovr: keep
    assert retirement_reason(33, True, 35, CFG) is None
    assert retirement_reason(32, False, 20, CFG) is None


def test_retire_thresholds_come_from_config():
    cfg = dict(CFG, retire_age_hard="38")
    assert retirement_reason(38, True, 80, cfg) == "age"


# ── progression sampler ───────────────────────────────────────────────────

import random as _random
from player_engine.player_progression import sample_delta  # noqa: E402


def test_sample_delta_is_an_independent_triangular_draw_within_bounds():
    rng = _random.Random(7)
    params = (-5.0, 7.0, 12.0)
    draws = [sample_delta(params, 22, rng) for _ in range(20000)]
    assert all(-5.0 <= d <= 12.0 for d in draws)
    assert abs(sum(draws) / len(draws) - (-5.0 + 7.0 + 12.0) / 3) < 0.15


def test_sample_delta_young_floor_and_decline_cap():
    rng = _random.Random(3)
    assert all(sample_delta((-9.0, -2.0, 0.0), 19, rng) >= -1.0 for _ in range(500))
    assert all(sample_delta((-9.0, -2.0, 0.0), 40, rng) <= 0.0 for _ in range(500))


# ── training camp ladder ──────────────────────────────────────────────────

from services.training_camp import shift_grade, resolve_intensity, intensity_rules, GRADE_LADDER  # noqa: E402


def test_shift_grade_ladder_and_clamps():
    assert shift_grade("C", 1) == "C+"
    assert shift_grade("C", 4) == "B+"
    assert shift_grade("C", -2) == "D+"
    assert shift_grade("A+", 2) == "A+"
    assert shift_grade("N", -1) == "N"
    assert shift_grade(None, 3) is None
    assert len(GRADE_LADDER) == 14


def test_resolve_intensity_backfire_thresholds():
    rules = intensity_rules(CFG)
    assert resolve_intensity("regular", 0.0, rules) == (1, False)
    assert resolve_intensity("regular", 0.99, rules) == (1, False)
    assert resolve_intensity("intense", 0.24, rules) == (-2, True)
    assert resolve_intensity("intense", 0.25, rules) == (2, False)
    assert resolve_intensity("max", 0.49, rules) == (-4, True)
    assert resolve_intensity("max", 0.50, rules) == (4, False)


def test_retire_never_signed_at_25_only_without_pro_history():
    # undrafted graduate kept in the FA pool: retires at 25 if never signed
    assert retirement_reason(25, False, 70, CFG, ever_pro=False) == "never_signed"
    assert retirement_reason(24, False, 70, CFG, ever_pro=False) is None
    # a released ex-pro of the same age plays on
    assert retirement_reason(25, False, 70, CFG, ever_pro=True) is None
    assert retirement_reason(25, True, 70, CFG, ever_pro=False) is None
    # default keeps the old behaviour
    assert retirement_reason(25, False, 70, CFG) is None
