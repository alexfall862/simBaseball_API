"""
Dump a single game payload in the full format the engine expects.
Saves to engine_payload_sample.json for debugging.

Usage:  python dump_engine_payload.py
"""
import json
import os
from dotenv import load_dotenv

load_dotenv()

from db import get_engine
from services.game_payload import build_game_payload
from sqlalchemy import text

engine = get_engine()

with engine.connect() as conn:
    # Grab one game from week 1
    row = conn.execute(text(
        "SELECT id FROM gamelist WHERE season = 1 AND season_week = 1 LIMIT 1"
    )).fetchone()

    if not row:
        print("No games found for season=1, week=1")
        exit(1)

    game_id = row[0]
    print(f"Building full payload for game_id={game_id} ...")

    # build_game_payload returns the full format with game_constants,
    # level_configs, rules, injury_types, and subweeks
    full_payload = build_game_payload(conn, game_id)

out_path = os.path.join(os.path.dirname(__file__), "engine_payload_sample.json")
with open(out_path, "w") as f:
    json.dump(full_payload, f, indent=2, default=str)

print(f"Saved to {out_path}")
print(f"Payload size: {os.path.getsize(out_path) / 1024:.1f} KB")
print(f"Top-level keys: {list(full_payload.keys())}")
