# Financial Data Endpoints — Frontend Guide

All endpoints are served under `/api/v1`. Responses are JSON. All `GET` requests use query parameters; `POST` requests use JSON bodies.

---

## 1. Org Financial Summary

**`GET /api/v1/orgs/{org_abbrev}/financial_summary?league_year={year}`**

Full P&L breakdown for a single organization in a given season. This is the primary endpoint for building an org finances page.

### Parameters

| Param | Location | Type | Required | Example |
|-------|----------|------|----------|---------|
| `org_abbrev` | URL path | string | yes | `NYY` |
| `league_year` | query string | int | yes | `2026` |

### Response Shape

```json
{
  "org": {
    "id": 5,
    "abbrev": "NYY"
  },
  "league_year": 2026,
  "starting_balance": 12500000.00,
  "season_revenue": 85000000.00,
  "season_expenses": 72000000.00,
  "year_start_events": {
    "media": 30000000.00,
    "bonus": -5000000.00,
    "buyout": -1000000.00
  },
  "weeks": [
    {
      "week_index": 1,
      "salary_out": 2800000.00,
      "performance_in": 1500000.00,
      "other_in": 0.0,
      "other_out": 0.0,
      "net": -1300000.00,
      "cumulative_balance": 35200000.00,
      "by_type": {
        "salary": -2800000.00,
        "performance": 1500000.00
      }
    }
  ],
  "interest_events": {
    "interest_income": 625000.00
  },
  "ending_balance_before_interest": 12500000.00,
  "ending_balance": 13125000.00
}
```

### Field Reference

| Field | Description |
|-------|-------------|
| `starting_balance` | Net ledger balance from all prior league years (cumulative all-time) |
| `season_revenue` | Sum of all positive ledger entries this year (media + performance + interest income + playoff) |
| `season_expenses` | Sum of absolute values of all negative entries (salary + bonus + buyout + interest expense) |
| `year_start_events` | One-time entries at season start — `media` (positive), `bonus` (negative), `buyout` (negative). Keys only appear if values exist. |
| `weeks[]` | One entry per game week (1 through `weeks_in_season`). Empty weeks still appear with zeroes. |
| `weeks[].salary_out` | Presented as a **positive number** (the ledger stores it negative; this is flipped for display convenience) |
| `weeks[].performance_in` | Revenue earned that week based on rolling 3-year win history |
| `weeks[].by_type` | Raw ledger signs — salary is negative, performance is positive |
| `interest_events` | End-of-year interest. Either `interest_income` (positive balance) or `interest_expense` (negative balance), never both. |
| `ending_balance` | Final balance after all activity including interest |

### Errors

| Status | `error` | When |
|--------|---------|------|
| 400 | `missing_param` | `league_year` query param not provided |
| 404 | `not_found` | Org abbreviation or league year doesn't exist |
| 500 | `database_error` | Internal DB failure |

---

## 2. League-Wide Financial Summary

**`GET /api/v1/financial_summary?league_year={year}`**

Aggregated financial summary for every organization in the league. Calls the org summary internally for each org.

### Parameters

| Param | Location | Type | Required | Example |
|-------|----------|------|----------|---------|
| `league_year` | query string | int | yes | `2026` |

### Response Shape

```json
{
  "league_year": 2026,
  "league_totals": {
    "season_revenue": 2550000000.00,
    "season_expenses": 2160000000.00
  },
  "orgs": {
    "NYY": { /* same shape as org financial_summary response */ },
    "LAD": { /* ... */ },
    "BOS": { /* ... */ }
  }
}
```

### Notes

- `orgs` is keyed by `org_abbrev` strings, sorted alphabetically.
- Each value under `orgs` has the exact same shape as the single-org endpoint response.
- `league_totals` only includes `season_revenue` and `season_expenses` (rolled up across all orgs).
- This endpoint is heavier than the single-org version — it queries every org. Cache or debounce on the frontend if used for dashboards.

### Errors

Same as single-org endpoint (400, 404, 500).

---

## 3. Raw Ledger Entries

**`GET /api/v1/orgs/{org_abbrev}/ledger?league_year={year}`**

