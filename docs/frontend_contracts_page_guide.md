# Frontend Guide: Building a Full Contracts Page

## Goal

A contracts page where a team can view all of their committed contracts year-over-year for the next 5 years. This is the financial planning view — think of it like an MLB team's payroll obligations table.

---

## Data Model Primer

Understanding how contracts are stored is essential for building this page.

### Three-Table Chain

Every active contract is represented by a chain of three tables:

```
contracts (the deal)
  └─ contractDetails (one row per year of the deal, with salary)
       └─ contractTeamShare (who pays, and how much)
```

**Example:** A 3-year, $15M deal signed in 2026:

| Table | Key Fields |
|-------|------------|
| `contracts` | id=100, playerID=42, years=3, current_year=1, leagueYearSigned=2026 |
| `contractDetails` | contractID=100, year=1, salary=$4,000,000 |
| `contractDetails` | contractID=100, year=2, salary=$5,000,000 |
| `contractDetails` | contractID=100, year=3, salary=$6,000,000 |
| `contractTeamShare` | contractDetailsID=each above, orgID=1, isHolder=1, salary_share=1.00 |

### Mapping Contract Years to Real Years

The formula to determine which league year a contract detail row corresponds to:

```
actual_league_year = leagueYearSigned + (detail.year - 1)
```

So for our example signed in 2026:
- year 1 → 2026
- year 2 → 2027
- year 3 → 2028

### Salary Retention (Trades)

When a player is traded with salary retention, each `contractDetails` row gets **two** `contractTeamShare` rows:

| contractDetailsID | orgID | isHolder | salary_share |
|-------------------|-------|----------|--------------|
| 201 | 1 (old team) | 0 | 0.30 |
| 201 | 5 (new team) | 1 | 0.70 |

The old team pays 30% of the salary but doesn't hold the player. The new team pays 70% and controls the player.

**For the contracts page:** Show the team's actual dollar obligation, not the gross salary. Multiply `salary × salary_share` for each org.

### Extensions

An extension is a separate `contracts` row with `isExtension=1`. It's created ahead of time but doesn't "activate" until the original contract expires at end-of-season.

**Key:** The extension's `leagueYearSigned` is set to the year the original contract ends. So it naturally continues the timeline.

For the 5-year view, you need to include both the current contract AND any pending extension to show the full future commitment.

### Buyouts

A buyout creates a 1-year contract with `isBuyout=1`, salary=$0, and the buyout amount stored as `bonus`. The original contract is marked `isFinished=1`. Buyouts appear as a one-time cost in the year they're executed.

### Auto-Renewals

At end-of-season, expiring minor league and pre-arb contracts get auto-renewed as new 1-year contracts. These show up in the transaction log as type `renewal`. They won't exist in the database until EOS processing runs, so the contracts page can't show them as "projected" — but you can flag players whose contracts are expiring and indicate they'll auto-renew based on their `contract_phase`.

---

## Available Endpoints

### Currently Available

| Endpoint | What It Returns | Limitation for 5-Year View |
|----------|----------------|---------------------------|
| `GET /transactions/roster/{org_id}` | All held players with current year salary | Only year 1 salary, no future years |
| `GET /transactions/contract-overview/{org_id}` | All held players with service time + phase | Only current year salary, no future years |
| `GET /transactions/contract-status/{player_id}` | Single player enriched contract info | Only current year salary |
| `GET /transactions/signing-budget/{org_id}?league_year_id=X` | Available signing budget | Single number, no breakdown |

### What's Missing

**None of the existing endpoints return the full multi-year salary schedule.** They all join to `contractDetails` on `year = current_year` and return only the current salary.

To build the 5-year view, the frontend needs a new endpoint (or a SQL console query) that returns all `contractDetails` rows for all active contracts held by an org.

### Recommended New Endpoint

**`GET /api/v1/transactions/payroll-projection/{org_id}`**

This endpoint should return every future salary commitment for the org, mapped to actual league years.

