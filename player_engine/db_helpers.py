"""
Database helper functions for weighted random selection from seed tables.
All functions take a SQLAlchemy Core connection.

The SeedCache class preloads all seed data to avoid per-player DB round-trips
during batch generation. Single-player generation still works with direct queries.
"""
import random
from collections import defaultdict
from sqlalchemy import text


# ── Direct DB helpers (one query per call, used for single-player gen) ──────


def weighted_random_row(conn, query, params=None):
    """
    Execute a query that returns rows with a 'weight' column,
    then pick one row using weighted random selection.
    Returns the chosen row as a dict, or None if no rows found.
    """
    result = conn.execute(text(query), params or {})
    rows = result.mappings().all()
    if not rows:
        return None
    weights = [row["weight"] for row in rows]
    return random.choices(rows, weights=weights, k=1)[0]


def pick_region(conn):
    """
    Pick a random region weighted by population/baseball presence.
    Returns dict with: id, name, region_type, weight, name_pool.
    """
    return weighted_random_row(
        conn,
        "SELECT id, name, region_type, weight, name_pool FROM regions"
    )


def pick_city(conn, region_id):
    """
    Pick a random city within a region, weighted by population.
    Returns dict with: id, region_id, name, weight.
    """
    return weighted_random_row(
        conn,
        "SELECT id, region_id, name, weight FROM cities WHERE region_id = :rid",
        {"rid": region_id}
    )


def pick_name(conn, name_pool):
    """
    Pick a first name and last name from the name tables,
    filtered by the region's name_pool.
    Returns (firstname, lastname).
    """
    fname_row = weighted_random_row(
        conn,
        "SELECT name, weight FROM forenames WHERE region = :pool",
        {"pool": name_pool}
    )
    lname_row = weighted_random_row(
        conn,
        "SELECT name, weight FROM surnames WHERE region = :pool",
        {"pool": name_pool}
    )
    return (
        fname_row["name"] if fname_row else "Unknown",
        lname_row["name"] if lname_row else "Unknown"
    )


def pick_potential(conn, player_type, ability_class):
    """
    Pick a potential grade (A+, A, A-, ..., N) for a given player type
    and ability class, using the weights from the potential_weights table.
    Returns the grade string.
    """
    row = weighted_random_row(
        conn,
        """SELECT grade, weight FROM potential_weights
           WHERE player_type = :ptype AND ability_class = :aclass AND weight > 0""",
        {"ptype": player_type, "aclass": ability_class}
    )
    return row["grade"] if row else "F"


def get_growth_params(conn, grade, age):
    """
    Look up progression parameters for a given potential grade and age.
    Returns (prog_min, prog_mode, prog_max) or (0, 0, 0) if not found.
    """
    result = conn.execute(
        text("SELECT prog_min, prog_mode, prog_max FROM growth_curves WHERE grade = :g AND age = :a"),
        {"g": grade, "a": age}
    )
    row = result.mappings().first()
    if not row:
        return (0, 0, 0)
    return (row["prog_min"], row["prog_mode"], row["prog_max"])


def get_pitch_pool(conn, pool_num):
    """
    Get all pitch types in a given pool (1=fastball, 2=offspeed, 3=breaking).
    Returns list of dicts with: name, pool_weight.
    """
    result = conn.execute(
        text("SELECT name, pool_weight AS weight FROM pitch_types WHERE pool = :p AND pool_weight > 0"),
        {"p": pool_num}
    )
    return result.mappings().all()


def get_extra_pitches(conn, exclude_names):
    """
    Get all pitch types available for slots 4-5, excluding already-chosen pitches.
    Returns list of dicts with: name, extra_weight.
    """
    if not exclude_names:
        exclude_names = []
    placeholders = ", ".join(f":p{i}" for i in range(len(exclude_names)))
    params = {f"p{i}": name for i, name in enumerate(exclude_names)}
    query = f"""
        SELECT name, extra_weight AS weight FROM pitch_types
        WHERE extra_weight > 0 AND name NOT IN ({placeholders})
    """
    result = conn.execute(text(query), params)
    return result.mappings().all()


# ── SeedCache: preload all seed data for batch generation ───────────────────


