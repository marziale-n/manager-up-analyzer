from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Event:
    event_id: str
    session_id: str
    timestamp_utc: str
    event_type: str
    payload: dict[str, Any]
