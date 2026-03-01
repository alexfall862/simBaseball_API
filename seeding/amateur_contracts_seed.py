# seeding/amateur_contracts_seed.py
"""
One-time seeding of contracts for amateur-level players (HS, INTAM, College).

Finds all players in simbbPlayers who have no active contract and assigns them
to the appropriate amateur organization with contracts lasting through their
eligibility window.
"""

import random
import logging
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from sqlalchemy import MetaData, Table, and_, select
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

log = logging.getLogger("app")

# ── Constants ────────────────────────────────────────────────────────────

MINOR_SALARY = Decimal("40000.00")
LEAGUE_YEAR = 2026
REDSHIRT_RATE = 0.20

HS_ORG_ID = 340
HS_LEVEL = 1

INTAM_ORG_ID = 339
INTAM_LEVEL = 2

COLLEGE_LEVEL = 3
COLLEGE_ORG_IDS = list(range(31, 339))  # 31..338 inclusive (308 orgs)

TARGET_PITCHERS_PER_ORG = 17
TARGET_BATTERS_PER_ORG = 17


# ── Preview (read-only) ──────────────────────────────────────────────────

def preview_amateur_need(engine=None) -> Dict[str, Any]:
    """
    Read-only scan: count uncontracted players by category so the admin
    UI can display the breakdown before triggering the seed.
    """
    if engine is None:
        engine = get_engine()

    md = MetaData()
    players = Table("simbbPlayers", md, autoload_with=engine)
    contracts = Table("contracts", md, autoload_with=engine)

    with engine.connect() as conn:
        uncontracted = conn.execute(
            select(
                players.c.id,
                players.c.age,
                players.c.intorusa,
                players.c.ptype,
            )
            .where(players.c.id.notin_(
                select(contracts.c.playerID).where(contracts.c.isFinished == 0)
            ))
        ).all()

        hs = {"Pitcher": 0, "Position": 0}
        intam_young = {"Pitcher": 0, "Position": 0}
        intam_older = {"Pitcher": 0, "Position": 0}
        college = {"Pitcher": 0, "Position": 0}
        skipped = 0

        for row in uncontracted:
            m = row._mapping
            age = m["age"]
            origin = (m["intorusa"] or "").lower()
            ptype = m["ptype"] if m["ptype"] in ("Pitcher", "Position") else "Position"

            if age is None:
                skipped += 1
                continue

            if origin == "international":
                if 15 <= age <= 17:
                    intam_young[ptype] += 1
                elif 18 <= age <= 22:
                    intam_older[ptype] += 1
                else:
                    skipped += 1
            elif origin == "usa":
                if 15 <= age <= 17:
                    hs[ptype] += 1
                elif 18 <= age <= 23:
                    college[ptype] += 1
                else:
                    skipped += 1
            else:
                skipped += 1

        college_total = college["Pitcher"] + college["Position"]
        college_orgs = len(COLLEGE_ORG_IDS)

        return {
            "total_uncontracted": len(uncontracted),
            "hs": {
                "pitchers": hs["Pitcher"],
                "batters": hs["Position"],
                "total": hs["Pitcher"] + hs["Position"],
                "org": "USHS (340)",
            },
            "intam_young": {
                "pitchers": intam_young["Pitcher"],
                "batters": intam_young["Position"],
                "total": intam_young["Pitcher"] + intam_young["Position"],
                "org": "INTAM (339)",
                "age_range": "15-17",
            },
            "intam_older": {
                "pitchers": intam_older["Pitcher"],
                "batters": intam_older["Position"],
                "total": intam_older["Pitcher"] + intam_older["Position"],
                "org": "INTAM (339)",
                "age_range": "18-22",
            },
            "college": {
                "pitchers": college["Pitcher"],
                "batters": college["Position"],
                "total": college_total,
                "orgs_available": college_orgs,
                "avg_pitchers_per_org": round(college["Pitcher"] / college_orgs, 1) if college_orgs else 0,
                "avg_batters_per_org": round(college["Position"] / college_orgs, 1) if college_orgs else 0,
                "target_per_org": TARGET_PITCHERS_PER_ORG + TARGET_BATTERS_PER_ORG,
            },
            "skipped": skipped,
        }


# ── Main entry point ────────────────────────────────────────────────────

