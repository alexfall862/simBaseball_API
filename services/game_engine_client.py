# services/game_engine_client.py

import os
import logging
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
    timeout: int = 300
) -> List[Dict[str, Any]]:
    """
    Send a batch of game payloads to the game engine for simulation.

    Args:
        games: List of game payloads (from build_game_payload)
        subweek: The subweek identifier ('a', 'b', 'c', 'd')
        timeout: Request timeout in seconds (default 300 = 5 minutes)

    Returns:
        List of game results from the engine. Each result contains:
        {
            "game_id": 123,
            "home_score": 5,
            "away_score": 3,
            "winner": "home" | "away" | "tie",
            "events": [...],  # pitch-by-pitch events
            "stats": {
                "pitchers": {...},
                "batters": {...}
            }
        }

    Raises:
        ValueError: If the engine returns an error or invalid response
        RequestException: If the engine is unreachable
        Timeout: If the simulation exceeds the timeout
    """
    if not games:
        logger.warning("simulate_games_batch called with empty games list")
        return []

    url = f"{GAME_ENGINE_URL}/simulate/batch"

    payload = {
        "games": games,
        "subweek": subweek
    }

    logger.info(
        f"Sending {len(games)} games to engine at {url} for subweek '{subweek}'"
    )

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "simBaseball-API/1.0"
            }
        )

        # Raise exception for 4xx/5xx status codes
        response.raise_for_status()

        data = response.json()

        # Validate response structure
        if not isinstance(data, dict):
            raise ValueError(f"Engine returned invalid response type: {type(data)}")

        results = data.get("results", [])

        if not isinstance(results, list):
            raise ValueError(f"Engine returned invalid results type: {type(results)}")

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
