# Frontend Guide: Service Time, Contract Phases & End-of-Season

## Overview

Two new API endpoints expose service time and contract phase data for every player. A third endpoint runs end-of-season batch processing (admin only). This data lets the frontend show users where each player sits on the minor league → pre-arb → arbitration → free agency timeline.

---

## New Endpoints

### 1. `GET /api/v1/transactions/contract-status/{player_id}`

Single-player view. Returns enriched contract info including service time.

**Response:**
```json
{
  "player_id": 123,
  "player_name": "John Smith",
  "age": 25,
  "contract_id": 456,
  "current_level": 9,
  "years": 3,
  "current_year": 2,
  "years_remaining": 1,
  "salary": 800000.00,
  "is_extension": false,
  "on_ir": false,
  "mlb_service_years": 2,
  "contract_phase": "pre_arb",
  "years_to_arb": 1,
  "years_to_fa": 4,
  "is_expiring": false,
  "has_extension": false
}
```

Returns `404` if the player has no active held contract (i.e., they're a free agent or don't exist).

### 2. `GET /api/v1/transactions/contract-overview/{org_id}`

Org-wide view. Returns the same data for every active player held by the org. Sorted by level (desc) then last name.

**Response:**
```json
[
  {
    "player_id": 123,
    "player_name": "John Smith",
    "age": 25,
    "position": "Pitcher",
    "contract_id": 456,
    "current_level": 9,
    "years": 3,
    "current_year": 2,
    "years_remaining": 1,
    "salary": 800000.00,
    "on_ir": false,
    "mlb_service_years": 2,
    "contract_phase": "pre_arb",
    "years_to_arb": 1,
    "years_to_fa": 4,
    "is_expiring": false
  }
]
```

### 3. `POST /api/v1/transactions/end-of-season` (Admin)

Runs the full end-of-season batch. **Body:** `{ "league_year_id": 1 }`

**Response:**
```json
{
  "league_year": 2026,
  "service_time_credited": 45,
  "contracts_advanced": 320,
  "contracts_expired": 180,
  "auto_renewed_minor": 150,
  "auto_renewed_pre_arb": 12,
  "became_free_agents": 18,
  "extensions_activated": 5
}
```

---

## Contract Phase System

Every player with an active contract falls into one of four phases:

| Phase | Criteria | What Happens at EOS | Badge Color |
|-------|----------|---------------------|-------------|
| `minor` | Level < 9 (any minor league) | Auto-renews at $40K/yr | Green |
| `pre_arb` | Level 9 (MLB) + < 3 service years | Auto-renews at $800K/yr | Blue |
| `arb_eligible` | Level 9 + 3-5 service years | Becomes free agent* | Orange |
| `fa_eligible` | 6+ service years | Becomes free agent | Red |

*Arbitration salary logic is stubbed for now. Arb-eligible players become free agents at EOS until the arbitration hearing system is built.

### Service Time Rules

- **Accrual:** Players at MLB level (9) with an active contract at end-of-season receive +1 service year.
- **Minor league players do not accrue service time.**
- **Thresholds:** 3 years → arbitration eligible. 6 years → free agent eligible.

---

## Key Fields Explained

| Field | Type | Description |
|-------|------|-------------|
| `mlb_service_years` | int | Total MLB seasons completed |
| `contract_phase` | string | One of: `minor`, `pre_arb`, `arb_eligible`, `fa_eligible` |
| `years_to_arb` | int or null | Seasons until arbitration. `null` if already arb/FA eligible |
| `years_to_fa` | int or null | Seasons until free agency. `null` if already FA eligible |
| `is_expiring` | bool | True if `current_year == years` (final year of deal) |
| `has_extension` | bool | True if an extension contract exists for after this one ends |
| `years_remaining` | int | `years - current_year` (0 = final year) |

---

## Frontend Integration Patterns

### Player Card / Profile

Show the service time timeline on the player detail page:

```javascript
fetch(`/api/v1/transactions/contract-status/${playerId}`)
  .then(r => r.json())
  .then(status => {
    // Display phase badge
    const phaseLabels = {
      minor: 'Minor League',
      pre_arb: 'Pre-Arbitration',
      arb_eligible: 'Arbitration Eligible',
      fa_eligible: 'Free Agent Eligible'
    };

    // Build timeline info
    let timeline = `${status.mlb_service_years} MLB service year(s)`;
    if (status.years_to_arb !== null) {
      timeline += ` · ${status.years_to_arb} year(s) to arbitration`;
    }
    if (status.years_to_fa !== null) {
      timeline += ` · ${status.years_to_fa} year(s) to free agency`;
    }

    // Contract status
    let contractInfo = `Year ${status.current_year} of ${status.years}`;
    if (status.is_expiring) contractInfo += ' (EXPIRING)';
    if (status.has_extension) contractInfo += ' (Extension signed)';
  });
```

### Org Financial Dashboard

Use `contract-overview` to show the full roster with phase info:

```javascript
fetch(`/api/v1/transactions/contract-overview/${orgId}`)
  .then(r => r.json())
  .then(players => {
    // Group by phase for summary counts
    const phaseCounts = { minor: 0, pre_arb: 0, arb_eligible: 0, fa_eligible: 0 };
    let expiringCount = 0;

    players.forEach(p => {
      phaseCounts[p.contract_phase]++;
      if (p.is_expiring) expiringCount++;
    });

    // Show: "12 Minor | 8 Pre-Arb | 3 Arb | 2 FA Eligible | 5 Expiring"

    // Filter by level for sub-views
    const mlbPlayers = players.filter(p => p.current_level === 9);
    const minorPlayers = players.filter(p => p.current_level < 9);
  });
```

### Expiring Contracts Alert

Highlight players whose contracts expire this season:

```javascript
const expiring = players.filter(p => p.is_expiring && !p.has_extension);
// These players need action: extend, or they'll be processed at EOS
// minor/pre_arb will auto-renew, arb/fa_eligible will hit the market
```

---

## End-of-Season Processing Flow

The admin triggers EOS processing after the final week of the season. Here's what happens:

```
1. Credit service time
   └─ Every MLB-level player gets +1 mlb_service_years

2. Advance mid-contract players
   └─ current_year increments for all non-expiring contracts

3. Process expiring contracts
   ├─ Has extension? → Old contract finishes, extension takes over
   ├─ Minor league?  → Auto-renews: new 1-year contract at $40K
   ├─ Pre-arb MLB?   → Auto-renews: new 1-year contract at $800K
   ├─ Arb eligible?  → Contract finishes, player becomes free agent
   └─ FA eligible?   → Contract finishes, player becomes free agent
```

After EOS, the frontend should refresh all roster/contract views to reflect new state.

---

## Suggested UI Components

### Phase Badge
Color-coded pill showing the player's contract phase:
- **Minor** → green background
- **Pre-Arb** → blue background
- **Arb Eligible** → orange background (action needed)
- **FA Eligible** → red background (will leave)

### Service Time Progress Bar
Visual showing 0-6 service years with markers at 3 (arb) and 6 (FA):
```
[████████░░░░░░░░░░░░░░░░] 2/6 years
         ▲ Arb (3)        ▲ FA (6)
```

### Expiring Contract Warning
On roster views, flag players with `is_expiring: true` and `has_extension: false`:
- Minor/Pre-arb: info badge — "Will auto-renew"
- Arb eligible: warning badge — "Arb eligible, no extension"
- FA eligible: danger badge — "Will become free agent"
