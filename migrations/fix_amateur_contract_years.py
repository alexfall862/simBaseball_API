# migrations/017_fix_amateur_contract_years.py
"""
Fix HS and College contract years/current_year so the frontend can derive
class year directly from current_year.

Changes:
  - Move 18-year-old USA players from College (level 3) to HS (level 1)
  - HS contracts: years=4, current_year = age - 14
  - College non-redshirt: years=4, current_year = age - 18
  - College redshirt: years=5, current_year = age - 18
  - Rebuild contractDetails + contractTeamShare to match new year counts

Run via: POST /admin/migrations/fix-amateur-contracts
"""

import logging
from decimal import Decimal

from sqlalchemy import MetaData, Table, select, and_, text

from db import get_engine

log = logging.getLogger("app")

HS_ORG_ID = 340
HS_LEVEL = 1
COLLEGE_LEVEL = 3
MINOR_SALARY = Decimal("40000.00")


def migrate_amateur_contract_years(engine=None):
    """
    Fix HS/College contract years and current_year for class year derivation.

    Returns summary dict with counts.
    """
    if engine is None:
        engine = get_engine()

    md = MetaData()
    contracts = Table("contracts", md, autoload_with=engine)
    details = Table("contractDetails", md, autoload_with=engine)
    shares = Table("contractTeamShare", md, autoload_with=engine)
    players = Table("simbbPlayers", md, autoload_with=engine)

    with engine.begin() as conn:
        # ── Step 1: Find all active HS + College contracts with player age ──

        rows = conn.execute(
            select(
                contracts.c.id.label("contract_id"),
                contracts.c.current_level,
                contracts.c.years,
                contracts.c.isExtension,
                contracts.c.signingOrg,
                players.c.id.label("player_id"),
                players.c.age,
                players.c.intorusa,
            )
            .join(players, players.c.id == contracts.c.playerID)
            .where(and_(
                contracts.c.isActive == 1,
                contracts.c.isFinished == 0,
                contracts.c.current_level.in_([HS_LEVEL, COLLEGE_LEVEL]),
            ))
        ).all()

        log.info("migrate_contracts: found %d HS/College contracts to fix", len(rows))

        # ── Step 2: Calculate new values for each contract ──

        updates = []  # list of (contract_id, new_years, new_current_year, new_level, new_org, new_is_ext)
        moved_to_hs = 0

        for row in rows:
            m = row._mapping
            cid = m["contract_id"]
            level = m["current_level"]
            age = m["age"]
            is_redshirt = bool(m["isExtension"])
            origin = (m["intorusa"] or "").lower()
            signing_org = m["signingOrg"]

            if level == COLLEGE_LEVEL and age == 18 and origin == "usa":
                # 18-year-old USA college player → move to HS as senior
                new_years = 4
                new_cy = 4  # senior
                new_level = HS_LEVEL
                new_org = HS_ORG_ID
                new_is_ext = 0
                moved_to_hs += 1

            elif level == HS_LEVEL or (level == COLLEGE_LEVEL and age == 18 and origin == "usa"):
                # HS contract: 4 years, current_year = age - 14
                new_years = 4
                new_cy = max(1, min(4, age - 14))
                new_level = HS_LEVEL
                new_org = signing_org if level == HS_LEVEL else HS_ORG_ID
                new_is_ext = 0

            elif level == COLLEGE_LEVEL:
                # College: 4 years (non-RS) or 5 years (RS), current_year = age - 18
                new_cy = age - 18

                if is_redshirt:
                    new_years = 5
                else:
                    new_years = 4

                # Force redshirt if over-age for non-redshirt
                if new_cy > new_years:
                    is_redshirt = True
                    new_years = 5

                new_cy = max(1, min(new_years, new_cy))
                new_level = COLLEGE_LEVEL
                new_org = signing_org
                new_is_ext = 1 if is_redshirt else 0

            else:
                continue

            updates.append((cid, new_years, new_cy, new_level, new_org, new_is_ext))

        if not updates:
            return {
                "hs_updated": 0,
                "college_updated": 0,
                "moved_to_hs": 0,
                "details_rebuilt": 0,
                "shares_rebuilt": 0,
            }

        log.info(
            "migrate_contracts: %d contracts to update, %d moved to HS",
            len(updates), moved_to_hs,
        )

        # ── Step 3: Update contracts table ──

        for cid, new_years, new_cy, new_level, new_org, new_is_ext in updates:
            conn.execute(
                contracts.update()
                .where(contracts.c.id == cid)
                .values(
                    years=new_years,
                    current_year=new_cy,
                    current_level=new_level,
                    signingOrg=new_org,
                    isExtension=new_is_ext,
                )
            )

        # ── Step 4: Rebuild contractDetails + contractTeamShare ──

        contract_ids = [u[0] for u in updates]
        cid_to_info = {
            u[0]: {"years": u[1], "org": u[4]}
            for u in updates
        }

        # Delete existing shares (must go first — FK to details)
        existing_detail_ids = conn.execute(
            select(details.c.id)
            .where(details.c.contractID.in_(contract_ids))
        ).all()
        detail_ids = [r[0] for r in existing_detail_ids]

        if detail_ids:
            conn.execute(
                shares.delete().where(shares.c.contractDetailsID.in_(detail_ids))
            )
            log.info("migrate_contracts: deleted %d old share rows", len(detail_ids))

        # Delete existing details
        conn.execute(
            details.delete().where(details.c.contractID.in_(contract_ids))
        )
        log.info("migrate_contracts: deleted old detail rows for %d contracts", len(contract_ids))

        # Insert new details
        details_rows = []
        for cid, info in cid_to_info.items():
            for yr in range(1, info["years"] + 1):
                details_rows.append({
                    "contractID": cid,
                    "year": yr,
                    "salary": MINOR_SALARY,
                })

        if details_rows:
            conn.execute(details.insert(), details_rows)
            log.info("migrate_contracts: inserted %d new detail rows", len(details_rows))

        # Re-query to get generated detail IDs
        new_details = conn.execute(
            select(details.c.id, details.c.contractID)
            .where(details.c.contractID.in_(contract_ids))
        ).all()

        shares_rows = []
        for drow in new_details:
            dm = drow._mapping
            org_id = cid_to_info[dm["contractID"]]["org"]
            shares_rows.append({
                "contractDetailsID": dm["id"],
                "orgID": org_id,
                "isHolder": 1,
                "salary_share": Decimal("1.00"),
            })

        if shares_rows:
            conn.execute(shares.insert(), shares_rows)
            log.info("migrate_contracts: inserted %d new share rows", len(shares_rows))

        # ── Summary ──

        hs_count = sum(1 for u in updates if u[3] == HS_LEVEL)
        college_count = sum(1 for u in updates if u[3] == COLLEGE_LEVEL)

        summary = {
            "hs_updated": hs_count,
            "college_updated": college_count,
            "moved_to_hs": moved_to_hs,
            "details_rebuilt": len(details_rows),
            "shares_rebuilt": len(shares_rows),
        }

        log.info("migrate_contracts: done — %s", summary)
        return summary