def seed_amateur_contracts(engine=None) -> Dict[str, Any]:
    """
    Find uncontracted players, categorize by age/origin, and create contracts
    for HS, INTAM, and College organizations.

    Returns a summary dict with counts per category.
    """
    if engine is None:
        engine = get_engine()

    md = MetaData()
    players = Table("simbbPlayers", md, autoload_with=engine)
    contracts = Table("contracts", md, autoload_with=engine)
    details = Table("contractDetails", md, autoload_with=engine)
    shares = Table("contractTeamShare", md, autoload_with=engine)

    with engine.begin() as conn:
        try:
            # 1) Find all players with no active contract
            active_player_ids = (
                select(contracts.c.playerID)
                .where(contracts.c.isFinished == 0)
                .scalar_subquery()
            )

            uncontracted = conn.execute(
                select(
                    players.c.id,
                    players.c.age,
                    players.c.intorusa,
                    players.c.ptype,
                )
                .where(players.c.id.notin_(
                    select(contracts.c.playerID).where(contracts.c.isFinished == 0)
                ))
            ).all()

            log.info("amateur_seed: found %d uncontracted players", len(uncontracted))

            # 2) Categorize
            hs = []
            intam_young = []
            intam_older = []
            college = []
            skipped = 0

            for row in uncontracted:
                m = row._mapping
                pid = m["id"]
                age = m["age"]
                origin = (m["intorusa"] or "").lower()
                ptype = m["ptype"] or "Position"

                if age is None:
                    skipped += 1
                    continue

                p = {"id": pid, "age": age, "ptype": ptype}

                if origin == "international":
                    if 15 <= age <= 17:
                        intam_young.append(p)
                    elif 18 <= age <= 22:
                        intam_older.append(p)
                    else:
                        skipped += 1
                elif origin == "usa":
                    if 15 <= age <= 17:
                        hs.append(p)
                    elif 18 <= age <= 23:
                        college.append(p)
                    else:
                        skipped += 1
                else:
                    skipped += 1

            log.info(
                "amateur_seed: hs=%d intam_young=%d intam_older=%d college=%d skipped=%d",
                len(hs), len(intam_young), len(intam_older), len(college), skipped,
            )

            # 3) Build assignments: list of (player, org_id, level, years, is_redshirt)
            assignments = []
            skipped_zero = 0

            # HS
            for p in hs:
                years = 18 - p["age"]
                if years <= 0:
                    skipped_zero += 1
                    continue
                assignments.append((p, HS_ORG_ID, HS_LEVEL, years, False))

            # INTAM young (15-17, expire at 18)
            for p in intam_young:
                years = 18 - p["age"]
                if years <= 0:
                    skipped_zero += 1
                    continue
                assignments.append((p, INTAM_ORG_ID, INTAM_LEVEL, years, False))

            # INTAM older (18-22, expire at 23)
            for p in intam_older:
                years = 23 - p["age"]
                if years <= 0:
                    skipped_zero += 1
                    continue
                assignments.append((p, INTAM_ORG_ID, INTAM_LEVEL, years, False))

            # College — round-robin distribution
            college_assignments = _distribute_college_players(college)
            redshirt_count = 0
            for p, org_id in college_assignments:
                is_redshirt = random.random() < REDSHIRT_RATE
                years = (24 if is_redshirt else 23) - p["age"]
                if years <= 0:
                    skipped_zero += 1
                    continue
                if is_redshirt:
                    redshirt_count += 1
                assignments.append((p, org_id, COLLEGE_LEVEL, years, is_redshirt))

            log.info(
                "amateur_seed: total assignments=%d, skipped_zero_years=%d, redshirts=%d",
                len(assignments), skipped_zero, redshirt_count,
            )

            if not assignments:
                return {
                    "hs_contracts": 0,
                    "intam_contracts": 0,
                    "college_contracts": 0,
                    "total_contracts": 0,
                    "skipped_no_age": skipped,
                    "skipped_zero_years": skipped_zero,
                }

            # 4) Bulk-insert contracts
            contract_rows = []
            for p, org_id, level, years, is_redshirt in assignments:
                contract_rows.append({
                    "playerID": p["id"],
                    "years": years,
                    "current_year": 1,
                    "isExtension": 1 if is_redshirt else 0,
                    "isBuyout": 0,
                    "isActive": 1,
                    "bonus": Decimal("0.00"),
                    "signingOrg": org_id,
                    "current_level": level,
                    "leagueYearSigned": LEAGUE_YEAR,
                    "isFinished": 0,
                    "onIR": 0,
                })

            conn.execute(contracts.insert(), contract_rows)
            log.info("amateur_seed: inserted %d contracts", len(contract_rows))

            # 5) Re-query to get generated contract IDs
            assigned_pids = [a[0]["id"] for a in assignments]
            new_contracts = conn.execute(
                select(
                    contracts.c.id,
                    contracts.c.playerID,
                    contracts.c.years,
                )
                .where(and_(
                    contracts.c.playerID.in_(assigned_pids),
                    contracts.c.isFinished == 0,
                    contracts.c.current_level.in_([HS_LEVEL, INTAM_LEVEL, COLLEGE_LEVEL]),
                ))
            ).all()

            pid_to_contract = {}
            for row in new_contracts:
                m = row._mapping
                pid_to_contract[m["playerID"]] = {
                    "contract_id": m["id"],
                    "years": m["years"],
                }

            # 6) Bulk-insert contractDetails
            details_rows = []
            for pid, cinfo in pid_to_contract.items():
                for yr in range(1, cinfo["years"] + 1):
                    details_rows.append({
                        "contractID": cinfo["contract_id"],
                        "year": yr,
                        "salary": MINOR_SALARY,
                    })

            if details_rows:
                conn.execute(details.insert(), details_rows)
                log.info("amateur_seed: inserted %d detail rows", len(details_rows))

            # 7) Re-query details to get generated IDs, build shares
            contract_ids = [c["contract_id"] for c in pid_to_contract.values()]
            all_details = conn.execute(
                select(details.c.id, details.c.contractID)
                .where(details.c.contractID.in_(contract_ids))
            ).all()

            # Build org lookup from assignments: pid → org_id
            pid_to_org = {a[0]["id"]: a[1] for a in assignments}

            # Build contract_id → org_id mapping
            cid_to_org = {}
            for pid, cinfo in pid_to_contract.items():
                cid_to_org[cinfo["contract_id"]] = pid_to_org[pid]

            shares_rows = []
            for drow in all_details:
                dm = drow._mapping
                org_id = cid_to_org.get(dm["contractID"])
                if org_id is None:
                    continue
                shares_rows.append({
                    "contractDetailsID": dm["id"],
                    "orgID": org_id,
                    "isHolder": 1,
                    "salary_share": Decimal("1.00"),
                })

            if shares_rows:
                conn.execute(shares.insert(), shares_rows)
                log.info("amateur_seed: inserted %d share rows", len(shares_rows))

            # 8) Build summary
            hs_count = sum(1 for a in assignments if a[2] == HS_LEVEL)
            intam_count = sum(1 for a in assignments if a[2] == INTAM_LEVEL)
            college_count = sum(1 for a in assignments if a[2] == COLLEGE_LEVEL)

            summary = {
                "hs_contracts": hs_count,
                "intam_contracts": intam_count,
                "college_contracts": college_count,
                "total_contracts": len(assignments),
                "skipped_no_age": skipped,
                "skipped_zero_years": skipped_zero,
                "redshirt_count": redshirt_count,
                "details_created": len(details_rows),
                "shares_created": len(shares_rows),
            }

            log.info("amateur_seed: done — %s", summary)
            return summary

        except SQLAlchemyError as e:
            log.exception("amateur_seed: SQLAlchemyError: %s", str(e))
            raise


# ── College distribution ─────────────────────────────────────────────────

def _distribute_college_players(
    players: List[Dict],
) -> List[Tuple[Dict, int]]:
    """
    Round-robin distribution of college-eligible players across 308 orgs.
    Targets 17 Pitchers + 17 Batters per org.

    Separates by ptype, shuffles for random talent spread, then assigns
    round-robin so each org gets at most 1 more than any other.
    """
    pitchers = [p for p in players if p["ptype"] == "Pitcher"]
    batters = [p for p in players if p["ptype"] != "Pitcher"]

    random.shuffle(pitchers)
    random.shuffle(batters)

    assignments = []

    for i, p in enumerate(pitchers):
        org_id = COLLEGE_ORG_IDS[i % len(COLLEGE_ORG_IDS)]
        assignments.append((p, org_id))

    for i, p in enumerate(batters):
        org_id = COLLEGE_ORG_IDS[i % len(COLLEGE_ORG_IDS)]
        assignments.append((p, org_id))

    return assignments
