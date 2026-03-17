# seeding/draft_slot_values_seed.py
"""
Seed draft_slot_values with round-based slot values.

Values decrease by round, loosely modeled on MLB draft slot values.
Round 1 picks are worth the most; later rounds scale down.
"""

import logging
from decimal import Decimal

from sqlalchemy import text
from db import get_engine

log = logging.getLogger("app")

# (round, slot_value) — NULL pick_in_round means the value applies to the
# entire round.  Per-pick overrides can be added later.
SLOT_VALUES = [
    (1,  Decimal("5000000.00")),
    (2,  Decimal("2000000.00")),
    (3,  Decimal("1000000.00")),
    (4,  Decimal("750000.00")),
    (5,  Decimal("500000.00")),
    (6,  Decimal("400000.00")),
    (7,  Decimal("300000.00")),
    (8,  Decimal("250000.00")),
    (9,  Decimal("200000.00")),
    (10, Decimal("175000.00")),
    (11, Decimal("150000.00")),
    (12, Decimal("130000.00")),
    (13, Decimal("115000.00")),
    (14, Decimal("100000.00")),
    (15, Decimal("90000.00")),
    (16, Decimal("80000.00")),
    (17, Decimal("75000.00")),
    (18, Decimal("70000.00")),
    (19, Decimal("65000.00")),
    (20, Decimal("60000.00")),
]


def seed_slot_values():
    """Insert slot values into draft_slot_values (idempotent)."""
    engine = get_engine()
    sql = text("""
        INSERT INTO draft_slot_values (round, pick_in_round, slot_value)
        VALUES (:round, NULL, :slot_value)
        AS new_row ON DUPLICATE KEY UPDATE slot_value = new_row.slot_value
    """)
    with engine.begin() as conn:
        for rnd, val in SLOT_VALUES:
            conn.execute(sql, {"round": rnd, "slot_value": val})
    log.info("Seeded %d draft slot values", len(SLOT_VALUES))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_slot_values()
