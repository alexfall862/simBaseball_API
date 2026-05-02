# financials/books.py

import random
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List

from sqlalchemy import (
    MetaData,
    Table,
    select,
    and_,
    func,
    literal,
    desc,
    text,
)
from sqlalchemy.exc import SQLAlchemyError


INTEREST_RATE = Decimal("0.05")  # 5% annual

# Performance revenue: 65% attributed to home games (gate/tickets),
# 35% to away games (broadcast/merch). Season totals are preserved;
# this only shifts *when* revenue is recognized week-to-week.
HOME_REVENUE_WEIGHT = Decimal("0.65")
AWAY_REVENUE_WEIGHT = Decimal("0.35")


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
        "players": Table("simbbPlayers", md, autoload_with=engine),
        "gamelist": Table("gamelist", md, autoload_with=engine),
        "teams": Table("teams", md, autoload_with=engine),
        "seasons": Table("seasons", md, autoload_with=engine),
        "financial_config": Table("financial_config", md, autoload_with=engine),
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

    Idempotent: media and bonuses each claim their own column on league_years
    (media_run_at, bonuses_run_at) via a single-statement UPDATE so concurrent
    callers can't both pass the guard and double-insert.
    """
    tables = _get_tables(engine)
    ly_tbl = tables["league_years"]
    media_tbl = tables["media_shares"]
    ledger = tables["ledger"]
    contracts = tables["contracts"]

    media_created = 0
    bonuses_created = 0
    media_status = "processed"
    bonuses_status = "processed"

    with engine.begin() as conn:
        ly_row = _get_league_year_row(conn, tables, league_year)
        league_year_id = ly_row["id"]
        media_total = Decimal(ly_row["media_total"])

        # ---- MEDIA PAYOUTS ----
        media_claim = conn.execute(
            text(
                "UPDATE league_years SET media_run_at = NOW() "
                "WHERE id = :ly_id AND media_run_at IS NULL"
            ),
            {"ly_id": league_year_id},
        )

        if media_claim.rowcount == 0:
            media_status = "already_processed"
        else:
            media_rows = conn.execute(
                select(
                    media_tbl.c.org_id,
                    media_tbl.c.media_share,
                ).where(media_tbl.c.league_year_id == league_year_id)
            ).all()

            media_inserts = []
            for row in media_rows:
                m = row._mapping
                org_id = m["org_id"]
                share = Decimal(m["media_share"])
                amount = media_total * share

                media_inserts.append({
                    "org_id": org_id,
                    "league_year_id": league_year_id,
                    "game_week_id": None,
                    "entry_type": "media",
                    "amount": amount,
                    "contract_id": None,
                    "player_id": None,
                    "note": f"Media payout for league_year {league_year}",
                })

            if media_inserts:
                conn.execute(ledger.insert(), media_inserts)
                media_created = len(media_inserts)

        # ---- BONUSES / BUYOUTS ----
        bonuses_claim = conn.execute(
            text(
                "UPDATE league_years SET bonuses_run_at = NOW() "
                "WHERE id = :ly_id AND bonuses_run_at IS NULL"
            ),
            {"ly_id": league_year_id},
        )

        if bonuses_claim.rowcount == 0:
            bonuses_status = "already_processed"
        else:
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

            bonus_inserts = []
            for row in bonus_rows:
                m = row._mapping
                contract_id = m["contract_id"]
                player_id = m["player_id"]
                org_id = m["org_id"]
                is_buyout = bool(m["isBuyout"])
                bonus_amt = Decimal(m["bonus"])

                entry_type = "buyout" if is_buyout else "bonus"

                bonus_inserts.append({
                    "org_id": org_id,
                    "league_year_id": league_year_id,
                    "game_week_id": None,
                    "entry_type": entry_type,
                    "amount": -bonus_amt,
                    "contract_id": contract_id,
                    "player_id": player_id,
                    "note": f"{entry_type} for contract {contract_id} (leagueYearSigned={league_year})",
                })

            if bonus_inserts:
                conn.execute(ledger.insert(), bonus_inserts)
                bonuses_created = len(bonus_inserts)

    return {
        "league_year": league_year,
        "media_status": media_status,
        "media_entries_created": media_created,
        "bonuses_status": bonuses_status,
        "bonus_entries_created": bonuses_created,
    }

# --------------------------------------------------------
# 2) Weekly books: salaries + performance revenue
# --------------------------------------------------------

def run_week_books(engine, league_year: int, week_index: int) -> Dict[str, Any]:
    """
    Run weekly books for a given league_year and week_index:

      - Pro-rated salary expenses (per contract, per org share).
      - Performance revenue using up-to-3-year rolling wins.

    Idempotent: claims the week atomically by setting game_weeks.books_run_at
    via a single UPDATE ... WHERE books_run_at IS NULL. Concurrent callers
    coming from /admin/run-week-books, run_all_levels, or advance_week can
    no longer both pass the guard and double-insert ledger rows.
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

            # ---- Atomic claim: only one caller can flip books_run_at from NULL ----
            # Single-statement UPDATE serializes concurrent run_week_books calls
            # at the row level; rowcount==0 means another caller has already
            # claimed (and committed, or will commit) this week.
            claim = conn.execute(
                text(
                    "UPDATE game_weeks SET books_run_at = NOW() "
                    "WHERE id = :gw_id AND books_run_at IS NULL"
                ),
                {"gw_id": game_week_id},
            )

            if claim.rowcount == 0:
                return {
                    "league_year": league_year,
                    "week_index": week_index,
                    "status": "already_processed",
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
                        contracts.c.isFinished == 0,
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

                weekly_salary = ((salary * share) / weeks_dec).quantize(Decimal("0.01"))
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

            # ---- PERFORMANCE REVENUE (home/away weighted) ----
            # Rolling win share determines each org's season-long slice of the
            # performance_budget.  Home/away game counts determine *when* that
            # slice is recognised: 65 % attributed to home games (gate revenue),
            # 35 % to away games (broadcast/merch).  Season totals per org are
            # preserved; only the weekly timing shifts.

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
                # Compute rolling wins per org
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

                if total_wins == 0:
                    pass
                else:
                    # --- Home/away game counts for weighted distribution ---
                    gl = tables["gamelist"]
                    teams_tbl = tables["teams"]
                    seasons_tbl = tables["seasons"]

                    # Resolve season IDs that correspond to this league_year
                    season_rows = conn.execute(
                        select(seasons_tbl.c.id)
                        .where(seasons_tbl.c.year == league_year)
                    ).all()
                    season_ids = [r._mapping["id"] for r in season_rows]

                    # Full-season home/away counts per org
                    org_home_season: Dict[int, int] = {}
                    org_away_season: Dict[int, int] = {}
                    # This-week home/away counts per org
                    org_home_week: Dict[int, int] = {}
                    org_away_week: Dict[int, int] = {}

                    if season_ids:
                        for rows_dict, join_col, week_filter in [
                            (org_home_season, gl.c.home_team, False),
                            (org_away_season, gl.c.away_team, False),
                            (org_home_week,   gl.c.home_team, True),
                            (org_away_week,   gl.c.away_team, True),
                        ]:
                            conditions = [
                                gl.c.season.in_(season_ids),
                                gl.c.league_level == 9,
                                gl.c.game_type == "regular",
                            ]
                            if week_filter:
                                conditions.append(gl.c.season_week == week_index)
                            qrows = conn.execute(
                                select(
                                    teams_tbl.c.orgID.label("org_id"),
                                    func.count().label("cnt"),
                                )
                                .select_from(
                                    gl.join(teams_tbl, join_col == teams_tbl.c.id)
                                )
                                .where(and_(*conditions))
                                .group_by(teams_tbl.c.orgID)
                            ).all()
                            for r in qrows:
                                rows_dict[r._mapping["org_id"]] = int(r._mapping["cnt"])

                    for org_id in org_ids:
                        org_w = org_wins.get(org_id, 0)
                        if org_w == 0:
                            continue

                        win_share = Decimal(org_w) / Decimal(total_wins)
                        org_season_share = performance_budget * win_share

                        # Weighted season total for this org
                        h_season = Decimal(org_home_season.get(org_id, 0))
                        a_season = Decimal(org_away_season.get(org_id, 0))
                        season_weight = (h_season * HOME_REVENUE_WEIGHT
                                         + a_season * AWAY_REVENUE_WEIGHT)

                        # Weighted count for this week
                        h_week = Decimal(org_home_week.get(org_id, 0))
                        a_week = Decimal(org_away_week.get(org_id, 0))
                        week_weight = (h_week * HOME_REVENUE_WEIGHT
                                       + a_week * AWAY_REVENUE_WEIGHT)

                        if season_weight == 0:
                            # No games scheduled — fall back to flat distribution
                            amount = org_season_share / weeks_dec
                        elif week_weight == 0:
                            # Bye week for this org — no revenue
                            continue
                        else:
                            amount = (org_season_share * (week_weight / season_weight)).quantize(Decimal("0.01"))

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

    Idempotent: claims league_years.interest_run_at atomically; concurrent
    callers can no longer both pass the per-org existence check.
    """
    tables = _get_tables(engine)
    ly_tbl = tables["league_years"]
    orgs_tbl = tables["organizations"]
    ledger = tables["ledger"]

    created = 0

    with engine.begin() as conn:
        try:
            ly_row = _get_league_year_row(conn, tables, league_year)
            target_ly_id = ly_row["id"]
            target_year = ly_row["league_year"]

            # ---- Atomic claim ----
            claim = conn.execute(
                text(
                    "UPDATE league_years SET interest_run_at = NOW() "
                    "WHERE id = :ly_id AND interest_run_at IS NULL"
                ),
                {"ly_id": target_ly_id},
            )
            if claim.rowcount == 0:
                return {
                    "league_year": league_year,
                    "status": "already_processed",
                    "interest_rate": float(INTEREST_RATE),
                }

            org_rows = conn.execute(
                select(orgs_tbl.c.id, orgs_tbl.c.cash)
            ).all()
            org_ids = [r._mapping["id"] for r in org_rows]
            org_seed = {r._mapping["id"]: Decimal(r._mapping["cash"] or 0) for r in org_rows}

            for org_id in org_ids:
                # Compute net balance: seed capital + all ledger entries up to this year
                ledger_balance = conn.execute(
                    select(func.coalesce(func.sum(ledger.c.amount), 0))
                    .select_from(ledger.join(ly_tbl, ledger.c.league_year_id == ly_tbl.c.id))
                    .where(
                        and_(
                            ledger.c.org_id == org_id,
                            ly_tbl.c.league_year <= target_year,
                        )
                    )
                ).scalar_one()

                balance_dec = org_seed.get(org_id, Decimal(0)) + Decimal(ledger_balance)

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
        "status": "processed",
        "interest_entries_created": created,
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

        # Seed capital from organizations.cash (initial funds before any ledger activity)
        seed_capital = conn.execute(
            select(func.coalesce(orgs.c.cash, 0))
            .where(orgs.c.id == org_id)
        ).scalar_one()

        # --- Starting balance: seed capital + all prior-year ledger entries ---
        ledger_prior = conn.execute(
            select(func.coalesce(func.sum(ledger.c.amount), 0))
            .select_from(ledger.join(ly_tbl, ledger.c.league_year_id == ly_tbl.c.id))
            .where(
                and_(
                    ledger.c.org_id == org_id,
                    ly_tbl.c.league_year < league_year,
                )
            )
        ).scalar_one()
        starting_balance = Decimal(seed_capital) + Decimal(ledger_prior)

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
        playoff_events = {
            k: v
            for k, v in year_level_totals.items()
            if k in ("playoff_gate", "playoff_media")
        }
        interest_events = {
            k: v
            for k, v in year_level_totals.items()
            if k in ("interest_income", "interest_expense")
        }

        year_start_net = sum(year_start_events.values())
        playoff_net = sum(playoff_events.values())
        interest_net = sum(interest_events.values())

        # balance immediately after year-start events (playoff revenue is also year-level)
        balance_after_year_start = float(starting_balance) + year_start_net + playoff_net

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
        "playoff_events": playoff_events,
        "weeks": weeks_summary,
        "interest_events": interest_events,
        "ending_balance_before_interest": ending_balance_before_interest,
        "ending_balance": ending_balance,
    }


# --------------------------------------------------------
# League year initialization with inflation
# --------------------------------------------------------

def initialize_next_league_year(engine, current_league_year: int) -> Dict[str, Any]:
    """
    Create the next league_years row by applying inflation to the current
    year's performance_budget and media_total.

    Reads inflation bounds from financial_config, samples a rate using a
    triangular distribution (min, max, mode=mean), and multiplies the
    current year's budgets.  Also creates the game_weeks rows for the
    new year.

    Returns summary dict with the new year's values and applied rate.
    Idempotent: raises ValueError if the next year already exists.
    """
    tables = _get_tables(engine)
    ly_tbl = tables["league_years"]
    gw_tbl = tables["game_weeks"]
    fc_tbl = tables["financial_config"]

    with engine.begin() as conn:
        # ---- Current year ----
        cur = _get_league_year_row(conn, tables, current_league_year)
        next_year = current_league_year + 1

        # ---- Guard: next year must not exist ----
        existing = conn.execute(
            select(ly_tbl.c.id).where(ly_tbl.c.league_year == next_year)
        ).first()
        if existing:
            raise ValueError(
                f"league_year {next_year} already exists (id={existing._mapping['id']})"
            )

        # ---- Read financial_config ----
        fc_row = conn.execute(select(fc_tbl)).first()
        if not fc_row:
            raise ValueError("financial_config table is empty — seed it first")
        fc = fc_row._mapping

        inf_min = float(fc["inflation_min"])
        inf_max = float(fc["inflation_max"])
        inf_mean = float(fc["inflation_mean"])

        # ---- Sample inflation rate (triangular distribution) ----
        inflation_rate = random.triangular(inf_min, inf_max, inf_mean)
        # Clamp to configured bounds (triangular already does this, but be safe)
        inflation_rate = max(inf_min, min(inf_max, inflation_rate))
        inflation_factor = Decimal(str(round(inflation_rate, 4)))
        multiplier = Decimal("1") + inflation_factor

        # ---- Compute new budgets ----
        prev_perf = Decimal(str(cur["performance_budget"]))
        prev_media = Decimal(str(cur["media_total"]))
        weeks_in_season = int(cur["weeks_in_season"])

        new_perf = (prev_perf * multiplier).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        new_media = (prev_media * multiplier).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # ---- Insert new league_years row ----
        result = conn.execute(
            ly_tbl.insert().values(
                league_year=next_year,
                performance_budget=new_perf,
                media_total=new_media,
                inflation_factor=inflation_factor,
                weeks_in_season=weeks_in_season,
            )
        )
        new_ly_id = result.lastrowid

        # ---- Create game_weeks for the new year ----
        gw_inserts = [
            {
                "league_year_id": new_ly_id,
                "week_index": w,
                "label": f"Week {w}",
            }
            for w in range(1, weeks_in_season + 1)
        ]
        if gw_inserts:
            conn.execute(gw_tbl.insert(), gw_inserts)

    return {
        "league_year": next_year,
        "league_year_id": new_ly_id,
        "previous_year": current_league_year,
        "inflation_rate": float(inflation_factor),
        "inflation_bounds": {
            "min": inf_min,
            "max": inf_max,
            "mean": inf_mean,
        },
        "performance_budget": {
            "previous": float(prev_perf),
            "new": float(new_perf),
        },
        "media_total": {
            "previous": float(prev_media),
            "new": float(new_media),
        },
        "weeks_in_season": weeks_in_season,
        "game_weeks_created": len(gw_inserts),
    }


# --------------------------------------------------------
# Playoff revenue: gate + media
# --------------------------------------------------------

PLAYOFF_LEVEL = 9  # MLB only


def process_playoff_revenue(engine, league_year: int) -> Dict[str, Any]:
    """
    Generate playoff revenue ledger entries for a completed postseason.

    Two revenue streams, both anchored to existing economy baselines:

    1. **Playoff gate** — each playoff home game earns the org
       `regular_per_home_game_value × playoff_gate_multiplier`.
       The regular per-home-game value is derived from the org's
       performance_budget share (win-weighted) and the 65% home weight,
       the same formula used in weekly books.

    2. **Playoff media** — each org earns a flat payout per series
       appearance, derived from `media_total × playoff_media_fraction`
       divided by total team-series slots.

    Idempotent: skips if playoff_gate or playoff_media entries already
    exist for this league_year.
    """
    tables = _get_tables(engine)
    ly_tbl = tables["league_years"]
    orgs_tbl = tables["organizations"]
    ledger = tables["ledger"]
    weekly = tables["weekly_record"]
    gl = tables["gamelist"]
    teams_tbl = tables["teams"]
    seasons_tbl = tables["seasons"]
    fc_tbl = tables["financial_config"]

    with engine.begin() as conn:
        ly_row = _get_league_year_row(conn, tables, league_year)
        league_year_id = ly_row["id"]
        performance_budget = Decimal(ly_row["performance_budget"])
        media_total = Decimal(ly_row["media_total"])

        # ---- Atomic claim: only one caller can flip playoff_revenue_run_at from NULL ----
        claim = conn.execute(
            text(
                "UPDATE league_years SET playoff_revenue_run_at = NOW() "
                "WHERE id = :ly_id AND playoff_revenue_run_at IS NULL"
            ),
            {"ly_id": league_year_id},
        )
        if claim.rowcount == 0:
            return {
                "league_year": league_year,
                "status": "already_processed",
            }

        # ---- Read config ----
        fc_row = conn.execute(select(fc_tbl)).first()
        if not fc_row:
            raise ValueError("financial_config table is empty")
        fc = fc_row._mapping

        gate_mult = Decimal(str(fc.get("playoff_gate_multiplier", 5)))
        media_frac = Decimal(str(fc.get("playoff_media_fraction", "0.10")))

        # ==================================================================
        # 1. PLAYOFF GATE REVENUE
        # ==================================================================

        # ---- Compute each org's regular per-home-game value ----
        # Same rolling 3-year win share as weekly books
        ly_rows = conn.execute(
            select(ly_tbl.c.id, ly_tbl.c.league_year)
        ).all()
        year_to_id = {r._mapping["league_year"]: r._mapping["id"] for r in ly_rows}

        years_to_consider = [
            y for y in (league_year - 2, league_year - 1, league_year)
            if y in year_to_id
        ]
        relevant_year_ids = [year_to_id[y] for y in years_to_consider]

        org_rows = conn.execute(select(orgs_tbl.c.id)).all()
        org_ids = [r._mapping["id"] for r in org_rows]
        org_wins: Dict[int, int] = {oid: 0 for oid in org_ids}

        if relevant_year_ids:
            gw_tbl = tables["game_weeks"]
            rec_rows = conn.execute(
                select(weekly.c.org_id, weekly.c.wins)
                .where(weekly.c.league_year_id.in_(relevant_year_ids))
            ).all()
            for r in rec_rows:
                m = r._mapping
                oid = m["org_id"]
                if oid in org_wins:
                    org_wins[oid] += int(m["wins"])

        total_wins = sum(org_wins.values())

        # Regular-season home game counts per org (full season)
        season_rows = conn.execute(
            select(seasons_tbl.c.id).where(seasons_tbl.c.year == league_year)
        ).all()
        season_ids = [r._mapping["id"] for r in season_rows]

        org_home_season: Dict[int, int] = {}
        if season_ids:
            home_rows = conn.execute(
                select(
                    teams_tbl.c.orgID.label("org_id"),
                    func.count().label("cnt"),
                )
                .select_from(gl.join(teams_tbl, gl.c.home_team == teams_tbl.c.id))
                .where(and_(
                    gl.c.season.in_(season_ids),
                    gl.c.league_level == PLAYOFF_LEVEL,
                    gl.c.game_type == "regular",
                ))
                .group_by(teams_tbl.c.orgID)
            ).all()
            for r in home_rows:
                org_home_season[r._mapping["org_id"]] = int(r._mapping["cnt"])

        # Compute per-org regular home game value
        org_per_home: Dict[int, Decimal] = {}
        if total_wins > 0:
            for oid in org_ids:
                w = org_wins.get(oid, 0)
                homes = org_home_season.get(oid, 0)
                if w == 0 or homes == 0:
                    continue
                win_share = Decimal(w) / Decimal(total_wins)
                org_season_share = performance_budget * win_share
                # Home-attributed portion / number of home games
                org_per_home[oid] = (
                    org_season_share * HOME_REVENUE_WEIGHT / Decimal(homes)
                )

        # ---- Count playoff home games per org ----
        playoff_home: Dict[int, int] = {}
        if season_ids:
            ph_rows = conn.execute(
                select(
                    teams_tbl.c.orgID.label("org_id"),
                    func.count().label("cnt"),
                )
                .select_from(gl.join(teams_tbl, gl.c.home_team == teams_tbl.c.id))
                .where(and_(
                    gl.c.season.in_(season_ids),
                    gl.c.league_level == PLAYOFF_LEVEL,
                    gl.c.game_type == "playoff",
                ))
                .group_by(teams_tbl.c.orgID)
            ).all()
            for r in ph_rows:
                playoff_home[r._mapping["org_id"]] = int(r._mapping["cnt"])

        # ---- Create gate entries ----
        gate_inserts = []
        total_gate = Decimal("0")
        for oid, home_games in playoff_home.items():
            base_val = org_per_home.get(oid)
            if not base_val:
                continue
            amount = (base_val * gate_mult * Decimal(home_games)).quantize(Decimal("0.01"))
            gate_inserts.append({
                "org_id": oid,
                "league_year_id": league_year_id,
                "game_week_id": None,
                "entry_type": "playoff_gate",
                "amount": amount,
                "contract_id": None,
                "player_id": None,
                "note": (
                    f"Playoff gate revenue: {home_games} home game(s) "
                    f"× {float(base_val * gate_mult):.2f}/game "
                    f"(league_year={league_year})"
                ),
            })
            total_gate += amount

        if gate_inserts:
            conn.execute(ledger.insert(), gate_inserts)

        # ==================================================================
        # 2. PLAYOFF MEDIA REVENUE
        # ==================================================================

        # Series appearances per org: count team_a + team_b from playoff_series
        series_app: Dict[int, int] = {}

        app_rows = conn.execute(text("""
            SELECT t.orgID AS org_id, COUNT(*) AS cnt
            FROM playoff_series ps
            JOIN teams t ON t.id = ps.team_a_id
            WHERE ps.league_year_id = :lyid
              AND ps.league_level = :lvl
            GROUP BY t.orgID
            UNION ALL
            SELECT t.orgID AS org_id, COUNT(*) AS cnt
            FROM playoff_series ps
            JOIN teams t ON t.id = ps.team_b_id
            WHERE ps.league_year_id = :lyid
              AND ps.league_level = :lvl
            GROUP BY t.orgID
        """), {"lyid": league_year_id, "lvl": PLAYOFF_LEVEL}).all()

        for r in app_rows:
            oid = r._mapping["org_id"]
            series_app[oid] = series_app.get(oid, 0) + int(r._mapping["cnt"])

        total_team_series_slots = sum(series_app.values())

        media_inserts = []
        total_media = Decimal("0")

        if total_team_series_slots > 0:
            playoff_media_pool = media_total * media_frac
            per_team_per_series = playoff_media_pool / Decimal(total_team_series_slots)

            for oid, appearances in series_app.items():
                amount = (per_team_per_series * Decimal(appearances)).quantize(Decimal("0.01"))
                media_inserts.append({
                    "org_id": oid,
                    "league_year_id": league_year_id,
                    "game_week_id": None,
                    "entry_type": "playoff_media",
                    "amount": amount,
                    "contract_id": None,
                    "player_id": None,
                    "note": (
                        f"Playoff media revenue: {appearances} series "
                        f"× {float(per_team_per_series):.2f}/series "
                        f"(league_year={league_year})"
                    ),
                })
                total_media += amount

        if media_inserts:
            conn.execute(ledger.insert(), media_inserts)

    return {
        "league_year": league_year,
        "status": "processed",
        "config": {
            "gate_multiplier": float(gate_mult),
            "media_fraction": float(media_frac),
        },
        "gate": {
            "entries_created": len(gate_inserts),
            "total_amount": float(total_gate),
            "orgs_with_home_games": len(playoff_home),
        },
        "media": {
            "entries_created": len(media_inserts),
            "total_amount": float(total_media),
            "total_team_series_slots": total_team_series_slots,
            "per_team_per_series": float(per_team_per_series) if total_team_series_slots > 0 else 0,
        },
    }