class SeedCache:
    """
    Preloads all seed tables into memory so batch player generation
    avoids per-player DB round-trips (~49 queries/player → 0).

    Usage:
        cache = SeedCache(conn)
        region = cache.pick_region()
        city = cache.pick_city(region["id"])
        ...
    """

    def __init__(self, conn):
        self._load_regions(conn)
        self._load_cities(conn)
        self._load_names(conn)
        self._load_potentials(conn)
        self._load_pitches(conn)

    # ── Loading ─────────────────────────────────────────────

    def _load_regions(self, conn):
        rows = conn.execute(
            text("SELECT id, name, region_type, weight, name_pool FROM regions")
        ).mappings().all()
        self._regions = [dict(r) for r in rows]
        self._region_weights = [r["weight"] for r in self._regions]

    def _load_cities(self, conn):
        rows = conn.execute(
            text("SELECT id, region_id, name, weight FROM cities")
        ).mappings().all()
        self._cities_by_region = defaultdict(list)
        self._city_weights_by_region = defaultdict(list)
        for r in rows:
            d = dict(r)
            self._cities_by_region[d["region_id"]].append(d)
            self._city_weights_by_region[d["region_id"]].append(d["weight"])

    def _load_names(self, conn):
        fnames = conn.execute(
            text("SELECT name, weight, region FROM forenames")
        ).mappings().all()
        self._forenames_by_pool = defaultdict(list)
        self._fname_weights_by_pool = defaultdict(list)
        for r in fnames:
            self._forenames_by_pool[r["region"]].append(r["name"])
            self._fname_weights_by_pool[r["region"]].append(r["weight"])

        lnames = conn.execute(
            text("SELECT name, weight, region FROM surnames")
        ).mappings().all()
        self._surnames_by_pool = defaultdict(list)
        self._lname_weights_by_pool = defaultdict(list)
        for r in lnames:
            self._surnames_by_pool[r["region"]].append(r["name"])
            self._lname_weights_by_pool[r["region"]].append(r["weight"])

    def _load_potentials(self, conn):
        rows = conn.execute(
            text(
                "SELECT player_type, ability_class, grade, weight "
                "FROM potential_weights WHERE weight > 0"
            )
        ).mappings().all()
        self._pot_grades = defaultdict(list)
        self._pot_weights = defaultdict(list)
        for r in rows:
            key = (r["player_type"], r["ability_class"])
            self._pot_grades[key].append(r["grade"])
            self._pot_weights[key].append(r["weight"])

    def _load_pitches(self, conn):
        rows = conn.execute(
            text("SELECT name, pool, pool_weight, extra_weight FROM pitch_types")
        ).mappings().all()
        self._pitch_pools = defaultdict(list)
        self._pitch_pool_weights = defaultdict(list)
        self._all_pitches = []
        for r in rows:
            d = dict(r)
            self._all_pitches.append(d)
            if d["pool_weight"] and d["pool_weight"] > 0:
                self._pitch_pools[d["pool"]].append(d)
                self._pitch_pool_weights[d["pool"]].append(d["pool_weight"])

    # ── Weighted random picks (in-memory, no DB) ───────────

    def pick_region(self):
        return random.choices(self._regions, self._region_weights, k=1)[0]

    def pick_city(self, region_id):
        cities = self._cities_by_region.get(region_id)
        if not cities:
            return {"name": "Unknown"}
        weights = self._city_weights_by_region[region_id]
        return random.choices(cities, weights, k=1)[0]

    def pick_name(self, name_pool):
        fnames = self._forenames_by_pool.get(name_pool)
        lnames = self._surnames_by_pool.get(name_pool)
        fn = random.choices(fnames, self._fname_weights_by_pool[name_pool], k=1)[0] if fnames else "Unknown"
        ln = random.choices(lnames, self._lname_weights_by_pool[name_pool], k=1)[0] if lnames else "Unknown"
        return fn, ln

    def pick_potential(self, player_type, ability_class):
        key = (player_type, ability_class)
        grades = self._pot_grades.get(key)
        if not grades:
            return "F"
        weights = self._pot_weights[key]
        return random.choices(grades, weights, k=1)[0]

    def get_pitch_pool(self, pool_num):
        return self._pitch_pools.get(pool_num, [])

    def get_pitch_pool_weights(self, pool_num):
        return self._pitch_pool_weights.get(pool_num, [])

    def get_extra_pitches(self, exclude_names):
        exclude = set(exclude_names)
        pitches = [p for p in self._all_pitches if p["extra_weight"] and p["extra_weight"] > 0 and p["name"] not in exclude]
        return pitches
