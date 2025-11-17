# financials/books.py

from decimal import Decimal
from typing import Dict, Any, List

from sqlalchemy import (
    MetaData,
    Table,
    select,
    and_,
    func,
    literal,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func


INTEREST_RATE = Decimal("0.05")  # 5% annual


def _get_tables(engine):
    """
    Reflect and cache tables needed for financial books logic.
    """
    md = MetaData()
    return {
        "league_years": Table("league_years", md, autoload_with=engine),
        "game_weeks": Table("game_weeks", md, autoload_with=engine),
        "organizations": Table("organizations", md, autoload_with=engine),
        "ledger": Table("org_ledger_entries", md, autoload_with=engine),
        "media_shares": Table("org_media_shares", md, autoload_with=engine),
        "weekly_record": Table("team_weekly_record", md, autoload_with=engine),
        "contracts": Table("contracts", md, autoload_with=engine),
        "details": Table("contractDetails", md, autoload_with=engine),
        "shares": Table("contractTeamShare", md, autoload_with=engine),
        # players optional; handy for audit/notes if you want more info
        "players": Table("simbbPlayers", md, autoload_with=engine),
    }


# --------------------------------------------------------
# Helper: resolve league_year → league_years row
# --------------------------------------------------------

def _get_league_year_row(conn, tables, league_year: int):
    ly = tables["league_years"]
    row = conn.execute(
        select(
            ly.c.id,
            ly.c.league_year,
            ly.c.performance_budget,
            ly.c.media_total,
            ly.c.inflation_factor,
            ly.c.weeks_in_season,
        ).where(ly.c.league_year == league_year).limit(1)
    ).first()
    if not row:
        raise ValueError(f"league_year {league_year} not found in league_years")
    return row._mapping


def _get_game_week_row(conn, tables, league_year_id: int, week_index: int):
    gw = tables["game_weeks"]
    row = conn.execute(
        select(gw.c.id, gw.c.week_index)
        .where(and_(gw.c.league_year_id == league_year_id, gw.c.week_index == week_index))
        .limit(1)
    ).first()
    if not row:
        raise ValueError(
            f"game_week with league_year_id={league_year_id} and week_index={week_index} not found"
        )
    return row._mapping


# --------------------------------------------------------
# 1) Year-start books: media payouts + bonuses
# --------------------------------------------------------

def run_year_start_books(engine, league_year: int) -> Dict[str, Any]:
    """
    Apply year-start financial events for a league year:

      - Media payouts from org_media_shares using media_share * media_total.
      - Signing bonuses / buyouts from contracts (if bonus > 0 and leagueYearSigned == league_year).
    """
    tables = _get_tables(engine)
    ly_tbl = tables["league_years"]
    media_tbl = tables["media_shares"]
    ledger = tables["ledger"]
    contracts = tables["contracts"]

    media_created = 0
    bonuses_created = 0
    skipped_media = 0
    skipped_bonuses = 0

    with engine.begin() as conn:
        ly_row = _get_league_year_row(conn, tables, league_year)
        league_year_id = ly_row["id"]
        media_total = Decimal(ly_row["media_total"])

        # ---- MEDIA PAYOUTS ----
        # Now using media_share (e.g. 0.045) instead of media_amount
        media_rows = conn.execute(
            select(
                media_tbl.c.org_id,
                media_tbl.c.media_share,
            ).where(media_tbl.c.league_year_id == league_year_id)
        ).all()

        for row in media_rows:
            m = row._mapping
            org_id = m["org_id"]
            share = Decimal(m["media_share"])  # e.g. 0.045
            amount = media_total * share       # actual dollars

            # Skip if already have a media entry for this org/year
            existing = conn.execute(
                select(ledger.c.id)
                .where(
                    and_(
                        ledger.c.org_id == org_id,
                        ledger.c.league_year_id == league_year_id,
                        ledger.c.entry_type == "media",
                    )
                )
                .limit(1)
            ).first()
            if existing:
                skipped_media += 1
                continue

            conn.execute(
                ledger.insert().values(
                    org_id=org_id,
                    league_year_id=league_year_id,
                    game_week_id=None,
                    entry_type="media",
                    amount=amount,
                    contract_id=None,
                    player_id=None,
                    note=f"Media payout for league_year {league_year}",
                )
            )
            media_created += 1

        # ---- BONUSES / BUYOUTS ----
        bonus_rows = conn.execute(
            select(
                contracts.c.id.label("contract_id"),
                contracts.c.playerID.label("player_id"),
                contracts.c.signingOrg.label("org_id"),
                contracts.c.isBuyout.label("isBuyout"),
                contracts.c.bonus.label("bonus"),
            ).where(
                and_(
                    contracts.c.leagueYearSigned == league_year,
                    contracts.c.bonus > 0,
                )
            )
        ).all()

        for row in bonus_rows:
            m = row._mapping
            contract_id = m["contract_id"]
            player_id = m["player_id"]
            org_id = m["org_id"]
            is_buyout = bool(m["isBuyout"])
            bonus_amt = Decimal(m["bonus"])

            entry_type = "buyout" if is_buyout else "bonus"

            existing = conn.execute(
                select(ledger.c.id)
                .where(
                    and_(
                        ledger.c.contract_id == contract_id,
                        ledger.c.league_year_id == league_year_id,
                        ledger.c.entry_type == entry_type,
                    )
                )
                .limit(1)
            ).first()
            if existing:
                skipped_bonuses += 1
                continue

            conn.execute(
                ledger.insert().values(
                    org_id=org_id,
                    league_year_id=league_year_id,
                    game_week_id=None,
                    entry_type=entry_type,
                    amount=-bonus_amt,
                    contract_id=contract_id,
                    player_id=player_id,
                    note=f"{entry_type} for contract {contract_id} (leagueYearSigned={league_year})",
                )
            )
            bonuses_created += 1

    return {
        "league_year": league_year,
        "media_entries_created": media_created,
        "media_entries_skipped": skipped_media,
        "bonus_entries_created": bonuses_created,
        "bonus_entries_skipped": skipped_bonuses,
    }

# --------------------------------------------------------
# 2) Weekly books: salaries + performance revenue
# --------------------------------------------------------

def run_week_books(engine, league_year: int, week_index: int) -> Dict[str, Any]:
    """
    Run weekly books for a given league_year and week_index:

      - Pro-rated salary expenses (per contract, per org share).
      - Performance revenue using up-to-3-year rolling wins.

    Idempotent-ish: if any salary/performance entries already exist for that week,
    it will skip and report 'already_processed'.
    """
    tables = _get_tables(engine)
    ly_tbl = tables["league_years"]
    gw_tbl = tables["game_weeks"]
    orgs_tbl = tables["organizations"]
    ledger = tables["ledger"]
    weekly = tables["weekly_record"]
    contracts = tables["contracts"]
    details = tables["details"]
    shares = tables["shares"]

    with engine.begin() as conn:
        try:
            # ---- Resolve league_year + game_week ----
            ly_row = _get_league_year_row(conn, tables, league_year)
            league_year_id = ly_row["id"]
            performance_budget = Decimal(ly_row["performance_budget"])
            weeks_in_season = int(ly_row["weeks_in_season"])

            gw_row = _get_game_week_row(conn, tables, league_year_id, week_index)
            game_week_id = gw_row["id"]

            # ---- Guard: already processed? ----
            existing_count = conn.execute(
                select(func.count(ledger.c.id)).where(
                    and_(
                        ledger.c.league_year_id == league_year_id,
                        ledger.c.game_week_id == game_week_id,
                        ledger.c.entry_type.in_(("salary", "performance")),
                    )
                )
            ).scalar_one()

            if existing_count and existing_count > 0:
                return {
                    "league_year": league_year,
                    "week_index": week_index,
                    "status": "already_processed",
                    "existing_entries": int(existing_count),
                }

            # ---- SALARY EXPENSES ----
            weekly_salary_entries = 0
            total_salary_amount = Decimal("0.00")

            league_year_expr = contracts.c.leagueYearSigned + (details.c.year - literal(1))

            salary_rows = conn.execute(
                select(
                    contracts.c.id.label("contract_id"),
                    contracts.c.playerID.label("player_id"),
                    details.c.salary.label("salary"),
                    shares.c.salary_share.label("salary_share"),
                    shares.c.orgID.label("org_id"),
                )
                .select_from(
                    contracts.join(details, details.c.contractID == contracts.c.id)
                    .join(shares, shares.c.contractDetailsID == details.c.id)
                )
                .where(
                    and_(
                        league_year_expr == league_year,
                        shares.c.salary_share > 0,
                    )
                )
            ).all()

            if weeks_in_season <= 0:
                raise ValueError("weeks_in_season must be > 0 for weekly books")

            weeks_dec = Decimal(weeks_in_season)

            salary_inserts = []
            for row in salary_rows:
                m = row._mapping
                contract_id = m["contract_id"]
                player_id = m["player_id"]
                org_id = m["org_id"]
                salary = Decimal(m["salary"])
                share = Decimal(m["salary_share"])

                weekly_salary = (salary * share) / weeks_dec
                if weekly_salary == 0:
                    continue

                salary_inserts.append(
                    {
                        "org_id": org_id,
                        "league_year_id": league_year_id,
                        "game_week_id": game_week_id,
                        "entry_type": "salary",
                        "amount": -weekly_salary,
                        "contract_id": contract_id,
                        "player_id": player_id,
                        "note": f"Weekly salary (league_year={league_year}, week={week_index})",
                    }
                )
                weekly_salary_entries += 1
                total_salary_amount += weekly_salary

            if salary_inserts:
                conn.execute(ledger.insert(), salary_inserts)

            # ---- PERFORMANCE REVENUE ----
            weekly_pot = performance_budget / weeks_dec

            ly_rows = conn.execute(
                select(ly_tbl.c.id, ly_tbl.c.league_year)
            ).all()
            year_to_id = {r._mapping["league_year"]: r._mapping["id"] for r in ly_rows}

            target_year = league_year
            years_to_consider: List[int] = [
                y for y in (target_year - 2, target_year - 1, target_year)
                if y in year_to_id
            ]
            relevant_year_ids = [year_to_id[y] for y in years_to_consider]

            org_rows = conn.execute(select(orgs_tbl.c.id)).all()
            org_ids = [r._mapping["id"] for r in org_rows]
            org_wins = {org_id: 0 for org_id in org_ids}

            rec_rows = []
            if relevant_year_ids:
                gw_tbl = tables["game_weeks"]
                rec_rows = conn.execute(
                    select(
                        weekly.c.org_id,
                        weekly.c.wins,
                        gw_tbl.c.week_index,
                        ly_tbl.c.league_year,
                    )
                    .select_from(
                        weekly
                        .join(gw_tbl, weekly.c.game_week_id == gw_tbl.c.id)
                        .join(ly_tbl, weekly.c.league_year_id == ly_tbl.c.id)
                    )
                    .where(weekly.c.league_year_id.in_(relevant_year_ids))
                ).all()

            if not rec_rows:
                # No wins history at all yet -> skip performance this week
                performance_entries = 0
                total_performance_amount = Decimal("0.00")
            else:
                # We have some results; compute rolling wins and shares
                for row in rec_rows:
                    m = row._mapping
                    org_id = m["org_id"]
                    wins = int(m["wins"])
                    y = m["league_year"]
                    wk = m["week_index"]

                    if y == target_year and wk > week_index:
                        continue
                    if org_id in org_wins:
                        org_wins[org_id] += wins
                    else:
                        org_wins[org_id] = wins

                total_wins = sum(org_wins.values())
                performance_inserts = []
                performance_entries = 0
                total_performance_amount = Decimal("0.00")

                num_orgs = len(org_ids) if org_ids else 0

                # If total_wins somehow ends up 0 even with rec_rows present (edge case):
                # you can still choose a fallback policy; here we'll just skip payouts.
                if total_wins == 0:
                    # No payouts this week
                    pass
                else:
                    for org_id in org_ids:
                        org_w = org_wins.get(org_id, 0)
                        if org_w == 0:
                            continue  # no share if no wins in window

                        share_ratio = Decimal(org_w) / Decimal(total_wins)
                        amount = weekly_pot * share_ratio
                        if amount == 0:
                            continue

                        performance_inserts.append(
                            {
                                "org_id": org_id,
                                "league_year_id": league_year_id,
                                "game_week_id": game_week_id,
                                "entry_type": "performance",
                                "amount": amount,
                                "contract_id": None,
                                "player_id": None,
                                "note": f"Weekly performance revenue (league_year={league_year}, week={week_index})",
                            }
                        )
                        performance_entries += 1
                        total_performance_amount += amount

                    if performance_inserts:
                        conn.execute(ledger.insert(), performance_inserts)

            return {
                "league_year": league_year,
                "week_index": week_index,
                "status": "processed",
                "salary_entries_created": weekly_salary_entries,
                "total_weekly_salary_out": float(total_salary_amount),
                "performance_entries_created": performance_entries,
                "total_weekly_performance_in": float(total_performance_amount),
            }

        except SQLAlchemyError:
            raise
        except ValueError:
            raise


# --------------------------------------------------------
# 3) Year-end interest on net balance
# --------------------------------------------------------

def run_year_end_interest(engine, league_year: int) -> Dict[str, Any]:
    """
    Apply interest on each org's net balance at the end of a league year.

    - If net balance > 0: interest_income (positive entry)
    - If net balance < 0: interest_expense (negative entry)

    Balance is computed as SUM(amount) over all ledger entries for that org
    whose league_year <= target year (i.e., net to date).
    """
    tables = _get_tables(engine)
    ly_tbl = tables["league_years"]
    orgs_tbl = tables["organizations"]
    ledger = tables["ledger"]

    created = 0
    skipped = 0

    with engine.begin() as conn:
        try:
            ly_row = _get_league_year_row(conn, tables, league_year)
            target_ly_id = ly_row["id"]
            target_year = ly_row["league_year"]

            # Map league_year_id -> league_year to filter by year <= target_year
            ly_rows = conn.execute(
                select(ly_tbl.c.id, ly_tbl.c.league_year)
            ).all()
            id_to_year = {r._mapping["id"]: r._mapping["league_year"] for r in ly_rows}

            org_rows = conn.execute(select(orgs_tbl.c.id)).all()
            org_ids = [r._mapping["id"] for r in org_rows]

            for org_id in org_ids:
                # Skip if we've already applied interest for this org in this year
                existing = conn.execute(
                    select(ledger.c.id)
                    .where(
                        and_(
                            ledger.c.org_id == org_id,
                            ledger.c.league_year_id == target_ly_id,
                            ledger.c.entry_type.in_(("interest_income", "interest_expense")),
                        )
                    )
                    .limit(1)
                ).first()
                if existing:
                    skipped += 1
                    continue

                # Compute net balance up to and including this league year
                # (using league_year_id -> league_year mapping)
                # We will sum all entries where league_year <= target_year
                balance = conn.execute(
                    select(func.coalesce(func.sum(ledger.c.amount), 0))
                    .select_from(ledger.join(ly_tbl, ledger.c.league_year_id == ly_tbl.c.id))
                    .where(
                        and_(
                            ledger.c.org_id == org_id,
                            ly_tbl.c.league_year <= target_year,
                        )
                    )
                ).scalar_one()

                balance_dec = Decimal(balance)

                if balance_dec == 0:
                    continue

                if balance_dec > 0:
                    interest = balance_dec * INTEREST_RATE
                    entry_type = "interest_income"
                    amount = interest  # positive
                else:
                    interest = abs(balance_dec) * INTEREST_RATE
                    entry_type = "interest_expense"
                    amount = -interest  # negative

                conn.execute(
                    ledger.insert().values(
                        org_id=org_id,
                        league_year_id=target_ly_id,
                        game_week_id=None,
                        entry_type=entry_type,
                        amount=amount,
                        contract_id=None,
                        player_id=None,
                        note=f"{entry_type} for league_year {league_year}",
                    )
                )
                created += 1

        except SQLAlchemyError:
            raise
        except ValueError:
            raise

    return {
        "league_year": league_year,
        "interest_entries_created": created,
        "interest_entries_skipped": skipped,
        "interest_rate": float(INTEREST_RATE),
    }

def run_full_season_books(engine, league_year: int) -> Dict[str, Any]:
    """
    Run the entire financial cycle for a league_year:

      1. Year-start books (media + bonuses/buyouts).
      2. Weekly books for each game_week (salary + performance).
      3. Year-end interest.

    Assumes:
      - league_years row exists and has weeks_in_season set,
      - team_weekly_record already populated for that season.
    """
    tables = _get_tables(engine)
    ly_tbl = tables["league_years"]

    with engine.begin() as conn:
        ly_row = _get_league_year_row(conn, tables, league_year)
        weeks_in_season = int(ly_row["weeks_in_season"])

    # 1) Year start
    year_start_result = run_year_start_books(engine, league_year)

    # 2) Weekly books
    weekly_results = []
    for week_index in range(1, weeks_in_season + 1):
        res = run_week_books(engine, league_year, week_index)
        weekly_results.append(res)

    # 3) Year end interest
    year_end_result = run_year_end_interest(engine, league_year)

    return {
        "league_year": league_year,
        "weeks_in_season": weeks_in_season,
        "year_start": year_start_result,
        "weeks": weekly_results,
        "year_end": year_end_result,
    }



def get_org_financial_summary(engine, org_abbrev: str, league_year: int) -> Dict[str, Any]:
    """
    Summarize an organization's finances for a league_year:

      - starting_balance: net balance from all prior years
      - year_start_events: media/bonus/buyout totals for that year (non-week entries)
      - weekly activity: per-week salary/performance/other and cumulative balance
      - interest_events: interest_income/interest_expense in that year
      - ending_balance: net balance after this year (including interest)
    """
    tables = _get_tables(engine)
    orgs = tables["organizations"]
    ly_tbl = tables["league_years"]
    gw_tbl = tables["game_weeks"]
    ledger = tables["ledger"]

    with engine.begin() as conn:
        # org lookup by abbrev (adjust column name if needed)
        org_row = conn.execute(
            select(
                orgs.c.id,
                orgs.c.org_abbrev,
            ).where(orgs.c.org_abbrev == org_abbrev)
        ).first()
        if not org_row:
            raise ValueError(f"Organization '{org_abbrev}' not found")

        org = org_row._mapping
        org_id = org["id"]

        # league_year row
        ly_row = _get_league_year_row(conn, tables, league_year)
        league_year_id = ly_row["id"]
        weeks_in_season = int(ly_row["weeks_in_season"])

        # --- Starting balance (all years < league_year) ---
        starting_balance = conn.execute(
            select(func.coalesce(func.sum(ledger.c.amount), 0))
            .select_from(ledger.join(ly_tbl, ledger.c.league_year_id == ly_tbl.c.id))
            .where(
                and_(
                    ledger.c.org_id == org_id,
                    ly_tbl.c.league_year < league_year,
                )
            )
        ).scalar_one()

        # --- Year-level (non-week) entries for this year ---
        year_level_rows = conn.execute(
            select(
                ledger.c.entry_type,
                func.coalesce(func.sum(ledger.c.amount), 0).label("total"),
            )
            .where(
                and_(
                    ledger.c.org_id == org_id,
                    ledger.c.league_year_id == league_year_id,
                    ledger.c.game_week_id.is_(None),
                )
            )
            .group_by(ledger.c.entry_type)
        ).all()

        year_level_totals: Dict[str, float] = {
            r._mapping["entry_type"]: float(r._mapping["total"]) for r in year_level_rows
        }

        year_start_events = {
            k: v
            for k, v in year_level_totals.items()
            if k in ("media", "bonus", "buyout")
        }
        interest_events = {
            k: v
            for k, v in year_level_totals.items()
            if k in ("interest_income", "interest_expense")
        }

        year_start_net = sum(year_start_events.values())
        interest_net = sum(interest_events.values())

        # balance immediately after year-start events
        balance_after_year_start = float(starting_balance) + year_start_net

        # --- Weekly entries (grouped by week_index + entry_type) ---
        weekly_rows = conn.execute(
            select(
                gw_tbl.c.week_index,
                ledger.c.entry_type,
                func.coalesce(func.sum(ledger.c.amount), 0).label("total"),
            )
            .select_from(
                ledger.join(gw_tbl, ledger.c.game_week_id == gw_tbl.c.id)
            )
            .where(
                and_(
                    ledger.c.org_id == org_id,
                    ledger.c.league_year_id == league_year_id,
                )
            )
            .group_by(gw_tbl.c.week_index, ledger.c.entry_type)
        ).all()

        # Build per-week breakdowns
        week_type_totals: Dict[int, Dict[str, float]] = {}
        for row in weekly_rows:
            m = row._mapping
            week = m["week_index"]
            etype = m["entry_type"]
            total = float(m["total"])
            wdict = week_type_totals.setdefault(week, {})
            wdict[etype] = total

        weeks_summary = []
        cumulative = balance_after_year_start

        for week_index in range(1, weeks_in_season + 1):
            by_type = week_type_totals.get(week_index, {})
            salary_total = by_type.get("salary", 0.0)       # negative
            performance_total = by_type.get("performance", 0.0)  # positive

            other_types = {
                k: v for k, v in by_type.items()
                if k not in ("salary", "performance")
            }
            other_in = sum(v for v in other_types.values() if v > 0)
            other_out = -sum(v for v in other_types.values() if v < 0)

            week_net = sum(by_type.values())  # sum of all entry_type totals
            cumulative += week_net

            weeks_summary.append({
                "week_index": week_index,
                "salary_out": -salary_total,          # present as positive outflow
                "performance_in": performance_total,
                "other_in": other_in,
                "other_out": other_out,
                "net": week_net,
                "cumulative_balance": cumulative,
                "by_type": by_type,   # optional detailed breakdown
            })

        ending_balance_before_interest = cumulative
        ending_balance = ending_balance_before_interest + interest_net

    return {
        "org": {
            "id": org_id,
            "abbrev": org["org_abbrev"],
        },
        "league_year": league_year,
        "starting_balance": float(starting_balance),
        "year_start_events": year_start_events,
        "weeks": weeks_summary,
        "interest_events": interest_events,
        "ending_balance_before_interest": ending_balance_before_interest,
        "ending_balance": ending_balance,
    }
