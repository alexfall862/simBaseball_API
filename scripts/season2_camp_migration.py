"""Check / apply the Season 2 migration chain against $DATABASE_URL (falls back to .env).

  python scripts/season2_camp_migration.py --check     read-only report, per migration and per statement
  python scripts/season2_camp_migration.py --apply     applies whatever is missing, in order (asks to confirm)
  python scripts/season2_camp_migration.py --apply --yes

Chain (docs/OFFSEASON_RUNBOOK.md / MASTER_PLAN_SEASON_2 §12), applied strictly in this order:
  1. seed_financial_config.sql
  2. seed_draft_slot_values.sql
  3. add_draft_picks_player_unique.sql
  4. normalize_finished_contracts_inactive.sql
  5. season2_amateur_pipeline.sql      (contains ALTERs that fail if re-run)
  6. season2_progression_camp.sql

Every statement is classified before it runs:
  * ALTER TABLE .. ADD COLUMN ..     skipped when all columns exist; REFUSES if only some exist
  * ALTER TABLE .. ADD UNIQUE KEY k  skipped when index k exists; REFUSES if duplicates would violate it
  * ALTER TABLE .. MODIFY COLUMN c ENUM(..)  skipped when the column already allows every value
  * CREATE TABLE IF NOT EXISTS / INSERT IGNORE / guarded INSERT/UPDATE   always run (idempotent)
so re-running --apply after a partial failure only does the remaining work.

MySQL commits DDL implicitly, so this is not one transaction. Take a database backup first.
"""
import argparse
import os
import re
import sys

import pymysql

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIG_DIR = os.path.join(ROOT, "migrations")
CHAIN = [
    "seed_financial_config.sql",
    "seed_draft_slot_values.sql",
    "add_draft_picks_player_unique.sql",
    "normalize_finished_contracts_inactive.sql",
    "season2_amateur_pipeline.sql",
    "season2_progression_camp.sql",
]


# ---------------------------------------------------------------- connection
def connect():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        env = os.path.join(ROOT, ".env")
        if os.path.exists(env):
            for line in open(env, encoding="utf-8"):
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
    m = re.match(r"mysql\+pymysql://([^:]+):([^@]*)@([^:/]+):?(\d+)?/(\w+)", url)
    if not m:
        sys.exit("DATABASE_URL not found or not a mysql+pymysql URL")
    user, pw, host, port, db = m.groups()
    print(f"target: {user}@{host}:{port or 3306}/{db}")
    conn = pymysql.connect(host=host, port=int(port or 3306), user=user, password=pw, database=db,
                           connect_timeout=10, read_timeout=600, write_timeout=600, autocommit=True)
    return conn, db


# ---------------------------------------------------------------- parsing
def statements(path):
    out, buf = [], []
    for line in open(path, encoding="utf-8").read().splitlines():
        if line.strip().startswith("--") or not line.strip() and not buf:
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            out.append("\n".join(buf).strip().rstrip(";").strip())
            buf = []
    if "".join(buf).strip():
        out.append("\n".join(buf).strip().rstrip(";").strip())
    return out


def head(sql, n=80):
    return " ".join(sql.split())[:n]


