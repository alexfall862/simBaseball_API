# player_engine Integration Guide

## What This Is

`player_engine` is a self-contained Python package that handles two core operations for the baseball sim:

1. **Player Generation** — creating a new player from scratch with randomized but realistically weighted attributes
2. **Player Progression** — aging a player by one year and evolving all their abilities based on potential grades

It reads from 7 seed/lookup tables and writes to the existing `simbbPlayers` table. No other dependencies beyond SQLAlchemy and the Python standard library.

---

## Prerequisites

### Python Dependencies

Already in your requirements — no new packages needed:
- `SQLAlchemy >= 2.0`
- `pymysql`
- Python stdlib `random` and `statistics`

### Database Tables

Run the 7 migration files (in the `migrations/` folder) **in order** before using the engine. They create and populate:

| Table | Rows | Purpose |
|---|---|---|
| `growth_curves` | 420 | Progression parameters by potential grade and age |
| `regions` | 242 | Countries + US states with selection weights |
| `cities` | ~13,000 | Cities per region with population weights |
| `forenames` | 93,894 | First names with frequency by region |
| `surnames` | 170,082 | Last names with frequency by region |
| `pitch_types` | 14 | Pitch type definitions with pool/weight info |
| `potential_weights` | 112 | Grade assignment probabilities by player type and ability class |

The `simbbPlayers` table must already exist with its current schema. The engine reads and writes to it directly.

---

## Module Structure

```
player_engine/
├── __init__.py                # Exports: generate_player, progress_player, progress_all_players
├── constants.py               # Ability mappings, static weight tables, distribution parameters
├── db_helpers.py              # Weighted random selection from seed tables
├── player_generation.py       # generate_player(), generate_players()
└── player_progression.py      # progress_player(), progress_all_players()
```

### What Each Module Does

