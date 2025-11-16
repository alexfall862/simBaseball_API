# seeding/contracts_seed.py

import random
from decimal import Decimal

from sqlalchemy import MetaData, Table, select, delete, update
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine  # you already use this in other modules


STARTING_LEAGUE_YEAR = 2026

MINOR_SALARY = Decimal("50000.00")
PRE_ARB_SALARY = Decimal("600000.00")
VET_MIN_SALARY = 1_000_000
VET_MAX_SALARY = 20_000_000


def seed_initial_contracts():
    """
    One-time contract seeding for launch.

    - Keeps contracts.current_level and existing holder org mapping.
    - Resets contract lengths, salaries, and team shares based on level/age.
    - Leaves contracts rows in place but overwrites years/current_year/etc.
    - Wipes and repopulates contractDetails and contractTeamShare.

    Returns:
        dict: {"seeded_contracts": <int>}
    """

    engine = get_engine()
    md = MetaData()

    contracts = Table("contracts", md, autoload_with=engine)
    details = Table("contractDetails", md, autoload_with=engine)
    shares = Table("contractTeamShare", md, autoload_with=engine)
    players = Table("simbbPlayers", md, autoload_with=engine)

    # Adjust if your schema is different
    player_age_col = players.c.age

    with engine.begin() as conn:  # begin() => transaction
        try:
            # 1) Snapshot contracts + players + current holder orgs

            current_detail_subq = (
                select(
                    details.c.id.label("detail_id"),
                    details.c.contractID.label("contract_id"),
                )
                .select_from(details)
                .join(contracts, details.c.contractID == contracts.c.id)
                .where(details.c.year == contracts.c.current_year)
                .subquery()
            )

            holder_subq = (
                select(
                    shares.c.contractDetailsID.label("detail_id"),
                    shares.c.orgID.label("holder_org_id"),
                )
                .where(shares.c.isHolder == 1)
                .subquery()
            )

            snapshot_stmt = (
                select(
                    contracts.c.id.label("contract_id"),
                    contracts.c.playerID.label("player_id"),
                    contracts.c.years.label("old_years"),
                    contracts.c.current_year.label("old_current_year"),
                    contracts.c.signingOrg.label("old_signing_org"),
                    contracts.c.current_level.label("current_level"),
                    player_age_col.label("player_age"),
                    holder_subq.c.holder_org_id.label("holder_org_id"),
                )
                .select_from(
                    contracts
                    .join(players, players.c.id == contracts.c.playerID)
                    .outerjoin(
                        current_detail_subq,
                        current_detail_subq.c.contract_id == contracts.c.id,
                    )
                    .outerjoin(
                        holder_subq,
                        holder_subq.c.detail_id == current_detail_subq.c.detail_id,
                    )
                )
                # Add filters if you only want certain contracts:
                # .where(contracts.c.isFinished == 0)
            )

            contract_rows = conn.execute(snapshot_stmt).all()

            contract_info = {}
            for row in contract_rows:
                m = row._mapping
                contract_id = m["contract_id"]

                holder_org_id = (
                    m["holder_org_id"]
                    if m["holder_org_id"] is not None
                    else m["old_signing_org"]
                )

                contract_info[contract_id] = {
                    "contract_id": contract_id,
                    "player_id": m["player_id"],
                    "current_level": m["current_level"],
                    "player_age": m["player_age"],
                    "holder_org_id": holder_org_id,
                }

            # 2) Wipe old contractDetails and contractTeamShare
            conn.execute(delete(shares))
            conn.execute(delete(details))

            # 3) Update contracts + build new details in memory
            new_details_to_insert = []
            contract_lengths = {}
            contract_salaries = {}

            for info in contract_info.values():
                contract_id = info["contract_id"]
                current_level = info["current_level"]
                player_age = info["player_age"]
                holder_org_id = info["holder_org_id"]

                length = 1
                annual_salary = MINOR_SALARY

                if current_level is None:
                    length = 1
                    annual_salary = MINOR_SALARY
                elif current_level < 9:
                    # Minor leagues
                    length = 1
                    annual_salary = MINOR_SALARY
                else:
                    # MLB level
                    if player_age is not None and player_age >= 27:
                        length = random.randint(1, 3)
                        annual_salary = Decimal(
                            str(random.randint(VET_MIN_SALARY, VET_MAX_SALARY))
                        )
                    else:
                        length = 1
                        annual_salary = PRE_ARB_SALARY

                contract_lengths[contract_id] = length
                contract_salaries[contract_id] = annual_salary

                upd = (
                    update(contracts)
                    .where(contracts.c.id == contract_id)
                    .values(
                        years=length,
                        current_year=1,
                        isExtension=0,
                        isBuyout=0,
                        bonus=Decimal("0.00"),
                        signingOrg=holder_org_id,
                        leagueYearSigned=STARTING_LEAGUE_YEAR,
                        isFinished=0,
                    )
                )
                conn.execute(upd)

                for year_idx in range(1, length + 1):
                    new_details_to_insert.append(
                        {
                            "contractID": contract_id,
                            "year": year_idx,
                            "salary": annual_salary,
                        }
                    )

            if new_details_to_insert:
                conn.execute(details.insert(), new_details_to_insert)

            # 5) Reload contractDetails and create TeamShare rows
            details_stmt = select(
                details.c.id,
                details.c.contractID,
            )
            all_details = conn.execute(details_stmt).all()

            team_shares_to_insert = []

            for drow in all_details:
                dm = drow._mapping
                detail_id = dm["id"]
                contract_id = dm["contractID"]

                info = contract_info.get(contract_id)
                if not info:
                    continue

                holder_org_id = info["holder_org_id"]

                team_shares_to_insert.append(
                    {
                        "contractDetailsID": detail_id,
                        "orgID": holder_org_id,
                        "isHolder": 1,
                        "salary_share": Decimal("1.00"),
                    }
                )

            if team_shares_to_insert:
                conn.execute(shares.insert(), team_shares_to_insert)

            seeded_count = len(contract_info)
            print(f"Seeded {seeded_count} contracts with new terms.")

            return {"seeded_contracts": seeded_count}

        except SQLAlchemyError as e:
            print("Error during contract seeding:", str(e))
            raise
