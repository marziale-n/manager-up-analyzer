import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

import json
import orjson

from recorder.models import Event


class SessionWriter:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.session_dir / "events.jsonl"
        self.events_path.touch(exist_ok=True)
        self.session_path = self.session_dir / "session.json"
        self.summary_path = self.session_dir / "summary.json"
        self._lock = threading.Lock()

    def write_session_metadata(self, metadata: dict[str, Any]) -> None:
        with self._lock:
            self.session_path.write_bytes(orjson.dumps(metadata, option=orjson.OPT_INDENT_2))

    def append_event(self, event: Event) -> None:
        with self._lock:
            with self.events_path.open("ab") as f:
                f.write(orjson.dumps(asdict(event)))
                f.write(b"\n")

    def write_event(self, payload: dict[str, Any]) -> None:
        with self._lock:
            with self.events_path.open("ab") as f:
                f.write(orjson.dumps(payload))
                f.write(b"\n")

    def write_summary(self, summary: dict[str, Any]) -> None:
        with self._lock:
            self.summary_path.write_bytes(orjson.dumps(summary, option=orjson.OPT_INDENT_2))
