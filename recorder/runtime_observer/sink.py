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
        self._closed = False

    def write(self, payload: dict[str, Any]) -> None:
        with self._lock:
            if self._closed or self._output_file_handle.closed:
                return
            try:
                self._output_file_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._output_file_handle.flush()
            except ValueError:
                self._closed = True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if not self._output_file_handle.closed:
                    self._output_file_handle.flush()
            finally:
                if not self._output_file_handle.closed:
                    self._output_file_handle.close()
