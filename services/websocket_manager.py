# services/websocket_manager.py
"""
WebSocket connection manager for broadcasting simulation state to connected clients.

This module maintains a list of active WebSocket connections and provides
methods to broadcast the current Timestamp state to all clients.

Usage:
    from services.websocket_manager import ws_manager

    # In your endpoint after state changes:
    ws_manager.broadcast_timestamp()
"""

import logging
import threading
from typing import Set, Any
import json

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts.

    Thread-safe implementation for handling multiple concurrent connections.
    """

    def __init__(self):
        self._connections: Set[Any] = set()
        self._lock = threading.Lock()

    def add_connection(self, ws) -> None:
        """Add a new WebSocket connection to the pool."""
        with self._lock:
            self._connections.add(ws)
            logger.info(
                f"WebSocket connected. Total connections: {len(self._connections)}"
            )

    def remove_connection(self, ws) -> None:
        """Remove a WebSocket connection from the pool."""
        with self._lock:
            self._connections.discard(ws)
            logger.info(
                f"WebSocket disconnected. Total connections: {len(self._connections)}"
            )

    def get_connection_count(self) -> int:
        """Return the number of active connections."""
        with self._lock:
            return len(self._connections)

    def broadcast(self, data: dict) -> int:
        """
        Broadcast data to all connected WebSocket clients.

        Args:
            data: Dictionary to send as JSON

        Returns:
            Number of clients successfully sent to
        """
        message = json.dumps(data)
        sent_count = 0
        failed_connections = []

        with self._lock:
            connections = list(self._connections)

        for ws in connections:
            try:
                ws.send(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                failed_connections.append(ws)

        # Clean up failed connections
        if failed_connections:
            with self._lock:
                for ws in failed_connections:
                    self._connections.discard(ws)

        logger.info(f"Broadcast sent to {sent_count} clients")
        return sent_count

    def broadcast_timestamp(self) -> int:
        """
        Fetch current timestamp from database and broadcast to all clients.

        Returns:
            Number of clients successfully sent to
        """
        try:
            from services.timestamp import get_current_timestamp

            timestamp_data = get_current_timestamp()

            if timestamp_data:
                return self.broadcast(timestamp_data)
            else:
                logger.warning("No timestamp data to broadcast")
                return 0

        except Exception as e:
            logger.exception(f"Failed to broadcast timestamp: {e}")
            return 0


# Global singleton instance
ws_manager = WebSocketManager()