# ---------------------------------------------------------------- schema probes
class Schema:
    def __init__(self, conn, db):
        self.conn, self.db = conn, db

    def q(self, sql, args=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()

    def table_exists(self, t):
        return bool(self.q("SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (self.db, t)))

    def columns(self, t):
        return {r[0].lower(): r[1] for r in self.q(
            "SELECT COLUMN_NAME, COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
            (self.db, t))}

    def index_exists(self, t, name):
        return bool(self.q("SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s",
                           (self.db, t, name)))


ENUM_VALS = re.compile(r"'((?:[^']|'')*)'")


def classify(sql, s: Schema):
    """Return (action, note): action in run | skip | refuse."""
    flat = " ".join(sql.split())
    m = re.match(r"ALTER TABLE `?(\w+)`?\s+(.*)$", flat, re.I)
    if not m:
        return "run", "idempotent"
    table, rest = m.group(1), m.group(2)
    if not s.table_exists(table):
        return "refuse", f"table {table} does not exist"
    cols = s.columns(table)

    adds = re.findall(r"ADD COLUMN `?(\w+)`?", rest, re.I)
    if adds:
        present = [c for c in adds if c.lower() in cols]
        if len(present) == len(adds):
            return "skip", f"{table}: columns already exist ({', '.join(adds)})"
        if present:
            return "refuse", f"{table}: partially applied, {present} exist but {[c for c in adds if c not in present]} do not"
        return "run", f"{table}: add {', '.join(adds)}"

    uk = re.search(r"ADD UNIQUE KEY `?(\w+)`?\s*\(([^)]*)\)", rest, re.I)
    if uk:
        name, keycols = uk.group(1), [c.strip(" `") for c in uk.group(2).split(",")]
        if s.index_exists(table, name):
            return "skip", f"{table}: index {name} already exists"
        nn = " AND ".join(f"`{c}` IS NOT NULL" for c in keycols)
        cl = ", ".join(f"`{c}`" for c in keycols)
        dups = s.q(f"SELECT COUNT(*) FROM (SELECT 1 FROM `{table}` WHERE {nn} GROUP BY {cl} HAVING COUNT(*) > 1) d")[0][0]
        if dups:
            return "refuse", f"{table}: {dups} duplicate ({cl}) group(s) would violate {name}; clean them first"
        return "run", f"{table}: add unique key {name}"

    mod = re.search(r"MODIFY COLUMN `?(\w+)`?\s+ENUM\((.*?)\)", rest, re.I)
    if mod:
        col, want = mod.group(1).lower(), set(ENUM_VALS.findall(mod.group(2)))
        cur_type = cols.get(col)
        if cur_type is None:
            return "refuse", f"{table}.{col} does not exist"
        have = set(ENUM_VALS.findall(cur_type))
        if want <= have:
            return "skip", f"{table}.{col}: enum already allows all values"
        if not have <= want:
            return "refuse", f"{table}.{col}: new enum would drop existing values {sorted(have - want)}"
        return "run", f"{table}.{col}: enum adds {sorted(want - have)}"

    return "refuse", f"unrecognised ALTER form, apply by hand: {head(flat)}"


# ---------------------------------------------------------------- per-migration status
def status_notes(s: Schema):
    """Human-readable 'applied?' signals for the guarded (non-ALTER) migrations."""
    notes = {}
    try:
        n = s.q("SELECT COUNT(*) FROM financial_config")[0][0]
        notes["seed_financial_config.sql"] = f"financial_config rows: {n}" + ("" if n else "  (needs league_years row 2026)")
    except Exception as e:  # noqa: BLE001
        notes["seed_financial_config.sql"] = f"financial_config: {e}"
    try:
        n = s.q("SELECT COUNT(*) FROM draft_slot_values WHERE pick_in_round IS NULL")[0][0]
        notes["seed_draft_slot_values.sql"] = f"per-round slot values: {n}/20"
    except Exception as e:  # noqa: BLE001
        notes["seed_draft_slot_values.sql"] = f"draft_slot_values: {e}"
    try:
        n = s.q("SELECT COUNT(*) FROM contracts WHERE isFinished = 1 AND isActive = 1")[0][0]
        notes["normalize_finished_contracts_inactive.sql"] = f"finished-but-active contracts: {n}"
    except Exception as e:  # noqa: BLE001
        notes["normalize_finished_contracts_inactive.sql"] = f"contracts: {e}"
    try:
        tables = ["league_config", "fa_config", "player_retirements", "draft_signing_offers", "draft_trade_proposals"]
        notes["season2_amateur_pipeline.sql"] = "tables: " + ", ".join(f"{t}={'ok' if s.table_exists(t) else 'MISSING'}" for t in tables)
    except Exception as e:  # noqa: BLE001
        notes["season2_amateur_pipeline.sql"] = str(e)
    try:
        tables = ["training_camp_focus", "training_camp_results", "player_rating_snapshots", "progression_curve_stats"]
        mx = s.q("SELECT MAX(age) FROM growth_curves")[0][0]
        notes["season2_progression_camp.sql"] = ("tables: " + ", ".join(f"{t}={'ok' if s.table_exists(t) else 'MISSING'}" for t in tables)
                                                + f"; growth_curves max age {mx}")
    except Exception as e:  # noqa: BLE001
        notes["season2_progression_camp.sql"] = str(e)
    return notes


def plan(s: Schema):
    out = []
    for fn in CHAIN:
        path = os.path.join(MIG_DIR, fn)
        if not os.path.exists(path):
            sys.exit(f"missing migration file {path}")
        out.append((fn, [(sql, *classify(sql, s)) for sql in statements(path)]))
    return out


def report(s: Schema):
    notes = status_notes(s)
    p = plan(s)
    refusals = 0
    pending_ddl = 0
    for fn, stmts in p:
        print(f"\n{fn}")
        if fn in notes:
            print(f"  status: {notes[fn]}")
        for sql, action, note in stmts:
            tag = {"run": "RUN ", "skip": "skip", "refuse": "STOP"}[action]
            if action == "refuse":
                refusals += 1
            if action == "run" and note != "idempotent":
                pending_ddl += 1
            print(f"  [{tag}] {head(sql, 70):70s}  {note if note != 'idempotent' else ''}")
    try:
        cfg = dict(s.q("SELECT config_key, config_value FROM league_config WHERE config_key = 'retire_age_hard'"))
        print(f"\nleague_config.retire_age_hard = {cfg.get('retire_age_hard', 'MISSING')}  (Season 2 sets 0: no age-only retirement)")
    except Exception:  # noqa: BLE001
        print("\nleague_config: not present yet")
    print(f"\nschema changes still to apply: {pending_ddl}    blocking problems: {refusals}")
    return p, refusals


# ---------------------------------------------------------------- apply
def apply(conn, s: Schema, assume_yes: bool):
    p, refusals = report(s)
    if refusals:
        sys.exit("\nREFUSING: fix the STOP lines above first (nothing was changed).")
    if not assume_yes:
        print("\nThis writes to the database above. Take a backup first.")
        if input("Type APPLY to continue: ").strip() != "APPLY":
            sys.exit("aborted")
    for fn, stmts in p:
        print(f"\n== {fn}")
        for sql, action, note in stmts:
            # re-classify right before running: an earlier statement may have changed the schema
            action, note = classify(sql, s)
            if action == "skip":
                print(f"  skip  {note}")
                continue
            if action == "refuse":
                sys.exit(f"  STOP  {note}\nstopped; statements above this line were applied.")
            with conn.cursor() as cur:
                cur.execute(sql)
                print(f"  ok    rows={cur.rowcount:<6} {head(sql, 70)}")
    print("\nall migrations applied. Re-checking:")
    report(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--yes", action="store_true", help="skip the APPLY confirmation prompt")
    a = ap.parse_args()
    if not (a.check or a.apply):
        ap.error("use --check or --apply")
    conn, db = connect()
    s = Schema(conn, db)
    if a.apply:
        apply(conn, s, a.yes)
    else:
        report(s)


if __name__ == "__main__":
    main()