**Suggested response shape:**
```json
{
  "org_id": 1,
  "current_league_year": 2026,
  "players": [
    {
      "player_id": 42,
      "player_name": "John Smith",
      "position": "Pitcher",
      "age": 27,
      "contract_id": 100,
      "is_extension": false,
      "contract_phase": "pre_arb",
      "mlb_service_years": 2,
      "current_level": 9,
      "bonus": 500000.00,
      "salary_schedule": [
        { "league_year": 2026, "contract_year": 1, "gross_salary": 4000000.00, "team_share": 1.00, "team_owes": 4000000.00, "is_current": true },
        { "league_year": 2027, "contract_year": 2, "gross_salary": 5000000.00, "team_share": 1.00, "team_owes": 5000000.00, "is_current": false },
        { "league_year": 2028, "contract_year": 3, "gross_salary": 6000000.00, "team_share": 1.00, "team_owes": 6000000.00, "is_current": false }
      ]
    },
    {
      "player_id": 55,
      "player_name": "Jane Doe",
      "position": "Position",
      "age": 30,
      "contract_id": 110,
      "is_extension": false,
      "contract_phase": "fa_eligible",
      "mlb_service_years": 7,
      "current_level": 9,
      "bonus": 0,
      "salary_schedule": [
        { "league_year": 2026, "contract_year": 2, "gross_salary": 12000000.00, "team_share": 0.70, "team_owes": 8400000.00, "is_current": true }
      ]
    }
  ],
  "year_totals": {
    "2026": { "total_salary": 12400000.00, "player_count": 2 },
    "2027": { "total_salary": 5000000.00, "player_count": 1 },
    "2028": { "total_salary": 6000000.00, "player_count": 1 }
  },
  "dead_money": [
    {
      "player_id": 80,
      "player_name": "Released Guy",
      "contract_id": 95,
      "remaining": [
        { "league_year": 2026, "team_owes": 2000000.00 },
        { "league_year": 2027, "team_owes": 2000000.00 }
      ]
    }
  ]
}
```

### SQL Query for the Projection (for reference)

Until the endpoint exists, this SQL assembles the data needed:

```sql
SELECT
    c.id            AS contract_id,
    c.playerID      AS player_id,
    p.firstname,
    p.lastname,
    p.ptype         AS position,
    p.age,
    c.years,
    c.current_year,
    c.current_level,
    c.isExtension,
    c.isBuyout,
    c.bonus,
    c.leagueYearSigned,
    d.year          AS contract_year,
    d.salary        AS gross_salary,
    s.orgID,
    s.isHolder,
    s.salary_share,
    ROUND(d.salary * s.salary_share, 2)  AS team_owes,
    (c.leagueYearSigned + d.year - 1)    AS league_year,
    COALESCE(pst.mlb_service_years, 0)   AS mlb_service_years
FROM contracts c
JOIN contractDetails d ON d.contractID = c.id
JOIN contractTeamShare s ON s.contractDetailsID = d.id
JOIN simbbPlayers p ON p.id = c.playerID
LEFT JOIN player_service_time pst ON pst.player_id = c.playerID
WHERE c.isFinished = 0
  AND s.orgID = ?          -- the org we're viewing
  AND d.year >= c.current_year  -- only current + future years
ORDER BY
    (c.leagueYearSigned + d.year - 1),  -- by league year
    d.salary DESC;                        -- highest salary first
```

**Important:** This query returns rows for BOTH held contracts (isHolder=1) and retained salary obligations (isHolder=0). The frontend should display these differently.

---

## Page Layout Recommendations

### Primary View: Payroll Table

A pivot table with players as rows and league years as columns:

```
                    2026         2027         2028         2029         2030
─────────────────────────────────────────────────────────────────────────────
MLB (Level 9)
  John Smith (P)    $4,000,000   $5,000,000   $6,000,000    —            —
  Jane Doe (IF)     $8,400,000*   —            —            —            —
  Bob Jones (OF)    $800,000      —†           —†           —†           —†

AAA (Level 8)
  Mike Lee (P)      $40,000       —†           —†           —†           —†

─────────────────────────────────────────────────────────────────────────────
Committed Total     $13,240,000  $5,000,000   $6,000,000   $0           $0
Projected Renewals‡  —           $840,000      —            —            —
Dead Money          $2,000,000   $2,000,000    —            —            —
─────────────────────────────────────────────────────────────────────────────
Grand Total         $15,240,000  $7,840,000   $6,000,000   $0           $0
```

Legend:
- `*` = Salary retention (team pays 70% of $12M gross)
- `†` = Projected auto-renewal (minor at $40K, pre-arb at $800K)
- `‡` = Estimated, actual renewals happen at end-of-season

### Row Annotations

Each player row should show:
- **Name and position**
- **Phase badge** (Minor / Pre-Arb / Arb / FA Eligible)
- **Service years** (e.g., "2 SVC")
- **Contract info** (Year X of Y)
- **Extension indicator** if `has_extension: true`

### Column Logic

For each future year column:
1. **Guaranteed salary** — from `contractDetails` rows where `leagueYearSigned + year - 1 = column_year`
2. **Extension salary** — from extension contracts where `leagueYearSigned + year - 1 = column_year`
3. **Projected renewal** — if no contractDetails row exists for that year AND the player's contract expires before it AND their phase is `minor` or `pre_arb`, show the renewal salary ($40K or $800K) as projected/italic
4. **Empty** — if the player will become a free agent before that year

