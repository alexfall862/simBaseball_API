"""
Database helper functions for weighted random selection from seed tables.
All functions take a SQLAlchemy Core connection.
"""
import random
from sqlalchemy import text


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
