from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from recorder.filters import WindowFilter
from recorder.visual_capture import EventSequence, VisualCaptureManager, VisualCheckpointConfig

from .busy_monitor import BusyMonitor
from .sink import JsonlEventSink
from .win_event_monitor import WinEventMonitor


class RuntimeObserverManager:
    def __init__(
        self,
        output_dir: str,
        session_id: str | None = None,
        window_filter: WindowFilter | None = None,
        target_window_regex: str | None = None,
        cpu_threshold: float = 8.0,
        enable_state_capture: bool = False,
        visual_checkpoint_config: VisualCheckpointConfig | None = None,
        visual_event_sequence: EventSequence | None = None,
        event_listeners: list[Callable[[dict[str, Any]], None]] | None = None,
    ) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.session_dir = Path(output_dir) / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.timeline_file = self.session_dir / "runtime_timeline.jsonl"
        self.metadata_file = self.session_dir / "runtime_metadata.json"
        self.sink = JsonlEventSink(self.timeline_file)
        self.window_filter = window_filter or WindowFilter(title_regex=target_window_regex)
        self.cpu_threshold = cpu_threshold
        self.enable_state_capture = enable_state_capture
        self.visual_checkpoint_config = visual_checkpoint_config or VisualCheckpointConfig()
        self.visual_capture = VisualCaptureManager(
            session_dir=self.session_dir,
            config=self.visual_checkpoint_config,
            event_sequence=visual_event_sequence,
        )
        self.event_listeners = list(event_listeners or [])
        self.started_at_utc = self._utc_now()
        self._state_lock = threading.RLock()
        self._started = False
        self._stopping = False
        self._stopped = False

        self.monitors = [
            WinEventMonitor(
                self.emit,
                window_filter=self.window_filter,
                enable_state_capture=self.enable_state_capture,
            ),
            BusyMonitor(self.emit, window_filter=self.window_filter, cpu_threshold=cpu_threshold),
        ]

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def write_metadata(self) -> None:
        self.metadata_file.write_text(
            __import__("json").dumps(
                {
                    "session_id": self.session_id,
                    "started_at_utc": self.started_at_utc,
                    "window_filter": self.window_filter.to_metadata(),
                    "cpu_threshold": self.cpu_threshold,
                    "enable_state_capture": self.enable_state_capture,
                    "visual_checkpoints": self.visual_checkpoint_config.to_metadata(),
                    "timeline_file": str(self.timeline_file),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def emit(self, payload: dict[str, Any]) -> None:
        with self._state_lock:
            if not self._started or self._stopping or self._stopped:
                return
            payload.setdefault("session_id", self.session_id)
            if self.visual_capture.should_capture_runtime(payload):
                checkpoint = self.visual_capture.capture_for_event(
                    event_type=str(payload.get("event_type") or "runtime_event"),
                    timestamp_utc=payload.get("timestamp_utc"),
                    ui_target=payload.get("ui_target"),
                    window_info=payload.get("window"),
                    hwnd=payload.get("hwnd"),
                    window_title=payload.get("window_title"),
                    process_name=payload.get("process_name"),
                    capture_stage="after",
                    metadata={"channel": payload.get("category")},
                )
                if checkpoint is not None:
                    payload["visual_checkpoint"] = checkpoint
            self.sink.write(payload)
        for listener in self.event_listeners:
            try:
                listener(dict(payload))
            except Exception:
                pass

    def start(self) -> None:
        with self._state_lock:
            if self._started and not self._stopped:
                return
            self.write_metadata()
            self._started = True
            self._stopping = False
            self._stopped = False
        for monitor in self.monitors:
            monitor.start()

    def stop(self) -> None:
        with self._state_lock:
            if not self._started or self._stopped:
                return
            if self._stopping:
                return
            self._stopping = True
        for monitor in reversed(self.monitors):
            try:
                monitor.stop()
            except Exception:
                pass
        with self._state_lock:
            self.sink.close()
            self._stopped = True