Returns every individual ledger entry row for an org in a given year. Use this when you need to display a transaction-level table or drill into specific entries.

### Parameters

| Param | Location | Type | Required | Example |
|-------|----------|------|----------|---------|
| `org_abbrev` | URL path | string | yes | `NYY` |
| `league_year` | query string | int | yes | `2026` |
| `entry_type` | query string | string | no | `salary`, `media`, `performance`, `bonus`, `buyout`, `interest_income`, `interest_expense`, `playoff_gate`, `playoff_media` |

### Response Shape

```json
{
  "org": {
    "id": 5,
    "abbrev": "NYY"
  },
  "league_year": 2026,
  "count": 142,
  "entries": [
    {
      "id": 10234,
      "org_id": 5,
      "league_year_id": 3,
      "game_week_id": 15,
      "entry_type": "salary",
      "amount": -2800000.00,
      "created_at": "2026-04-10T12:00:00",
      "week_index": 1
    }
  ]
}
```

### Field Reference

| Field | Description |
|-------|-------------|
| `count` | Total number of entries returned |
| `entries[].entry_type` | One of: `media`, `bonus`, `buyout`, `salary`, `performance`, `interest_income`, `interest_expense`, `playoff_gate`, `playoff_media` |
| `entries[].amount` | Signed value — positive = income, negative = expense |
| `entries[].game_week_id` | FK to game_weeks. `null` for year-level entries (media, bonus, buyout, interest) |
| `entries[].week_index` | Resolved week number (1-based). `null` for year-level entries. |

### Ordering

Entries are sorted by `week_index ASC` (nulls first — year-level entries appear at the top), then by `id ASC`.

### Filtering

Pass `entry_type` to filter to a single type. Examples:

```
GET /api/v1/orgs/NYY/ledger?league_year=2026&entry_type=salary
GET /api/v1/orgs/NYY/ledger?league_year=2026&entry_type=media
```

Only one `entry_type` value is supported per request (not comma-separated).

### Errors

| Status | `error` | When |
|--------|---------|------|
| 400 | `missing_param` | `league_year` not provided |
| 404 | `org_not_found` | Org abbreviation doesn't exist |
| 404 | `league_year_not_found` | League year doesn't exist |
| 500 | `database_error` | Internal DB failure |

---

## 4. Contract Status (Single Player)

**`GET /api/v1/transactions/contract-status/{player_id}`**

Enriched contract and service-time info for one player. Use this for player detail views.

### Parameters

| Param | Location | Type | Required |
|-------|----------|------|----------|
| `player_id` | URL path | int | yes |

### Response Shape

```json
{
  "player_id": 1234,
  "player_name": "Aaron Judge",
  "age": 34,
  "contract_id": 567,
  "current_level": 9,
  "years": 5,
  "current_year": 3,
  "years_remaining": 2,
  "salary": 36000000.00,
  "is_extension": false,
  "on_ir": false,
  "mlb_service_years": 8,
  "contract_phase": "fa_eligible",
  "years_to_arb": null,
  "years_to_fa": null,
  "is_expiring": false,
  "has_extension": false
}
```

### Field Reference

| Field | Description |
|-------|-------------|
| `current_level` | Team level (9 = MLB, 5-8 = MiLB, etc.) |
| `years` | Total contract length |
| `current_year` | Which year of the contract the player is in (1-based) |
| `years_remaining` | `years - current_year` |
| `salary` | Current year's salary |
| `contract_phase` | One of: `minor`, `pre_arb`, `arb_eligible`, `fa_eligible` |
| `years_to_arb` | Seasons until arbitration eligibility. `null` if already arb/FA eligible. |
| `years_to_fa` | Seasons until free agency. `null` if already FA eligible. |
| `is_expiring` | `true` if `current_year == years` (final year of deal) |
| `has_extension` | `true` if an extension contract exists queued up for when this one ends |

### Errors

| Status | `error` | When |
|--------|---------|------|
| 404 | `not_found` | No active contract for this player |
| 500 | `db_error` | Internal DB failure |

---