### Sections

Split the table into logical groups:
1. **Active Roster Commitments** — contracts where `isHolder=1`, grouped by level
2. **Dead Money** — contracts where `isHolder=0` (salary retention from trades) or released player obligations
3. **Pending Extensions** — extension contracts that haven't activated yet (show them inline with their player, greyed out until they kick in)

### Summary Cards

Above the table, show aggregate stats:
- **Total Payroll (Current Year):** Sum of all team_owes for current league year
- **Committed Future:** Sum of all guaranteed money beyond current year
- **Dead Money:** Sum of retained salary obligations
- **Signing Budget:** From `/signing-budget/{org_id}`
- **Expiring After This Season:** Count of contracts in final year
- **Players Approaching FA:** Count of players with `years_to_fa <= 2`

---

## How to Handle Each Contract Scenario

### Standard Contract (isHolder=1, isExtension=0, isBuyout=0)
Display normally. Show salary in each year column.

### Traded Player with Retention (isHolder=0)
Show under "Dead Money" section. Display the retained portion (`salary × salary_share`) in each remaining year. Use a muted/italic style to distinguish from active roster.

### Traded Player You Received (isHolder=1, salary_share < 1.0)
Show on active roster. Display the team's share (`salary × salary_share`) as the primary number, with the gross salary as a tooltip or secondary display. Mark with an asterisk or "retained" label.

### Extension Contract (isExtension=1)
Don't show as a separate row. Instead, append the extension years to the original player's row. Use a visual divider (dotted border, different shade) to show where the extension begins.

### Buyout Contract (isBuyout=1)
Show the buyout amount (stored as `bonus`) in the year it was executed. Typically a single-year blip. Can group under "Dead Money" since the player was bought out.

### Auto-Renewal Projection
For players with `is_expiring: true` and `contract_phase` of `minor` or `pre_arb`, show a projected column entry in the next year at the renewal salary. Style it differently (dashed border, lighter color) since it's projected, not committed.

---

## Interaction Features

### Click-Through
Clicking a player row should navigate to their player detail page or open a drawer showing:
- Full contract details (all years with salary)
- Service time timeline
- Transaction history for this player
- Available actions (extend, release, buyout, trade)

### Filters
- By level (MLB only, Minor only, All)
- By phase (show only arb-eligible, FA-eligible, etc.)
- By expiration (expiring this year, expiring within 2 years)

### Sorting
- By salary (highest first)
- By years remaining (most committed first)
- By service time
- By age

### Year Range Toggle
Let users view 3, 5, or all committed years.

---

## Data Assembly Strategy

Since the multi-year endpoint doesn't exist yet, here's how to build the view with existing endpoints:

### Option A: Two API Calls (Recommended Short-Term)

1. `GET /transactions/contract-overview/{org_id}` → Get all players with phase/service time
2. For each player, the current salary is returned but future years aren't

This gives you the roster with phase info but only current-year salary. Future years would need to be marked as "data not available" or estimated.

### Option B: SQL Console Query (Admin Only)

Use the SQL query above via `/admin/sql` to get the full projection. This works for admin tools but isn't suitable for the user-facing frontend.

### Option C: New Payroll Projection Endpoint (Recommended)

Build `GET /transactions/payroll-projection/{org_id}` that returns the full multi-year data. This is the right long-term solution. The service function would:

1. Query all active contracts where the org appears in `contractTeamShare`
2. Include ALL `contractDetails` rows (not just current year)
3. Include extension contracts for held players
4. Join to `player_service_time` for phase calculation
5. Compute `team_owes = salary × salary_share` for each row
6. Aggregate year totals

---

## Contract Constants Reference

| Constant | Value | Usage |
|----------|-------|-------|
| Minor league salary | $40,000 | Auto-renewal salary for levels 4-8 |
| Pre-arb MLB salary | $800,000 | Auto-renewal salary for MLB with < 3 service years |
| Arbitration threshold | 3 service years | Players become arb-eligible |
| Free agency threshold | 6 service years | Players become FA-eligible |
| Max contract length | 5 years | Enforced at signing/extension time |
| Salary retention | 0-100% | Set per-player during trades |

## Level Reference

| Level ID | Name | Max Roster |
|----------|------|------------|
| 9 | MLB | 26 |
| 8 | AAA | 28 |
| 7 | AA | 28 |
| 6 | High-A | 28 |
| 5 | A | 28 |
| 4 | Scraps | Unlimited |
