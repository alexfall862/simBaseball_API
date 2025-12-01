# Game Engine Integration Guide

This document describes how to integrate the simBaseball game engine with the simBaseball API.

## Architecture Overview

```
┌──────────────────┐         HTTP POST         ┌──────────────────┐
│  simBaseball_API │  ───────────────────────>  │  Game Engine     │
│                  │                             │  (Separate Repo) │
│  - Builds        │  <─────────────────────┐   │                  │
│    payloads      │      Returns results    │   │  - Simulates     │
│  - Stores        │                             │    games         │
│    results       │                             │  - Generates     │
│                  │                             │    stats         │
└──────────────────┘                             └──────────────────┘
```

**Both services:**
- Run as separate Flask applications
- Share the same MySQL database (via `DATABASE_URL` environment variable)
- Communicate via HTTP/REST

---

## What the API Sends

### Endpoint: `POST /simulate/batch`

The API will send batches of game payloads organized by subweek. Each subweek is processed sequentially (a → b → c → d).

### Request Format

```json
{
  "games": [
    {
      "game_id": 12345,
      "home_team_id": 42,
      "away_team_id": 67,
      "home_side": { ... },
      "away_side": { ... },
      "rules": { ... },
      "random_seed": "optional-seed-value"
    },
    // ... more games
  ],
  "subweek": "a"
}
```

### Game Payload Structure

Each game payload contains everything needed to simulate a single game:

```json
{
  "game_id": 12345,
  "home_team_id": 42,
  "away_team_id": 67,

  "home_side": {
    "team_id": 42,
    "team_name": "Boston Red Sox",
    "league_level": 9,

    "starting_pitcher": {
      "player_id": 501,
      "ratings": {
        "fastball": 65,
        "curveball": 58,
        "changeup": 62,
        "control": 70,
        "stamina": 85,
        "movement": 55
      },
      "pitch_hand": "R",
      "bat_hand": "R",
      "position_ratings": { ... }
    },

    "lineup": [
      {
        "slot": 1,
        "player_id": 201,
        "position": "CF",
        "ratings": {
          "contact": 72,
          "power": 58,
          "eye": 65,
          "speed": 80,
          "defense": 70
        },
        "bat_hand": "L",
        "pitch_hand": null
      },
      // ... 8 more batters (9 total)
    ],

    "bench": [
      {
        "player_id": 301,
        "ratings": { ... },
        "position": "C"
      },
      // ... more bench players
    ],

    "bullpen": [
      {
        "player_id": 502,
        "ratings": { ... },
        "pitch_hand": "L"
      },
      // ... more relievers
    ]
  },

  "away_side": {
    // Same structure as home_side
  },

  "rules": {
    "league_level": 9,
    "innings": 9,
    "dh": true,
    "extra_innings_rule": "standard",
    "pitch_clock": false
  },

  "random_seed": "optional-deterministic-seed"
}
```

### Player Ratings

All player ratings are integers (typically 0-100):

**Pitcher Ratings:**
- `fastball`: Fastball velocity/effectiveness
- `curveball`: Curveball effectiveness
- `changeup`: Changeup effectiveness
- `slider`: Slider effectiveness (if present)
- `control`: Command/control
- `stamina`: Endurance
- `movement`: Pitch movement
- `hold_runners`: Ability to prevent stolen bases

**Batter Ratings:**
- `contact`: Contact ability
- `power`: Power hitting
- `eye`: Plate discipline/walk rate
- `speed`: Running speed
- `stealing`: Base stealing ability
- `baserunning`: Baserunning instincts

**Fielding Ratings:**
- `defense`: Overall defensive ability
- `range`: Defensive range
- `arm`: Throwing arm strength
- `catching`: Catching ability (catchers)

---

## What the Engine Must Return

### Response Format

```json
{
  "results": [
    {
      "game_id": 12345,
      "home_score": 5,
      "away_score": 3,
      "winner": "home",
      "innings_played": 9,
      "events": [ ... ],
      "stats": { ... }
    },
    // ... more results (one per input game)
  ]
}
```

### Game Result Structure