## 5. Contract Overview (Org Roster)

**`GET /api/v1/transactions/contract-overview/{org_id}?league_year_id={id}`**

Contract status for every active player held by an organization. This is the main endpoint for a team's contract/roster management page.

### Parameters

| Param | Location | Type | Required | Notes |
|-------|----------|------|----------|-------|
| `org_id` | URL path | int | yes | Organization ID (not abbreviation) |
| `league_year_id` | query string | int | no | If provided, includes cached demand summaries for expiring contracts |

### Response Shape

Returns an array (not wrapped in an object):

```json
[
  {
    "player_id": 1234,
    "player_name": "Aaron Judge",
    "age": 34,
    "position": "OF",
    "contract_id": 567,
    "current_level": 9,
    "years": 5,
    "current_year": 3,
    "years_remaining": 2,
    "salary": 36000000.00,
    "on_ir": false,
    "mlb_service_years": 8,
    "contract_phase": "fa_eligible",
    "years_to_arb": null,
    "years_to_fa": null,
    "is_expiring": false,
    "demand": null
  },
  {
    "player_id": 5678,
    "player_name": "Clarke Schmidt",
    "age": 28,
    "position": "P",
    "contract_id": 890,
    "current_level": 9,
    "years": 3,
    "current_year": 3,
    "years_remaining": 0,
    "salary": 8000000.00,
    "on_ir": false,
    "mlb_service_years": 5,
    "contract_phase": "arb_eligible",
    "years_to_arb": null,
    "years_to_fa": 1,
    "is_expiring": true,
    "demand": {
      "type": "extension",
      "min_aav": 12000000,
      "min_years": 3,
      "war": 4.2
    }
  }
]
```

### Notes on `demand`

- `demand` is `null` for most players.
- Only populated when `league_year_id` is provided AND cached demands exist in the `player_demands` table.
- For expiring arb/FA-eligible players: `demand.type = "extension"` with `min_aav`, `min_years`, `war`.
- Buyout demands may also appear with `demand.type = "buyout"`.
- These are **cached** values — fresh demands are computed on-demand when opening a specific player's contract detail.

### Sort Order

Results are sorted by `current_level` descending (MLB first), then `lastname`, then `firstname`.

### Errors

| Status | `error` | When |
|--------|---------|------|
| 500 | `db_error` | Internal DB failure |

---

## 6. Payroll Projection (Multi-Year)

**`GET /api/v1/transactions/payroll-projection/{org_id}`**

Multi-year salary projection showing every committed dollar, including dead money from trades.

### Parameters

| Param | Location | Type | Required |
|-------|----------|------|----------|
| `org_id` | URL path | int | yes |

### Response Shape

```json
{
  "org_id": 5,
  "current_league_year": 2026,
  "players": [
    {
      "player_id": 1234,
      "player_name": "Aaron Judge",
      "position": "OF",
      "age": 34,
      "contract_id": 567,
      "is_extension": false,
      "is_buyout": false,
      "contract_phase": "fa_eligible",
      "mlb_service_years": 8,
      "current_level": 9,
      "bonus": 10000000.00,
      "salary_schedule": [
        {
          "league_year": 2026,
          "contract_year": 3,
          "gross_salary": 36000000.00,
          "team_share": 1.0,
          "team_owes": 36000000.00,
          "is_current": true
        },
        {
          "league_year": 2027,
          "contract_year": 4,
          "gross_salary": 38000000.00,
          "team_share": 1.0,
          "team_owes": 38000000.00,
          "is_current": false
        }
      ]
    }
  ],
  "year_totals": {
    "2026": { "total_salary": 195000000.00, "player_count": 40 },
    "2027": { "total_salary": 165000000.00, "player_count": 35 },
    "2028": { "total_salary": 120000000.00, "player_count": 22 }
  },
  "dead_money": [
    {
      "player_id": 9999,
      "player_name": "Former Player",
      "contract_id": 333,
      "remaining": [
        { "league_year": 2026, "team_owes": 5000000.00 },
        { "league_year": 2027, "team_owes": 5000000.00 }
      ]
    }
  ]
}
```

