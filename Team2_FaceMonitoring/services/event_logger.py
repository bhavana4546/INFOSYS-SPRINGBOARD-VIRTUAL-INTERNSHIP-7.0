"""Thread-safe in-memory event history for the dashboard."""

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from config import MAX_RECENT_EVENTS


class EventLogger:
    """Keep the newest events in memory without writing camera data to disk."""

    def __init__(self, max_events: int = MAX_RECENT_EVENTS) -> None:
        if max_events < 1:
            raise ValueError("max_events must be greater than zero")
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = Lock()

    def add_event(self, event_type: str, message: str) -> dict[str, Any]:
        event = {
            "type": event_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with self._lock:
            self._events.appendleft(event)
        return event

    def get_recent_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)