```json
{
  "game_id": 12345,
  "home_score": 5,
  "away_score": 3,
  "winner": "home",  // "home" | "away" | "tie"
  "innings_played": 9,

  "events": [
    {
      "inning": 1,
      "half": "top",  // "top" | "bottom"
      "batter_id": 201,
      "pitcher_id": 501,
      "event_type": "single",  // "single", "double", "triple", "hr", "out", "walk", "strikeout", etc.
      "result": "Single to left field",
      "rbi": 0,
      "runs_scored": []
    },
    // ... more events (optional - can omit for performance)
  ],

  "stats": {
    "pitchers": {
      "501": {
        "player_id": 501,
        "team": "home",
        "innings_pitched": 6.0,
        "hits_allowed": 5,
        "runs_allowed": 3,
        "earned_runs": 2,
        "walks": 2,
        "strikeouts": 7,
        "pitches_thrown": 95,
        "win": true,
        "loss": false,
        "save": false
      },
      // ... more pitchers
    },

    "batters": {
      "201": {
        "player_id": 201,
        "team": "away",
        "at_bats": 4,
        "hits": 2,
        "doubles": 1,
        "triples": 0,
        "home_runs": 0,
        "rbi": 1,
        "runs": 1,
        "walks": 1,
        "strikeouts": 1,
        "stolen_bases": 0,
        "caught_stealing": 0
      },
      // ... more batters
    }
  }
}
```

---

## Flask Implementation Example

Here's a complete example for your game engine Flask app:

### Directory Structure

```
simBaseball_Engine/
├── app.py                 # Flask app
├── engine/
│   ├── __init__.py
│   └── simulator.py       # Your game simulation logic
├── requirements.txt
├── .env                   # Environment variables
└── README.md
```

### app.py

```python
# app.py
from flask import Flask, request, jsonify
import logging
import os

from engine.simulator import simulate_game

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "simBaseball-Engine"}), 200


@app.route("/simulate/batch", methods=["POST"])
def simulate_batch():
    """
    Simulate a batch of baseball games.

    Request body:
    {
        "games": [game_payload, ...],
        "subweek": "a"
    }

    Returns:
    {
        "results": [game_result, ...]
    }
    """
    try:
        data = request.json

        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        games = data.get("games", [])
        subweek = data.get("subweek", "a")

        if not games:
            return jsonify({"error": "No games provided"}), 400

        logger.info(f"Received {len(games)} games for subweek '{subweek}'")

        results = []

        for game_payload in games:
            game_id = game_payload.get("game_id")

            try:
                # Your simulation logic here
                result = simulate_game(game_payload)
                results.append(result)

                logger.info(
                    f"Simulated game {game_id}: "
                    f"{result['away_score']}-{result['home_score']}"
                )

            except Exception as e:
                logger.error(f"Failed to simulate game {game_id}: {e}")
                # Return error for this specific game
                results.append({
                    "game_id": game_id,
                    "error": str(e),
                    "home_score": 0,
                    "away_score": 0,
                    "winner": "error"
                })

        logger.info(f"Completed simulation of {len(results)} games")

        return jsonify({"results": results}), 200

    except Exception as e:
        logger.exception("Error in simulate_batch")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
```

### engine/simulator.py

```python
# engine/simulator.py
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def simulate_game(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simulate a single baseball game.

    Args:
        payload: Game payload from the API

    Returns:
        Game result with scores, events, and stats
    """
    game_id = payload["game_id"]
    home_side = payload["home_side"]
    away_side = payload["away_side"]
    rules = payload["rules"]

    logger.info(f"Simulating game {game_id}")

    # TODO: Implement your actual game simulation logic here
    # This is where you'd:
    # 1. Simulate each inning
    # 2. Track at-bats, pitches, events
    # 3. Calculate stats
    # 4. Determine winner

    # Placeholder result
    result = {
        "game_id": game_id,
        "home_score": 5,
        "away_score": 3,
        "winner": "home",
        "innings_played": 9,
        "events": [],  # List of play-by-play events
        "stats": {
            "pitchers": {},
            "batters": {}
        }
    }

    return result
```

### requirements.txt

```
Flask==3.0.3
flask-cors==4.0.1
gunicorn==23.0.0
python-dotenv==1.0.1
```

---

## Environment Configuration

### Development (.env file)

```bash
# Game Engine .env
PORT=5001
FLASK_ENV=development
DATABASE_URL=mysql+pymysql://user:password@localhost/simbaseball
```

### Railway Deployment

Set these environment variables in the Railway dashboard:

```bash
PORT=5001
DATABASE_URL=mysql+pymysql://user:password@host/simbaseball
```

---

## API Configuration

The API needs to know where to find your engine. Set this environment variable in the **API service**:

### Development
```bash
GAME_ENGINE_URL=http://localhost:5001
```

### Production (Railway)
```bash
GAME_ENGINE_URL=https://simbaseball-engine.railway.app
```

Or use Railway's internal networking:
```bash
GAME_ENGINE_URL=http://simbaseball-engine.railway.internal:5001
```

