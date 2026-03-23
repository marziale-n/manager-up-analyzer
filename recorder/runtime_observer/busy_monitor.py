from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

import psutil

from recorder.filters import WindowFilter
from recorder.window_selector import list_open_windows

from .win32_utils import WindowIdentity, build_window_identity, dataclass_to_dict, get_foreground_hwnd, wait_for_input_idle


@dataclass(slots=True)
class BusyState:
    pid: int
    process_name: str | None
    window_title: str | None
    cpu_percent: float
    status: str


class BusyMonitor:
    def __init__(
        self,
        emit: Callable[[dict[str, Any]], None],
        window_filter: WindowFilter | None = None,
        cpu_threshold: float = 8.0,
        poll_interval_seconds: float = 0.35,
        settle_intervals: int = 3,
    ) -> None:
        self.emit = emit
        self.window_filter = window_filter
        self.cpu_threshold = cpu_threshold
        self.poll_interval_seconds = poll_interval_seconds
        self.settle_intervals = settle_intervals
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="busy-monitor")
        self._proc_cache: dict[int, psutil.Process] = {}
        self._busy: dict[int, int] = {}
        self._idle: dict[int, int] = {}

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _iter_candidate_windows(self) -> list[tuple[int, Any]]:
        if self.window_filter is not None and self.window_filter.pid is not None:
            identity = build_window_identity(self.window_filter.hwnd)
            if identity is not None and identity.pid == self.window_filter.pid:
                return [(identity.pid, identity)]

            process_name, process_path = None, None
            try:
                process = psutil.Process(self.window_filter.pid)
                process_name = process.name()
                process_path = process.exe()
            except Exception:
                pass

            return [
                (
                    self.window_filter.pid,
                    WindowIdentity(
                        title=None,
                        class_name=None,
                        handle=self.window_filter.hwnd,
                        pid=self.window_filter.pid,
                        process_name=process_name,
                        process_path=process_path,
                        visible=None,
                    ),
                )
            ]

        if self.window_filter is not None:
            results: list[tuple[int, Any]] = []
            seen_pids: set[int] = set()
            for item in list_open_windows():
                identity = build_window_identity(item.hwnd)
                if identity is None or identity.pid is None:
                    continue
                if not self.window_filter.matches_window(identity):
                    continue
                if identity.pid in seen_pids:
                    continue
                seen_pids.add(identity.pid)
                results.append((identity.pid, identity))
            if results:
                return results

        foreground_hwnd = get_foreground_hwnd()
        if not foreground_hwnd:
            return []
        identity = build_window_identity(foreground_hwnd)
        if identity is None or identity.pid is None:
            return []
        if self.window_filter is not None and not self.window_filter.matches_window(identity):
            return []
        return [(identity.pid, identity)]

    def _get_process(self, pid: int) -> psutil.Process | None:
        proc = self._proc_cache.get(pid)
        if proc is not None:
            return proc
        try:
            proc = psutil.Process(pid)
            proc.cpu_percent(interval=None)
            self._proc_cache[pid] = proc
            return proc
        except Exception:
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            for pid, identity in self._iter_candidate_windows():
                proc = self._get_process(pid)
                if proc is None:
                    continue
                try:
                    cpu = float(proc.cpu_percent(interval=None))
                except Exception:
                    continue

                idle_state = wait_for_input_idle(pid, timeout_ms=10)
                title = identity.title or None
                process_name = identity.process_name or None

                if cpu >= self.cpu_threshold:
                    self._busy[pid] = self._busy.get(pid, 0) + 1
                    self._idle[pid] = 0
                    if self._busy[pid] == 1:
                        self.emit(
                            {
                                "category": "process",
                                "event_type": "processing_started",
                                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time()%1)*1000):03d}Z",
                                "window": dataclass_to_dict(identity),
                                "process": asdict(BusyState(pid, process_name, title, cpu, idle_state or "unknown")),
                            }
                        )
                    else:
                        self.emit(
                            {
                                "category": "process",
                                "event_type": "cpu_sample",
                                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time()%1)*1000):03d}Z",
                                "window": dataclass_to_dict(identity),
                                "process": asdict(BusyState(pid, process_name, title, cpu, idle_state or "unknown")),
                            }
                        )
                else:
                    if self._busy.get(pid, 0) > 0:
                        self._idle[pid] = self._idle.get(pid, 0) + 1
                        if self._idle[pid] >= self.settle_intervals:
                            self.emit(
                                {
                                    "category": "process",
                                    "event_type": "processing_finished",
                                    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time()%1)*1000):03d}Z",
                                    "window": dataclass_to_dict(identity),
                                    "process": asdict(BusyState(pid, process_name, title, cpu, idle_state or "unknown")),
                                }
                            )
                            self._busy[pid] = 0
                            self._idle[pid] = 0
            time.sleep(self.poll_interval_seconds)
