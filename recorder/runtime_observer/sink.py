from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class JsonlEventSink:
    def __init__(self, output_file: Path) -> None:
        self.output_file = output_file
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._output_file_handle = self.output_file.open("a", encoding="utf-8")

    def write(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._output_file_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._output_file_handle.flush()

    def close(self) -> None:
        with self._lock:
            try:
                self._output_file_handle.flush()
            finally:
                self._output_file_handle.close()