---

## Testing the Integration

### 1. Start both services locally

**Terminal 1 - API:**
```bash
cd simBaseball_API
python app.py
```

**Terminal 2 - Engine:**
```bash
cd simBaseball_Engine
python app.py
```

### 2. Test the engine health check

```bash
curl http://localhost:5001/health
```

Expected response:
```json
{"status": "healthy", "service": "simBaseball-Engine"}
```

### 3. Test a full week simulation

```bash
curl -X POST http://localhost:8080/api/v1/games/simulate-week \
  -H "Content-Type: application/json" \
  -d '{"league_year_id": 1, "season_week": 1}'
```

Check the logs in both terminals to see the flow:
1. API builds payloads
2. API sends to engine
3. Engine simulates games
4. Engine returns results
5. API receives results

---

## Error Handling

### Engine Unreachable

If the API can't reach the engine, it will raise:
```
ValueError: Failed to reach game engine at http://localhost:5001. Is the engine service running?
```

**Fix:**
- Ensure engine service is running
- Check `GAME_ENGINE_URL` environment variable
- Verify network connectivity (especially in Railway)

### Simulation Timeout

If simulation takes longer than 5 minutes (default timeout):
```
ValueError: Game engine timeout for subweek 'a'. The simulation took longer than 300 seconds.
```

**Fix:**
- Optimize simulation performance
- Increase timeout in `services/game_engine_client.py` (line 35)

### Invalid Response

If the engine returns an unexpected response:
```
ValueError: Engine returned invalid response type: <class 'str'>
```

**Fix:**
- Ensure engine returns `{"results": [...]}`
- Check engine logs for errors

---

## Performance Considerations

### Batch Size

Subweeks typically contain 10-15 games. Your engine should:
- Process games sequentially (to maintain determinism)
- Complete within 5 minutes for a full subweek
- Target: ~20-30 seconds per game maximum

### Optimization Tips

1. **Caching:** Cache frequently accessed data (player ratings, rules)
2. **Parallel Processing:** If determinism isn't required, simulate games in parallel
3. **Reduce Events:** Consider returning only essential events, not every pitch
4. **Database Efficiency:** Batch database writes when storing detailed stats

---

## Database Access (Optional)

Both services can access the same MySQL database. The engine can:

**Read from:**
- Player ratings (if you need real-time data)
- League rules
- Historical stats

**Write to:**
- Detailed game logs
- Play-by-play events
- Advanced statistics

**Example:**

```python
# engine/db.py
import os
from sqlalchemy import create_engine

def get_engine():
    url = os.getenv("DATABASE_URL")
    return create_engine(url, pool_pre_ping=True)
```

---

## Deployment Checklist

### Railway Setup

1. **Create two services:**
   - `simBaseball_API` (from this repo)
   - `simBaseball_Engine` (from your new repo)

2. **Set environment variables:**
   - API: `GAME_ENGINE_URL=https://simbaseball-engine.railway.app`
   - Engine: `PORT=5001`, `DATABASE_URL=...`

3. **Configure networking:**
   - Expose API publicly
   - Optionally keep engine internal-only

4. **Deploy in order:**
   - Deploy engine first
   - Note the engine's URL
   - Update API's `GAME_ENGINE_URL`
   - Deploy API

---

## Next Steps

After integration is complete, you can implement:

1. **Result Storage** (in API):
   - Create `game_results` table
   - Store scores, events, stats
   - Implement `_store_game_results()` in `services/game_payload.py`

2. **State Updates** (in API):
   - Update `player_fatigue_state` (decrease stamina)
   - Update `team_rotation_state` (advance rotation)
   - Update `player_injury_state` (apply injuries)
   - Implement `_update_player_state_after_subweek()` in `services/game_payload.py`

3. **Enhanced Events** (in Engine):
   - Pitch-by-pitch tracking
   - Defensive plays
   - Base running events
   - Injury occurrences

---

## Support

If you run into issues:

1. Check logs on both services
2. Verify environment variables are set correctly
3. Test the `/health` endpoint on the engine
4. Ensure both services can access the database

---

## Summary

**The API sends:**
- Complete game payloads with rosters, lineups, and rules
- Batched by subweek (a, b, c, d)
- Sequential processing for state management

**The Engine returns:**
- Game scores
- Winner determination
- Player statistics
- Optional: play-by-play events

**Both services:**
- Run independently
- Communicate via HTTP
- Share the same database
- Deploy separately on Railway

---

*Last updated: 2025*
