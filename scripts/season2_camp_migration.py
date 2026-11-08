"""Check / apply migrations/season2_progression_camp.sql against the DATABASE_URL in .env.

  python scripts/season2_camp_migration.py --check     # read-only: what is applied, what is missing
  python scripts/season2_camp_migration.py --apply     # runs the camp migration (idempotent), then re-checks

The camp migration must run AFTER season2_amateur_pipeline.sql (it needs league_config). The
--apply path refuses if that prerequisite is missing. Take a Coolify DB backup before --apply.
"""
import argparse
import os
import re
import sys

import pymysql

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATION = os.path.join(ROOT, "migrations", "season2_progression_camp.sql")

CAMP_TABLES = ["training_camp_focus", "training_camp_results", "player_rating_snapshots", "progression_curve_stats"]
PREREQ_TABLES = ["league_config", "fa_config", "player_retirements", "draft_signing_offers"]
CAMP_KEYS = ["camp_regular_steps", "camp_intense_steps", "camp_intense_backfire", "camp_max_steps", "camp_max_backfire"]


def connect():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        env = os.path.join(ROOT, ".env")
        for line in open(env, encoding="utf-8"):
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
    m = re.match(r"mysql\+pymysql://([^:]+):([^@]*)@([^:/]+):?(\d+)?/(\w+)", url)
    if not m:
        sys.exit("DATABASE_URL not found or not a mysql+pymysql URL")
    user, pw, host, port, db = m.groups()
    print(f"target: {user}@{host}:{port or 3306}/{db}")
    return pymysql.connect(host=host, port=int(port or 3306), user=user, password=pw, database=db,
                           connect_timeout=10, read_timeout=120, autocommit=False), db


def check(conn, db):
    cur = conn.cursor()
    cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=%s", (db,))
    have = {r[0] for r in cur.fetchall()}
    print("\nprerequisite (season2_amateur_pipeline.sql):")
    prereq_ok = True
    for t in PREREQ_TABLES:
        ok = t in have
        prereq_ok &= ok
        print(f"  {t:28s} {'ok' if ok else 'MISSING'}")
    print("camp migration (season2_progression_camp.sql):")
    camp_ok = True
    for t in CAMP_TABLES:
        ok = t in have
        camp_ok &= ok
        print(f"  {t:28s} {'ok' if ok else 'MISSING'}")
    if "league_config" in have:
        cur.execute("SELECT config_key, config_value FROM league_config WHERE config_key IN (%s)"
                    % ",".join(["%s"] * (len(CAMP_KEYS) + 1)), CAMP_KEYS + ["retire_age_hard"])
        rows = dict(cur.fetchall())
        for k in CAMP_KEYS:
            print(f"  {k:28s} {rows.get(k, 'MISSING')}")
            camp_ok &= k in rows
        print(f"  {'retire_age_hard':28s} {rows.get('retire_age_hard', 'MISSING')}  (camp migration sets 40 -> 0)")
    try:
        cur.execute("SELECT MAX(age) FROM growth_curves")
        mx = cur.fetchone()[0]
        print(f"  {'growth_curves max age':28s} {mx}  (camp migration extends to 50)")
        camp_ok &= (mx or 0) >= 50
    except Exception as e:  # noqa: BLE001
        print(f"  growth_curves: {e}")
    print(f"\nprerequisite applied: {prereq_ok}    camp migration applied: {camp_ok}")
    return prereq_ok, camp_ok


def apply(conn):
    sql = open(MIGRATION, encoding="utf-8").read()
    # strip -- comments, split on ';'
    stmts = []
    buf = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmts.append("\n".join(buf).strip())
            buf = []
    if buf and "".join(buf).strip():
        stmts.append("\n".join(buf).strip())
    cur = conn.cursor()
    for i, st in enumerate(stmts, 1):
        head = " ".join(st.split())[:90]
        cur.execute(st)
        print(f"  [{i}/{len(stmts)}] rows={cur.rowcount:<4} {head}")
    conn.commit()
    print("committed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not (a.check or a.apply):
        ap.error("use --check or --apply")
    conn, db = connect()
    prereq_ok, camp_ok = check(conn, db)
    if a.apply:
        if not prereq_ok:
            sys.exit("\nREFUSING: season2_amateur_pipeline.sql is not applied; run it first.")
        if camp_ok:
            print("\ncamp migration already applied; nothing to do")
            return
        print(f"\napplying {MIGRATION} ...")
        apply(conn)
        check(conn, db)


if __name__ == "__main__":
    main()
