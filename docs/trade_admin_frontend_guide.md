# Trade Management — Admin Frontend Guide

This document covers the admin endpoints and workflows the frontend admin panel needs to manage trades: reviewing proposals, approving or rejecting counterparty-accepted trades, executing direct admin trades, viewing rosters and payroll context, and rolling back trades.

All endpoints are under `/api/v1`. Trade endpoints are prefixed `/transactions/trade/`. Roster/payroll helpers are at `/transactions/roster/` and `/transactions/payroll-projection/`.

---

## Table of Contents

1. [Concepts](#concepts)
2. [Trade Proposal Lifecycle](#trade-proposal-lifecycle)
3. [Viewing Proposals](#viewing-proposals)
4. [Admin: Approve Trade](#admin-approve-trade)
5. [Admin: Reject Trade](#admin-reject-trade)
6. [Admin: Direct Trade Execution](#admin-direct-trade-execution)
7. [Roster & Payroll Context](#roster--payroll-context)
8. [Transaction Log & Rollback](#transaction-log--rollback)
9. [Admin UI Suggestion](#admin-ui-suggestion)
10. [Endpoint Reference](#endpoint-reference)
11. [Full Workflow: Trade Proposal Lifecycle](#full-workflow-trade-proposal-lifecycle)
12. [Error Messages Reference](#error-messages-reference)

---

## Concepts

### Two Ways to Trade

1. **Proposal workflow** — An org proposes a trade to another org. The counterparty accepts or rejects. If accepted, the trade goes to the admin queue for final approval. Admin can approve (executes immediately) or reject.
2. **Direct admin execution** — Admin builds and executes a trade instantly, bypassing the proposal/counterparty flow. Used for forced trades, corrections, or when both orgs agree out-of-band.

### What a Trade Contains

Every trade (proposal or direct) has this structure:

| Field | Type | Description |
|-------|------|-------------|
| `org_a_id` | int | First org (the proposing org in proposals) |
| `org_b_id` | int | Second org (the receiving org in proposals) |
| `players_to_b` | int[] | Player IDs moving from org A → org B |
| `players_to_a` | int[] | Player IDs moving from org B → org A |
| `salary_retention` | object | Per-player retention: `{ "player_id": { "retention_pct": 0.25 } }` |
| `cash_a_to_b` | float | Cash consideration (positive = A pays B, negative = B pays A) |

At least one player must be involved. Cash-only deals are not allowed.

### Salary Retention

When a player is traded, the old org can retain a percentage of the player's salary. This is tracked via the `contractTeamShare` table:

- Old org keeps `retention_pct` share (e.g., 0.25 = 25%)
- New org pays `1 - retention_pct` share (e.g., 0.75 = 75%)
- If no retention specified, the default is 0 (new org pays 100%)

Retention applies to all remaining contract years.

### What Happens on Execution

When a trade is executed (either via admin-approve or direct execute):

1. For each traded player, all future-year contract detail shares are updated:
   - Old org's `isHolder` set to 0, `salary_share` set to retention percentage
   - New share row created for receiving org with `isHolder = 1`
2. If cash is involved, ledger entries are created for both orgs
3. A transaction log entry is created with full rollback-capable details

**Note:** Salary cap and roster limit checks are NOT enforced at trade time. The system assumes pre-validation. The admin should check roster status before approving.

---

## Trade Proposal Lifecycle

```
Org A proposes trade
  ↓
Status: "proposed"
  ├─ Org A cancels → "cancelled" (terminal)
  └─ Org B acts:
      ├─ Org B rejects → "counterparty_rejected" (terminal)
      └─ Org B accepts → "counterparty_accepted"
          ├─ Org A cancels → "cancelled" (terminal)
          └─ Admin acts:
              ├─ Admin rejects → "admin_rejected" (terminal)
              └─ Admin approves → "executed" (trade happens, terminal)
```

### Status Values

| Status | Meaning | Admin Action Available |
|--------|---------|----------------------|
| `proposed` | Waiting for counterparty | None (only counterparty or proposer can act) |
| `counterparty_accepted` | **Awaiting admin review** | Approve or Reject |
| `counterparty_rejected` | Counterparty declined | None (terminal) |
| `admin_rejected` | Admin vetoed | None (terminal) |
| `executed` | Trade completed | Rollback via transaction log |
| `cancelled` | Proposer withdrew | None (terminal) |
| `expired` | Timed out (if implemented) | None (terminal) |

**The admin queue shows proposals with status `counterparty_accepted`.** This is the primary admin workflow.

---

## Viewing Proposals

### List All Proposals

```
GET /api/v1/transactions/trade/proposals
```

| Param | Required | Default | Notes |
|-------|----------|---------|-------|
| `org_id` | no | — | Filter to proposals involving this org (either side) |
| `status` | no | — | Filter by status value |

### Response (200)

```json
[
  {
    "id": 567,
    "proposing_org_id": 5,
    "receiving_org_id": 12,
    "league_year_id": 2,
    "status": "counterparty_accepted",
    "proposal": {
      "players_to_b": [101, 102],
      "players_to_a": [201],
      "salary_retention": {
        "101": { "retention_pct": 0.25 }
      },
      "cash_a_to_b": 50000
    },
    "proposed_at": "2026-04-12T10:30:00",
    "counterparty_acted_at": "2026-04-12T14:45:00",
    "admin_acted_at": null,
    "executed_at": null,
    "counterparty_note": "Looks good, let's do it",
    "admin_note": null
  }
]
```

Sorted by `proposed_at` DESC (newest first).

### Proposal Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Unique proposal ID |
| `proposing_org_id` | int | Org that initiated the trade |
| `receiving_org_id` | int | Org that received the proposal |
| `league_year_id` | int | League year context |
| `status` | string | Current status (see table above) |
| `proposal` | object | Trade details (players, retention, cash) |
| `proposed_at` | ISO datetime | When the proposal was created |
| `counterparty_acted_at` | ISO datetime or null | When the receiving org accepted/rejected |
| `admin_acted_at` | ISO datetime or null | When admin approved/rejected |
| `executed_at` | ISO datetime or null | When trade was executed |
| `counterparty_note` | string or null | Note from the receiving org (max 500 chars) |
| `admin_note` | string or null | Note from admin (max 500 chars) |

### Get Single Proposal

```
GET /api/v1/transactions/trade/proposals/567
```

Returns a single proposal object (same shape). Returns `404` if not found.

### Filtering for the Admin Queue

To show proposals awaiting admin action:

```
GET /api/v1/transactions/trade/proposals?status=counterparty_accepted
```

This is the primary view for the admin trade panel — these are trades where both orgs have agreed and the admin needs to approve or reject.

---

## Admin: Approve Trade

Approves a counterparty-accepted proposal and executes the trade immediately.

```
PUT /api/v1/transactions/trade/proposals/567/admin-approve
```

```json
{
  "league_year_id": 2,
  "game_week_id": 45,
  "note": "Approved - fair value exchange",
  "executed_by": "admin"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `league_year_id` | yes | Current league year ID |
| `game_week_id` | yes | Current game week ID (for ledger entries) |
| `note` | no | Admin note (max 500 chars, stored in `admin_note`) |
| `executed_by` | no | Who approved (stored in transaction log) |

### Response (200)

```json
{
  "proposal_id": 567,
  "status": "executed",
  "trade_result": {
    "transaction_id": 1234,
    "org_a_id": 5,
    "org_b_id": 12,
    "players_to_b": [101, 102],
    "players_to_a": [201],
    "cash_a_to_b": 50000.0
  }
}
```

### What Happens

1. Proposal status changes from `counterparty_accepted` → `executed`
2. `admin_acted_at` and `executed_at` timestamps set
3. `execute_trade()` runs internally:
   - Contract share mutations for all traded players
   - Cash ledger entries created (if cash involved)
   - Transaction log entry created with full rollback details
4. Admin note stored

### Error Responses

```json
{ "error": "validation", "message": "Proposal is not in 'counterparty_accepted' status" }
```

Can only approve proposals with status `counterparty_accepted`.

---

## Admin: Reject Trade

Rejects a counterparty-accepted proposal without executing.

```
PUT /api/v1/transactions/trade/proposals/567/admin-reject
```

```json
{
  "note": "Rejected - lopsided value, would damage competitive balance"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `note` | no | Rejection reason (max 500 chars, stored in `admin_note`) |

### Response (200)

Returns the updated proposal object with:
- `status`: `"admin_rejected"`
- `admin_acted_at`: current timestamp
- `admin_note`: the provided note

### Error Responses

```json
{ "error": "validation", "message": "Proposal is not in 'counterparty_accepted' status" }
```

---

## Admin: Direct Trade Execution

Bypasses the proposal workflow entirely. The admin builds the trade and executes it immediately.

```
POST /api/v1/transactions/trade/execute
```

```json
{
  "org_a_id": 5,
  "org_b_id": 12,
  "league_year_id": 2,
  "game_week_id": 45,
  "players_to_b": [101, 102],
  "players_to_a": [201],
  "salary_retention": {
    "101": { "retention_pct": 0.25 }
  },
  "cash_a_to_b": 50000,
  "executed_by": "admin"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `org_a_id` | yes | First org |
| `org_b_id` | yes | Second org (must differ from org_a_id) |
| `league_year_id` | yes | Current league year |
| `game_week_id` | yes | Current game week |
| `players_to_b` | no | Player IDs moving A → B (array of ints) |
| `players_to_a` | no | Player IDs moving B → A (array of ints) |
| `salary_retention` | no | Per-player retention (keyed by player_id as string) |
| `cash_a_to_b` | no | Cash amount (positive = A pays B) |
| `executed_by` | no | Who executed (stored in transaction log) |

At least one of `players_to_b` or `players_to_a` must be non-empty.

### Response (200)

```json
{
  "transaction_id": 1234,
  "org_a_id": 5,
  "org_b_id": 12,
  "players_to_b": [101, 102],
  "players_to_a": [201],
  "cash_a_to_b": 50000.0
}
```

### Error Responses

```json
{ "error": "missing_fields", "fields": ["org_a_id", "org_b_id"] }
```

```json
{ "error": "validation", "message": "Player 101 does not have an active contract" }
```

---

## Roster & Payroll Context

Before approving or building a trade, the admin needs to see what each org has.

### Load Org Roster

```
GET /api/v1/transactions/roster/5
```

### Response (200)

```json
[
  {
    "contract_id": 890,
    "player_id": 101,
    "player_name": "Marcus Johnson",
    "position": "P",
    "current_level": 9,
    "onIR": 0,
    "salary": 5500000.0
  },
  {
    "contract_id": 891,
    "player_id": 102,
    "player_name": "Tyler Brooks",
    "position": "IF",
    "current_level": 9,
    "onIR": 0,
    "salary": 750000.0
  }
]
```

Sorted by `current_level` DESC (MLB first), then last name.

| Field | Type | Description |
|-------|------|-------------|
| `contract_id` | int | Active contract ID |
| `player_id` | int | Player ID |
| `player_name` | string | "Firstname Lastname" |
| `position` | string | Player type: `"P"`, `"IF"`, `"OF"`, `"C"` |
| `current_level` | int | Current assignment level (9=MLB, 8=AAA, etc.) |
| `onIR` | int | 1 if on injured reserve, 0 if active |
| `salary` | float | Year-1 salary (for display context) |

### Load Roster Status (Limits)

Check if an org's rosters are over/under limits before approving a trade.

```
GET /api/v1/transactions/roster-status/5
```

### Response (200)

```json
[
  {
    "level_id": 1,
    "level_name": 9,
    "count": 38,
    "min_roster": 25,
    "max_roster": 40,
    "over_limit": false,
    "under_limit": false
  },
  {
    "level_id": 2,
    "level_name": 8,
    "count": 28,
    "min_roster": 25,
    "max_roster": 35,
    "over_limit": false,
    "under_limit": false
  }
]
```

**UI tip:** Before approving a trade, load roster status for both orgs. If adding players would push a level over `max_roster`, display a warning (the API will still allow the trade, but the admin should know).

### Load Payroll Projection

Multi-year salary outlook for an org.

```
GET /api/v1/transactions/payroll-projection/5
```

Use this alongside the trade review to show how a trade affects each org's salary commitments.

---

## Transaction Log & Rollback

### View Transaction Log

```
GET /api/v1/transactions/log
```

| Param | Required | Default | Notes |
|-------|----------|---------|-------|
| `org_id` | no | — | Filter by org |
| `type` | no | — | Filter by type (e.g., `"trade"`) |

Returns chronological list of all transactions including trades. Each entry includes a `details` JSON blob with the full trade structure and share mutations.

### Rollback a Trade

Reverses all contract share mutations and deletes cash ledger entries.

```
POST /api/v1/transactions/rollback
```

```json
{ "transaction_id": 1234 }
```

### Response (200)

```json
{
  "status": "rolled_back",
  "transaction_id": 1234
}
```

### What Happens on Rollback

1. All `contractTeamShare` rows created by the trade are deleted
2. Original share rows restored: `isHolder` and `salary_share` set back to pre-trade values
3. Cash ledger entries deleted
4. Transaction log entry updated with rollback note

**Protection:** Cannot rollback the same transaction twice. The system checks for a "ROLLBACK of transaction {id}" note before proceeding.

**Warning:** Rollback does not revert the proposal status. If a trade was executed via admin-approve, the proposal stays as `"executed"` even after rollback. The rollback only undoes the contract/financial changes.

---

## Admin UI Suggestion

Add a "Trade Management" section to the admin panel:

```
┌──────────────────────────────────────────────────────────────────────┐
│  Trade Management                                                     │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  Pending Approval (3)                                          │   │
│  │                                                                │   │
│  │  #567  NYY → BOS    2 players ↔ 1 player + $50K               │   │
│  │        Proposed: Apr 12  ·  Accepted: Apr 12                   │   │
│  │        Note: "Looks good, let's do it"                         │   │
│  │        [View Details]  [✓ Approve]  [✗ Reject]                 │   │
│  │                                                                │   │
│  │  #571  LAD → CHC    1 player ↔ 2 players                      │   │
│  │        Proposed: Apr 11  ·  Accepted: Apr 12                   │   │
│  │        [View Details]  [✓ Approve]  [✗ Reject]                 │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ─── Filter ───                                                       │
│  Status: [All ▾]  Org: [All ▾]                                        │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  All Proposals                                                 │   │
│  │                                                                │   │
│  │  ID   From   To    Status              Date       Actions      │   │
│  │  571  LAD    CHC   ● Awaiting Admin    Apr 11     [Details]    │   │
│  │  567  NYY    BOS   ● Awaiting Admin    Apr 12     [Details]    │   │
│  │  563  ATL    MIA   ● Executed          Apr 10     [Details]    │   │
│  │  558  SEA    TEX   ○ Rejected (Admin)  Apr 9      [Details]    │   │
│  │  552  PHI    STL   ○ Rejected (CP)     Apr 8      [Details]    │   │
│  │  549  HOU    MIN   ○ Cancelled         Apr 7      [Details]    │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ─── Direct Trade Builder ───                                         │
│  Org A: [Select ▾]          Org B: [Select ▾]                         │
│  ┌──────────────────┐       ┌──────────────────┐                      │
│  │  □ M.Johnson (P) │       │  □ T.Brooks (IF) │                      │
│  │    Lv9  $5.5M    │       │    Lv9  $750K    │                      │
│  │  □ R.Garcia (OF) │       │  □ J.Kim (P)     │                      │
│  │    Lv9  $3.2M    │       │    Lv8  $500K    │                      │
│  └──────────────────┘       └──────────────────┘                      │
│                                                                       │
│  Cash: [$ 0       ]  (positive = A pays B)                            │
│  Salary Retention: [Configure ▾]                                      │
│                                                                       │
│  [Execute Trade]                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Trade Detail Modal

When "View Details" is clicked on a proposal:

```
┌──────────────────────────────────────────────────────────────┐
│  Trade #567                                    Status: ● Awaiting Admin │
│                                                               │
│  NYY sends to BOS:                  BOS sends to NYY:         │
│  ┌───────────────────────┐          ┌───────────────────────┐ │
│  │ Marcus Johnson (P)    │          │ Tyler Brooks (IF)     │ │
│  │ Level 9 · $5.5M/yr   │          │ Level 9 · $750K/yr    │ │
│  │ Retention: 25%        │          │ Retention: none       │ │
│  │                       │          │                       │ │
│  │ Ryan Garcia (OF)      │          │                       │ │
│  │ Level 9 · $3.2M/yr   │          │                       │ │
│  │ Retention: none       │          │                       │ │
│  └───────────────────────┘          └───────────────────────┘ │
│                                                               │
│  Cash: NYY pays BOS $50,000                                   │
│                                                               │
│  ─── Roster Impact ───                                        │
│  NYY: 38 → 37 (Lv9)    within limits (25-40)                 │
│  BOS: 36 → 37 (Lv9)    within limits (25-40)                 │
│                                                               │
│  ─── Timeline ───                                             │
│  Proposed: Apr 12, 10:30 AM                                   │
│  Accepted: Apr 12, 2:45 PM                                    │
│  Counterparty note: "Looks good, let's do it"                 │
│                                                               │
│  Admin note: [_________________________]                      │
│                                                               │
│  [✓ Approve Trade]         [✗ Reject Trade]                   │
└──────────────────────────────────────────────────────────────┘
```

### Status Badge Colors

| Status | Color | Label |
|--------|-------|-------|
| `proposed` | Gray | Proposed |
| `counterparty_accepted` | Orange | Awaiting Admin |
| `counterparty_rejected` | Red | Rejected (CP) |
| `admin_rejected` | Red | Rejected (Admin) |
| `executed` | Green | Executed |
| `cancelled` | Gray | Cancelled |
| `expired` | Gray | Expired |

### Loading Data for Trade Detail

When opening a proposal detail, load in parallel:

1. `GET /transactions/trade/proposals/{id}` — the proposal itself
2. `GET /transactions/roster/{org_a_id}` — proposing org's full roster
3. `GET /transactions/roster/{org_b_id}` — receiving org's full roster
4. `GET /transactions/roster-status/{org_a_id}` — proposing org's roster limits
5. `GET /transactions/roster-status/{org_b_id}` — receiving org's roster limits

Cross-reference `proposal.players_to_b` and `proposal.players_to_a` against the roster data to display player names, positions, levels, and salaries. Compute roster impact (current count ± players in/out) against limits to show warnings.

### Confirmation Dialogs

**Approve:** "Approve trade #567? This will immediately execute the trade — players and salary obligations will be transferred."

**Reject:** "Reject trade #567? Both orgs will be notified. This cannot be undone." Include the admin note input in the dialog.

**Direct Execute:** "Execute this trade? Players will be transferred immediately. This bypasses the proposal workflow."

---

## Endpoint Reference

### Proposal Workflow

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| POST | `/transactions/trade/propose` | Org | Create a trade proposal |
| GET | `/transactions/trade/proposals` | Any | List proposals (filterable) |
| GET | `/transactions/trade/proposals/{id}` | Any | Single proposal detail |
| PUT | `/transactions/trade/proposals/{id}/accept` | Receiving org | Counterparty accepts |
| PUT | `/transactions/trade/proposals/{id}/reject` | Receiving org | Counterparty rejects |
| PUT | `/transactions/trade/proposals/{id}/cancel` | Proposing org | Cancel proposal |
| PUT | `/transactions/trade/proposals/{id}/admin-approve` | **Admin** | Approve and execute |
| PUT | `/transactions/trade/proposals/{id}/admin-reject` | **Admin** | Reject without executing |

### Direct Execution

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| POST | `/transactions/trade/execute` | **Admin** | Build and execute trade directly |

### Context & Support

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/transactions/roster/{org_id}` | Any | Org's active roster with contracts |
| GET | `/transactions/roster-status/{org_id}` | Any | Roster counts vs limits per level |
| GET | `/transactions/payroll-projection/{org_id}` | Any | Multi-year salary projection |
| GET | `/transactions/log` | Any | Transaction history |
| POST | `/transactions/rollback` | **Admin** | Reverse a completed trade |

All POST/PUT endpoints return `400` with `{"error": "..."}` on validation failure.

---

## Full Workflow: Trade Proposal Lifecycle

### 1. Org A Proposes a Trade

User frontend calls `POST /transactions/trade/propose`:
- Selects players from both rosters
- Optionally configures salary retention per player
- Optionally adds cash consideration
- Proposal created with status `"proposed"`

### 2. Org B Reviews and Responds

User frontend shows incoming proposals. Org B can:
- **Accept** (`PUT .../accept`) → status becomes `"counterparty_accepted"`, moves to admin queue
- **Reject** (`PUT .../reject`) → status becomes `"counterparty_rejected"`, trade dies
- Both can include a note (max 500 chars)

### 3. Admin Reviews the Queue

Admin panel loads `GET /transactions/trade/proposals?status=counterparty_accepted`.

For each pending trade, admin should:
1. Review the players and salary implications
2. Check roster status for both orgs (are they over/under limits?)
3. Check payroll projections (does the salary work long-term?)
4. Decide: approve or reject

### 4a. Admin Approves

`PUT .../admin-approve` with `league_year_id` and `game_week_id`:
- Trade executes immediately
- Contract shares transfer
- Cash ledger entries created
- Status becomes `"executed"`
- Transaction log entry created

### 4b. Admin Rejects

`PUT .../admin-reject` with optional note:
- No trade execution
- Status becomes `"admin_rejected"`
- Both orgs can see the rejection and admin note

### 5. Post-Trade (If Needed)

If a trade needs to be undone:
- Find the `transaction_id` from the trade result or transaction log
- Call `POST /transactions/rollback` with the transaction_id
- All contract changes are reversed, cash ledger entries deleted

### At Any Point: Cancellation

The proposing org can cancel with `PUT .../cancel` as long as the status is `"proposed"` or `"counterparty_accepted"`. Once the admin has acted (approved or rejected), cancellation is no longer possible.

---

## Error Messages Reference

| Error | Cause | Resolution |
|-------|-------|------------|
| `"missing_fields"` with `fields` array | Required fields not provided | Include all required fields |
| `"Player {id} does not have an active contract"` | Player's contract is finished or doesn't exist | Verify player has an active contract |
| `"Proposal is not in 'counterparty_accepted' status"` | Tried to approve/reject a proposal not in the right state | Check proposal status first |
| `"Proposal not found"` (404) | Invalid proposal ID | Verify the ID |
| `"Invalid salary retention percentage"` | Retention not between 0.0 and 1.0 | Use decimal 0.00-1.00 |
| `"db_error"` | Database connection or query failure | Retry or check server logs |