**`constants.py`** — No DB access. Contains:
- `ABILITY_CLASS_MAP`: maps every ability column name (e.g. `"contact"`, `"throwpower"`) to its ability class (`"Ability"`, `"ThrowAbility"`, etc.). This determines which row of `potential_weights` is used when rolling that ability's potential grade.
- Static weight arrays for handedness, arm angle, injury risk, durability (these are small enough that they don't need their own DB table).
- Distribution parameters for height, weight, and splits.

**`db_helpers.py`** — Low-level DB functions. Every function takes a SQLAlchemy `Session` as its first argument.
- `weighted_random_row(session, query, params)`: the core utility. Runs a query, expects a `weight` column, uses `random.choices()` to pick one row. Used by everything else.
- `pick_region`, `pick_city`, `pick_name`: location/name selection.
- `pick_potential`: rolls a potential grade from `potential_weights`.
- `get_growth_params`: looks up `(prog_min, prog_mode, prog_max)` from `growth_curves`.
- `get_pitch_pool`, `get_extra_pitches`: pitch repertoire selection.

**`player_generation.py`** — The main generation pipeline.
- `generate_player(session, age=15)` — creates one player, INSERTs into `simbbPlayers`, returns the player dict with the new `id`.
- `generate_players(session, count, age=15)` — convenience wrapper to create multiple.

**`player_progression.py`** — The progression pipeline.
- `progress_player(session, player_id)` — ages one player by 1 year, updates all ability bases.
- `progress_all_players(session, max_age=45)` — batch version, progresses every player under `max_age`.

---

## How Player Generation Works

When `generate_player(session)` is called, it runs through this pipeline:

### Step 1: Position Type
50/50 coin flip between `"Pitcher"` and `"Position"`. This choice affects every potential grade roll that follows — pitchers get good pitching potentials and bad batting potentials, and vice versa.

### Step 2: Origin (Region + City)
- Query all rows from `regions`, weighted random pick by `weight` column.
- Weights reflect real-world baseball talent distribution. Cuba has weight 330, Dominican Republic 1500, US states range 7-1700. Most countries are weight 1.
- Once a region is chosen, query `cities` for that region's ID, pick one weighted by population.
- The region's `region_type` (`"usa"` or `"international"`) is stored on the player as `intorusa`.
- The region's `name` is stored as `area`.

### Step 3: Name
- Uses the region's `name_pool` field (not `name`) to query `forenames` and `surnames`.
- For all US states, `name_pool` is `"United States"` — so a player from Georgia (the US state) draws from American name pools, while a player from Georgia (the country) draws from Georgian names.
- Names are picked by weighted random from frequency data.

### Step 4: Physical Attributes
All from normal distributions, no DB lookups:
- **Height**: `N(72, 7/3)` inches, rounded to int. Roughly 68-76 inch range.
- **Weight**: `height * N(2.8, 0.8/3)`, rounded to int. Scales with height.
- **Handedness**: weighted draw → `(bat_hand, pitch_hand)`. 60% R/R, 20% L/L, 5% each for the 4 cross/switch combos.
- **Arm angle**: weighted draw. ~43% three-quarters, ~43% overhead, ~11% sidearm, ~3% submarine.
- **Injury risk**: 75% Normal, symmetric tails (Dependable/Risky at 10%, Safe/Volatile at 2.5%).
- **Durability**: same distribution as injury risk.

### Step 5: Splits
- Pull% drawn from `N(40, 10)`, clamped to [25, 55].
- Center% = `remainder * (4.08/7)`, Oppo% = `remainder * (2.92/7)`.
- Stored as `left_split`, `center_split`, `right_split`.

### Step 6: Ability Potentials
This is the most important step. Every ability gets a **potential grade** (A+, A, A-, B+, ..., D-, F, N) that permanently determines its growth trajectory.

For each of the 19 standard abilities, the engine:
1. Looks up the ability's class from `ABILITY_CLASS_MAP` (e.g. `"contact"` → `"Ability"`)
2. Queries `potential_weights` for `(player_type, ability_class)` to get all 14 grades and their weights
3. Weighted random pick → that's the ability's potential

**How the weights work by player type:**

| Scenario | What happens |
|---|---|
| Pitcher's pitching abilities (`PitchAbility`) | Weighted toward real grades — A+ through D- all have meaningful weight. F is heavily weighted (750) but good grades are possible. |
| Pitcher's batting abilities (`Ability`) | Almost all weight on F (152) and N (770). Pitchers are bad batters. |
| Pitcher's catching (`CatchAbility`) | Only D+/D/D-/F have weight. Pitchers can't catch. |
| Pitcher's throwing (`ThrowAbility`) | Bell curve centered on B-/C+. Pitchers throw well. |
| Position player's batting (`Ability`) | Same as Pitcher's PitchAbility — weighted toward real grades. |
| Position player's pitching (`PitchAbility`) | Same as Pitcher's Ability — almost all F/N. |
| Position player's catching (`CatchAbility`) | Lower weights than Ability but real grades possible (for catchers). Still heavily F-weighted (875). |
| Position player's throwing (`ThrowAbility`) | Same distribution as Position/Ability. |

All `_base` values start at `0.0`. The potential grade is what matters — it controls the growth curve that will be applied during progression.

### Step 7: Pitch Repertoire
Every player (both pitchers and position players) gets 5 pitches:

| Slot | Pool | Options (weight) |
|---|---|---|
| 1 (Fastball) | Pool 1 | Four-Seam (3), Two-Seam (2), Cutter (1), Sinker (0.5) |
| 2 (Off-speed) | Pool 2 | Change Up (3), Circle Change (2), Splitter (1) |
| 3 (Breaking) | Pool 3 | Curveball (15), Slider (15), Slurve (5), Screwball (0.25), Knuckle Curve (0.25) |
| 4 (Open) | Remaining | Any unused pitch type, weighted by `extra_weight` |
| 5 (Open) | Remaining | Any unused pitch type, weighted by `extra_weight` |

Each pitch gets 4 sub-abilities: `pacc` (accuracy), `pcntrl` (control), `pbrk` (break), `consist` (consistency). Each sub-ability gets its own independent potential grade rolled from `PitchAbility` weights. That's 20 additional potential rolls per player.

`pitch*_ovr` is the mean of the 4 sub-ability display values (rounded base values). At creation it's 0.0; it gets recalculated during each progression tick.

### Step 8: INSERT
All values are collected into a dict and inserted into `simbbPlayers` in one statement. The auto-incremented `id` is returned.

---

## How Progression Works

When `progress_player(session, player_id)` is called:

### Step 1: Age
Player's age increments by 1. If the new age is outside the growth table range (16-45), only the age is updated and abilities are left unchanged.

### Step 2: Ability Progression (x39 abilities)
For each of the 19 standard abilities + 20 pitch sub-abilities:

1. Read the ability's current `_base` value and `_pot` (potential grade) from the player row.
2. Query `growth_curves` for `(grade, new_age)` → get `(prog_min, prog_mode, prog_max)`.
3. Sample `delta` from `random.triangular(prog_min, prog_max, prog_mode)`.
4. If `new_age <= 19` and `delta < -1`, clamp to `-1.0` (young players don't regress hard).
5. `new_base = current_base + delta`.

### Step 3: Pitch OVR Recalculation
For each of the 5 pitch slots, `pitch*_ovr` = `mean(round(pacc_base), round(pcntrl_base), round(pbrk_base), round(consist_base))`.

### Step 4: UPDATE
All updated values are written back in a single UPDATE statement.

### Understanding the Growth Curves

The `growth_curves` table has 14 grades x 30 ages = 420 rows. Each row is a triangular distribution: `(prog_min, prog_mode, prog_max)`.

**General pattern across all grades:**

| Age Range | Phase | What Happens |
|---|---|---|
| 16 | Burst | Large initial growth possible (mode 0-30 depending on grade) |
| 17-28 | Development | Gradual growth, mode decreases by ~1/year |
| 29 | Plateau | All grades converge: `(-3, 0, 2)` — minimal change |
| 30-33 | Early decline | Mode hits 0, min becomes more negative |
| 34-36 | Decline | Mode goes to -1, min drops to -6/-7/-8 |
| 37-45 | Late decline | All grades converge: `(-9, -2, 0)` — steady decline |

**Difference between grades:**
The grade controls the mode at age 16 (initial growth burst) and how quickly the mode drops to 0. An A+ player's mode starts at 30 and decreases by ~2/year. An F player's mode starts at 5 and goes negative by age 17. An N (no potential) player starts at 0 and is negative from 17 onward.

After age 29, all grades decline at the same rate. The grade only matters for the development years.

### Batch Progression

`progress_all_players(session, max_age=45)` queries all player IDs with `age < max_age` and calls `progress_player` for each. Returns the count.

Retirement logic is **not** handled by the engine — that's for your contract/roster system. The engine just won't progress players beyond age 45 (growth table ends there).

---

## Flask Integration Examples

### Basic Usage

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from player_engine import generate_player, progress_player, progress_all_players

engine = create_engine("mysql+pymysql://user:pass@host/db")

# In a route or wherever you have your session:
with Session(engine) as session:
    new_player = generate_player(session)
    print(f"Created player {new_player['id']}: {new_player['firstname']} {new_player['lastname']}")
```

### As Flask Route Handlers

```python
@app.route("/api/players/generate", methods=["POST"])
def api_generate_player():
    count = request.json.get("count", 1)
    age = request.json.get("age", 15)
    with Session(engine) as session:
        players = [generate_player(session, age=age) for _ in range(count)]
    return jsonify({"created": len(players), "ids": [p["id"] for p in players]})

@app.route("/api/players/<int:player_id>/progress", methods=["POST"])
def api_progress_player(player_id):
    with Session(engine) as session:
        progress_player(session, player_id)
    return jsonify({"status": "ok"})

@app.route("/api/players/progress-all", methods=["POST"])
def api_progress_all():
    with Session(engine) as session:
        count = progress_all_players(session)
    return jsonify({"progressed": count})
```

### If You Already Have a Session Pattern

If your app uses a shared session (e.g. `db.session` from Flask-SQLAlchemy), just pass that in instead. The engine calls `session.commit()` internally after each insert/update. If you need to control transactions yourself, remove the `session.commit()` calls from `player_generation.py` and `player_progression.py` and commit externally.

---

## Display Values

The old system stored both `base` (raw float) and `display` (rounded int) for every ability. The new system only stores `base` and `pot`. Display values are computed on the fly:

```python
display_value = int(round(base_value, 0))
```

This means your frontend or API layer should compute display on read, not expect it from the DB. For example:

```python
player = session.execute(text("SELECT * FROM simbbPlayers WHERE id = :id"), {"id": 1}).mappings().first()
contact_display = int(round(player["contact_base"] or 0))
```

---

## Performance Notes

**Player Generation** makes ~30 DB queries per player:
- 1 for region, 1 for city, 2 for name (fore + sur)
- 19 potential rolls (1 query each for standard abilities)
- 20 potential rolls for pitch sub-abilities
- 3 pitch pool queries + 2 extra pitch queries
- 1 INSERT

For bulk generation, the main bottleneck is the potential rolls (39 queries that each load the same 8-14 rows from `potential_weights`). If you need to generate hundreds of players at once, consider caching the `potential_weights` table in memory at the start of the batch:

```python
# Example optimization for bulk generation:
result = session.execute(text("SELECT * FROM potential_weights WHERE weight > 0"))
all_weights = result.mappings().all()
# Group by (player_type, ability_class) and pass to generation functions
```

**Player Progression** makes ~40 DB queries per player:
- 1 SELECT for the player row
- 39 growth_curves lookups (one per ability)
- 1 UPDATE

Same caching idea applies — load all 420 growth_curves rows into a dict at the start of a batch progression run.

**Name tables** are the largest (264K rows combined). The queries filter by `region`, which is indexed. For high-traffic generation, consider adding a composite index on `(region, weight)` if query times are slow.

---

## Seed Data Tuning

All weights and distributions are tunable by editing the seed tables directly — no code changes needed:

- **Want more Cuban players?** Increase Cuba's weight in `regions`.
- **Want A+ potential to be rarer?** Decrease its weight in `potential_weights`.
- **Want slower aging curves?** Adjust `prog_min`/`prog_mode`/`prog_max` in `growth_curves`.
- **Want to add a new pitch type?** INSERT into `pitch_types` with a pool assignment and weights.
- **Want to change the fastball distribution?** Update `pool_weight` values for pool 1 in `pitch_types`.

Static weights in `constants.py` (handedness, arm angle, injury risk, durability, height/weight distributions) require a code change if you want to adjust them. These could be moved to DB tables in the future if you want full tunability without redeployment.
