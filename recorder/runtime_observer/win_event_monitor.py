from __future__ import annotations

import threading
import time
from typing import Any, Callable

from recorder.context import UIContextResolver, dataclass_to_dict as context_dataclass_to_dict
from recorder.filters import WindowFilter
from recorder.ui_resolver import UIElementResolver
from .win32_utils import get_class_name, get_control_text_passively

from .win32_utils import (
    EVENT_OBJECT_FOCUS,
    EVENT_OBJECT_HIDE,
    EVENT_OBJECT_NAMECHANGE,
    EVENT_OBJECT_SHOW,
    EVENT_OBJECT_STATECHANGE,
    EVENT_OBJECT_VALUECHANGE,
    EVENT_SYSTEM_DIALOGEND,
    EVENT_SYSTEM_DIALOGSTART,
    EVENT_SYSTEM_FOREGROUND,
    EVENT_SYSTEM_MENUEND,
    EVENT_SYSTEM_MENUSTART,
    OBJID_WINDOW,
    WINEVENT_OUTOFCONTEXT,
    WINEVENT_SKIPOWNPROCESS,
    WinEventProcType,
    build_window_identity,
    dataclass_to_dict,
    event_name,
    pump_messages_once,
    user32,
)


class WinEventMonitor:
    STATE_CAPTURE_EVENTS = {
        "object_focus",
        "object_statechange",
        "object_valuechange",
    }
    WRAPPER_INSPECTION_EVENTS = {
        "dialog_start",
        "dialog_end",
        "foreground_changed",
        "object_focus",
        "object_statechange",
        "object_valuechange",
    }

    def __init__(
        self,
        emit: Callable[[dict[str, Any]], None],
        window_filter: WindowFilter | None = None,
        poll_interval_seconds: float = 0.05,
        disable_state_capture: bool = False,
    ) -> None:
        self.emit = emit
        self.window_filter = window_filter
        self.poll_interval_seconds = poll_interval_seconds
        self.disable_state_capture = disable_state_capture
        self._lifecycle_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="win-event-monitor")
        self._hooks: list[Any] = []
        self._callbacks: list[Any] = []
        self._state_cache: dict[int, dict[str, Any]] = {}
        self._running = False
        self._started = False
        self._stopped = False

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._started:
                return
            self._running = True
            self._started = True
            self._stopped = False
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            if not self._started or self._stopped:
                return
            self._running = False
            self._stopped = True
            self._stop.set()
            hooks = list(self._hooks)
            self._hooks.clear()

        for hook in hooks:
            try:
                user32.UnhookWinEvent(hook)
            except Exception:
                pass

        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        resolver_context = UIContextResolver()
        ui_resolver = UIElementResolver(resolver_context)
        ranges = [
            (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),
            (EVENT_SYSTEM_MENUSTART, EVENT_SYSTEM_MENUEND),
            (EVENT_SYSTEM_DIALOGSTART, EVENT_SYSTEM_DIALOGEND),
            (EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW),
            (EVENT_OBJECT_HIDE, EVENT_OBJECT_HIDE),
            (EVENT_OBJECT_FOCUS, EVENT_OBJECT_FOCUS),
            (EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_NAMECHANGE),
            (EVENT_OBJECT_VALUECHANGE, EVENT_OBJECT_VALUECHANGE),
            (EVENT_OBJECT_STATECHANGE, EVENT_OBJECT_STATECHANGE),
        ]

        def make_callback() -> Any:
            def _callback(h_win_event_hook, event, hwnd, id_object, id_child, event_thread, event_time):
                if not self._running:
                    return

                resolved_event_name = event_name(int(event))
                raw_hwnd = int(hwnd) if hwnd else None
                root = build_window_identity(raw_hwnd)
                if self.window_filter is not None and not self.window_filter.matches_window(root):
                    return

                element = None
                ui_target = None
                control_state = None
                previous_control_state = None
                control_state_changes = None

                if raw_hwnd:
                    try:
                        element = resolver_context.get_element_info_from_handle(raw_hwnd)
                    except Exception:
                        element = None

                    should_capture_state = (
                        not self.disable_state_capture
                        and resolved_event_name in self.STATE_CAPTURE_EVENTS
                    )
                    if should_capture_state:
                        try:
                            class_name = get_class_name(raw_hwnd)
                            # Selettore passivo per i controlli VB6 "problematici"
                            if class_name and "ThunderRT6" in class_name:
                                passive_text = get_control_text_passively(raw_hwnd)
                                control_state = {"value": passive_text, "extraction_method": "passive_win32"}
                            else:
                                # Fallback al tuo resolver standard per le app non-VB6
                                control_state = resolver_context.capture_state_from_handle(raw_hwnd)
                        except Exception:
                            control_state = None

                    if control_state is not None:
                        previous_control_state = self._state_cache.get(raw_hwnd)
                        control_state_changes = self._diff_state(previous_control_state, control_state)
                        self._state_cache[raw_hwnd] = control_state

                    try:
                        wrapper = None
                        if resolved_event_name in self.WRAPPER_INSPECTION_EVENTS:
                            wrapper = resolver_context.get_wrapper_from_handle(raw_hwnd)
                        ui_target = ui_resolver.build_ui_target(
                            window=None,
                            element=element,
                            state=control_state,
                            wrapper=wrapper,
                            hwnd_hint=raw_hwnd,
                        )
                    except Exception:
                        ui_target = None

                self.emit(
                    {
                        "category": "system",
                        "event_type": resolved_event_name,
                        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time()%1)*1000):03d}Z",
                        "window": dataclass_to_dict(root),
                        "window_title": getattr(root, "title", None) or (ui_target or {}).get("window_title"),
                        "process_name": getattr(root, "process_name", None) or (ui_target or {}).get("process_name"),
                        "hwnd": getattr(root, "handle", None) or (ui_target or {}).get("hwnd"),
                        "ui_target": ui_target,
                        "element": context_dataclass_to_dict(element),
                        "control_state": control_state,
                        "previous_control_state": previous_control_state,
                        "control_state_changes": control_state_changes,
                        "raw": {
                            "hwnd": raw_hwnd,
                            "id_object": int(id_object),
                            "id_child": int(id_child),
                            "event_thread": int(event_thread),
                            "event_time_ms": int(event_time),
                            "is_window_object": int(id_object) == OBJID_WINDOW,
                        },
                    }
                )

            return WinEventProcType(_callback)

        try:
            for event_min, event_max in ranges:
                callback = make_callback()
                hook = user32.SetWinEventHook(
                    event_min,
                    event_max,
                    0,
                    callback,
                    0,
                    0,
                    WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
                )
                if hook:
                    with self._lifecycle_lock:
                        if self._stopped:
                            try:
                                user32.UnhookWinEvent(hook)
                            except Exception:
                                pass
                        else:
                            self._callbacks.append(callback)
                            self._hooks.append(hook)

            while not self._stop.is_set():
                pump_messages_once()
                time.sleep(self.poll_interval_seconds)
        finally:
            with self._lifecycle_lock:
                hooks = list(self._hooks)
                self._hooks.clear()
                self._callbacks.clear()

            for hook in hooks:
                try:
                    user32.UnhookWinEvent(hook)
                except Exception:
                    pass

    def _diff_state(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]] | None:
        if not before or not after:
            return None

        ignored_keys = {"non_empty", "texts_preview"}
        changed: dict[str, dict[str, Any]] = {}
        for key in sorted(set(before) | set(after)):
            if key in ignored_keys:
                continue
            if before.get(key) == after.get(key):
                continue
            changed[key] = {
                "before": before.get(key),
                "after": after.get(key),
            }
        return changed or None
