# services/game_engine_client.py

import json
import os
import logging
from decimal import Decimal
from typing import Dict, Any, List
import requests
from requests.exceptions import RequestException, Timeout

logger = logging.getLogger(__name__)

# Read game engine URL from environment variable
# In production: https://simbaseball-engine.railway.app
# In development: http://localhost:5001
GAME_ENGINE_URL = os.getenv("GAME_ENGINE_URL", "http://localhost:5001")


def simulate_games_batch(
    games: List[Dict[str, Any]],
    subweek: str,
    timeout: int = 300,
    *,
    game_constants: Dict[str, Any] = None,
    level_configs: Dict[str, Any] = None,
    rules: Dict[str, Any] = None,
    injury_types: List[Dict[str, Any]] = None,
    league_year_id: int = None,
    season_week: int = None,
    league_level: int = None,
) -> List[Dict[str, Any]]:
    """
    Send a batch of game payloads to the game engine for simulation.

    Args:
        games: List of core game payloads (from build_game_payload_core)
        subweek: The subweek identifier ('a', 'b', 'c', 'd')
        timeout: Request timeout in seconds (default 300 = 5 minutes)
        game_constants: Static reference data (field zones, contact types, etc.)
        level_configs: Level-specific config keyed by level id string
        rules: Level rules keyed by level id string
        injury_types: Injury type definitions
        league_year_id: The league year id
        season_week: The season week number
        league_level: The league level id

    Returns:
        List of game results from the engine.

    Raises:
        ValueError: If the engine returns an error or invalid response
        RequestException: If the engine is unreachable
        Timeout: If the simulation exceeds the timeout
    """
    if not games:
        logger.warning("simulate_games_batch called with empty games list")
        return []

    url = f"{GAME_ENGINE_URL}/simulate/batch"

    # Build the payload the engine expects:
    # Shared config at top level, each games[i] has only game-specific data.
    # Engine falls back to top-level config when per-game fields are absent.
    lvl = league_level or (games[0].get("league_level_id") if games else None)

    wrapped_games = []
    for game_core in games:
        wrapped_games.append({
            "league_level": lvl,
            "subweeks": {
                subweek: [game_core],
            },
        })

    payload = {
        "subweek": subweek,
        "game_constants": game_constants or {},
        "level_configs": level_configs or {},
        "rules": rules or {},
        "injury_types": injury_types or [],
        "games": wrapped_games,
    }

    logger.info(
        f"Sending {len(games)} games to engine at {url} for subweek '{subweek}'"
    )

    # Pre-serialize to handle Decimal values from MySQL
    body = json.dumps(payload, default=lambda o: float(o) if isinstance(o, Decimal) else str(o))

    try:
        response = requests.post(
            url,
            data=body,
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "simBaseball-API/1.0"
            }
        )

        # Log and raise on 4xx/5xx status codes
        if not response.ok:
            logger.error(
                f"Engine returned {response.status_code}: {response.text[:2000]}"
            )
            response.raise_for_status()

        data = response.json()

        # Log the full response keys and any error/message fields for debugging
        logger.info(
            f"Engine response status={response.status_code}, "
            f"keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        )
        if isinstance(data, dict):
            for key in ("error", "message", "errors", "status", "detail"):
                if key in data:
                    logger.warning(f"Engine response['{key}']: {data[key]}")

        # Validate response structure
        if not isinstance(data, dict):
            raise ValueError(f"Engine returned invalid response type: {type(data)}")

        # Engine may return results as flat "results" array or nested in "subweeks"
        if "results" in data and isinstance(data["results"], list) and len(data["results"]) > 0:
            results = data["results"]
        elif "subweeks" in data and isinstance(data["subweeks"], dict):
            results = data["subweeks"].get(subweek, [])
        else:
            results = []

        if not isinstance(results, list):
            raise ValueError(f"Engine returned invalid results type: {type(results)}")

        # Log first result structure for debugging
        if results:
            first = results[0]
            scalar_keys = {k: v for k, v in first.items() if not isinstance(v, (dict, list))}
            logger.info(f"Engine first result keys={list(first.keys())}, scalars={scalar_keys}")
            if "result" in first:
                logger.info(f"Engine first result['result']={first['result']}")

        if len(results) != len(games):
            logger.warning(
                f"Engine returned {len(results)} results for {len(games)} games"
            )

        logger.info(
            f"Successfully received {len(results)} game results from engine "
            f"for subweek '{subweek}'"
        )

        return results

    except Timeout:
        logger.error(
            f"Game engine timeout after {timeout}s for subweek '{subweek}' "
            f"({len(games)} games)"
        )
        raise ValueError(
            f"Game engine timeout for subweek '{subweek}'. "
            f"The simulation took longer than {timeout} seconds."
        )

    except RequestException as e:
        logger.exception(f"Failed to communicate with game engine: {e}")
        raise ValueError(
            f"Failed to reach game engine at {GAME_ENGINE_URL}. "
            f"Is the engine service running? Error: {e}"
        )

    except Exception as e:
        logger.exception(f"Unexpected error during engine communication: {e}")
        raise


def check_engine_health() -> bool:
    """
    Check if the game engine is reachable and healthy.

    Returns:
        True if engine is healthy, False otherwise
    """
    try:
        url = f"{GAME_ENGINE_URL}/health"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            logger.info(f"Game engine health check passed: {GAME_ENGINE_URL}")
            return True
        else:
            logger.warning(
                f"Game engine health check failed with status {response.status_code}"
            )
            return False

    except Exception as e:
        logger.warning(f"Game engine health check failed: {e}")
        return False