### Field Reference

| Field | Description |
|-------|-------------|
| `players[]` | Active held contracts — players on this org's roster |
| `players[].salary_schedule[]` | One entry per remaining contract year. Only future/current years included. |
| `players[].salary_schedule[].team_share` | Fraction of salary this org pays (1.0 = full, < 1.0 = trade split) |
| `players[].salary_schedule[].team_owes` | `gross_salary * team_share`, rounded to 2 decimals |
| `players[].salary_schedule[].is_current` | `true` for the current contract year |
| `players[].bonus` | Signing bonus amount (already paid, shown for reference) |
| `year_totals` | Keyed by league year (as string). Includes both held + dead money obligations. |
| `year_totals[year].player_count` | Distinct players contributing to that year's total |
| `dead_money[]` | Retained salary from traded players — org no longer holds them but still owes salary |

### Errors

| Status | `error` | When |
|--------|---------|------|
| 500 | `db_error` | Internal DB failure |

---

## 7. Signing Budget

**`GET /api/v1/transactions/signing-budget/{org_id}?league_year_id={id}`**

Returns the available budget an org has for signing free agents.

### Parameters

| Param | Location | Type | Required |
|-------|----------|------|----------|
| `org_id` | URL path | int | yes |
| `league_year_id` | query string | int | yes |

### Response Shape

```json
{
  "org_id": 5,
  "available_budget": 45000000.00
}
```

### Errors

| Status | `error` | When |
|--------|---------|------|
| 400 | `missing_fields` | `league_year_id` not provided |
| 500 | `db_error` | Internal DB failure |

---

## Entry Type Reference

These are the possible values for `entry_type` across the ledger system:

| Entry Type | Category | Sign | When Generated |
|------------|----------|------|----------------|
| `media` | Revenue | + | Year start (annual media payout) |
| `bonus` | Expense | - | Year start (signing bonuses for contracts signed that year) |
| `buyout` | Expense | - | Year start (contract buyouts) |
| `salary` | Expense | - | Weekly (pro-rated: `salary * share / weeks_in_season`) |
| `performance` | Revenue | + | Weekly (based on rolling 3-year win history, 65% home / 35% away) |
| `interest_income` | Revenue | + | Year end (5% on positive net balance) |
| `interest_expense` | Expense | - | Year end (5% on negative net balance) |
| `playoff_gate` | Revenue | + | Post-season (home playoff games × gate multiplier) |
| `playoff_media` | Revenue | + | Post-season (flat payout per series appearance) |

---

## Common Patterns

### Building an org finances page

1. Fetch `GET /api/v1/orgs/{abbrev}/financial_summary?league_year=2026` for the P&L overview.
2. Use `weeks[]` array for a chart of cumulative balance over the season.
3. Use `year_start_events` and `interest_events` for the summary cards.

### Building a transaction log / ledger view

1. Fetch `GET /api/v1/orgs/{abbrev}/ledger?league_year=2026` for all entries.
2. Filter client-side or pass `entry_type` to narrow server-side.
3. Year-level entries (`week_index: null`) appear first — these are media, bonus, buyout, and interest.

### Building a payroll / contracts page

1. Fetch `GET /api/v1/transactions/contract-overview/{org_id}?league_year_id=X` for the roster table.
2. Fetch `GET /api/v1/transactions/payroll-projection/{org_id}` for the multi-year salary chart.
3. Use `dead_money[]` to show retained salary obligations separately.
4. Fetch `GET /api/v1/transactions/signing-budget/{org_id}?league_year_id=X` to show available cap space.

### Viewing a single player's contract

1. Fetch `GET /api/v1/transactions/contract-status/{player_id}` for the detail card.
2. Key fields: `contract_phase`, `is_expiring`, `has_extension`, `years_to_arb`, `years_to_fa`.

### League-wide financial dashboard

1. Fetch `GET /api/v1/financial_summary?league_year=2026`.
2. `league_totals` gives top-line revenue/expenses.
3. Iterate `orgs` for per-team comparison charts.
4. Note: this is a heavy call — it queries every org. Cache or debounce.
