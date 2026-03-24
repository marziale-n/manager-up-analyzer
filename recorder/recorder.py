from __future__ import annotations

import queue
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from pynput import keyboard, mouse

from recorder.context import UIContextResolver, dataclass_to_dict
from recorder.filters import WindowFilter
from recorder.models import Event
from recorder.semantic_events import SemanticEventBuilder
from recorder.state_manager import StateManager
from recorder.storage import SessionWriter
from recorder.ui_resolver import UIElementResolver
from recorder.utils import new_id, utc_now_iso
from recorder.visual_capture import EventSequence, VisualCaptureManager, VisualCheckpointConfig


class InteractionRecorder:
    def __init__(
        self,
        output_dir: str,
        window_filter: WindowFilter,
        mouse_move_interval_seconds: float = 1,
        session_id: str | None = None,
        external_stop_event: threading.Event | None = None,
        strict_window_filter: bool | None = None,
        enable_state_capture: bool = False,
        visual_checkpoint_config: VisualCheckpointConfig | None = None,
        visual_event_sequence: EventSequence | None = None,
    ) -> None:
        self.session_id = session_id or new_id()
        self.session_dir = Path(output_dir) / self.session_id
        self.window_filter = window_filter
        self.mouse_move_interval_seconds = mouse_move_interval_seconds
        self.external_stop_event = external_stop_event
        self.enable_state_capture = enable_state_capture
        self.visual_checkpoint_config = visual_checkpoint_config or VisualCheckpointConfig()

        self.writer = SessionWriter(self.session_dir)
        self.context = UIContextResolver()
        self.ui_resolver = UIElementResolver(self.context)
        self.state_manager = StateManager(
            ui_automation_value_provider=self._read_uia_value,
            native_value_provider=self._read_native_value,
            debug_logger=self._debug,
        )
        self.semantic_builder = SemanticEventBuilder(self.state_manager)
        self.visual_capture = VisualCaptureManager(
            session_dir=self.session_dir,
            config=self.visual_checkpoint_config,
            event_sequence=visual_event_sequence,
        )
        self.event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._stopped = False

        self.last_mouse_move_ts = 0.0
        self.pressed_modifiers: set[str] = set()
        self.text_buffer = ""

        self.stats = Counter()
        self.started_at = utc_now_iso()
        self.ended_at: str | None = None

        self.debug = True
        self.debug_print_limit = 500
        self.debug_print_count = 0

        self.strict_window_filter = (
            window_filter.has_constraints() if strict_window_filter is None else strict_window_filter
        )
        self.dropped_by_filter = 0
        self.matched_filter_total = 0
        self.recorded_total = 0

    def on_runtime_event(self, payload: dict[str, Any]) -> None:
        self._debug(
            f"runtime_event: type={self._short(payload.get('event_type'))}, "
            f"hwnd={self._short(payload.get('hwnd'))}, "
            f"target={self._short((payload.get('ui_target') or {}).get('control_name'))}"
        )
        self.state_manager.on_runtime_event(payload)

    def _debug(self, message: str) -> None:
        if not self.debug:
            return
        if self.debug_print_count >= self.debug_print_limit:
            return
        self.debug_print_count += 1
        print(f"[DEBUG] {message}")

    def _short(self, value: Any, max_len: int = 120) -> str:
        text = repr(value)
        if len(text) > max_len:
            return text[:max_len] + "...<truncated>"
        return text

    def start(self) -> None:
        print(f"[DEBUG] recorder file: {__file__}")

        self.writer.write_session_metadata(
            {
                "session_id": self.session_id,
                "started_at_utc": self.started_at,
                "window_filter": self.window_filter.to_metadata(),
                "strict_window_filter": self.strict_window_filter,
                "visual_checkpoints": self.visual_checkpoint_config.to_metadata(),
                "notes": "MVP with optional visual fallback checkpoints",
            }
        )

        self._debug(
            f"Starting recorder with filter: "
            f"title_contains={self.window_filter.title_contains!r}, "
            f"title_regex={self.window_filter.title_regex!r}, "
            f"strict_window_filter={self.strict_window_filter!r}, "
            f"session_id={self.session_id!r}"
        )

        self.worker_thread.start()

        self.mouse_listener = mouse.Listener(
            on_move=self.on_move,
            on_click=self.on_click,
            on_scroll=self.on_scroll,
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release,
        )

        self.mouse_listener.start()
        self.keyboard_listener.start()
        while not self.stop_event.is_set():
            if self.external_stop_event is not None and self.external_stop_event.is_set():
                self._debug("External stop event received")
                break
            if not self.keyboard_listener.is_alive():
                break
            time.sleep(0.1)
        self.stop()

    def stop(self) -> None:
        if self._stopped:
            return

        self._stopped = True
        self.stop_event.set()
        try:
            self.mouse_listener.stop()
        except Exception:
            pass
        try:
            self.keyboard_listener.stop()
        except Exception:
            pass

        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
        self.ended_at = utc_now_iso()
        self.writer.write_summary(
            {
                "session_id": self.session_id,
                "started_at_utc": self.started_at,
                "ended_at_utc": self.ended_at,
                "stats": dict(self.stats),
                "output_dir": str(self.session_dir),
                "recorded_total": self.recorded_total,
                "matched_filter_total": self.matched_filter_total,
                "dropped_by_filter": self.dropped_by_filter,
            }
        )

    def on_move(self, x: int, y: int) -> None:
        now = time.time()
        if now - self.last_mouse_move_ts < self.mouse_move_interval_seconds:
            return
        self.last_mouse_move_ts = now
        self.event_queue.put(self._build_raw_mouse_event("mouse_move", x=x, y=y))

    def on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        event = self._build_raw_mouse_event(
            "mouse_click",
            x=x,
            y=y,
            button=str(button),
            pressed=pressed,
            click_count=None,
        )
        self.event_queue.put(event)

    def on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        event = self._build_raw_mouse_event(
            "mouse_scroll",
            x=x,
            y=y,
            dx=dx,
            dy=dy,
        )
        self.event_queue.put(event)

    def on_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        try:
            self.event_queue.put(
                self._build_raw_key_event("key_down", self._serialize_key(key))
            )
        except Exception as e:
            self._debug(f"on_press failed: key={self._short(key)} error={e}")

    def on_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> bool | None:
        key_name = self._serialize_key(key)
        try:
            self.event_queue.put(self._build_raw_key_event("key_up", key_name))
        except Exception as e:
            self._debug(f"on_release failed: key={self._short(key)} error={e}")

        if key == keyboard.Key.esc:
            self.stop_event.set()
            return False
        return None

    def _build_raw_mouse_event(self, kind: str, **kwargs: Any) -> dict[str, Any]:
        x = kwargs.get("x")
        y = kwargs.get("y")

        window = None
        target_element = None
        target_state = None
        ui_target = None
        focused_snapshot = None

        if x is not None and y is not None:
            try:
                window = self.context.get_window_info_from_point(int(x), int(y))
            except Exception as e:
                self._debug(f"{kind}: get_window_info_from_point failed at ({x},{y}): {e}")

            try:
                target_element = self.context.get_element_from_point(int(x), int(y))
            except Exception as e:
                self._debug(f"{kind}: get_element_from_point failed at ({x},{y}): {e}")

            if self.enable_state_capture or kind in {"mouse_click", "mouse_scroll"}:
                try:
                    target_state = self.context.capture_state_for_element(
                        element=target_element,
                        point=(int(x), int(y)),
                    )
                except Exception as e:
                    self._debug(f"{kind}: capture_state_for_element failed at ({x},{y}): {e}")

            try:
                point_wrapper = self.context.get_wrapper_from_point(int(x), int(y))
                ui_target = self.ui_resolver.build_ui_target(
                    window=window,
                    element=target_element,
                    state=target_state,
                    wrapper=point_wrapper,
                    point=(int(x), int(y)),
                )
            except Exception as e:
                self._debug(f"{kind}: ui target resolution failed at ({x},{y}): {e}")

        if window is None:
            try:
                window = self.context.get_active_window_info()
            except Exception as e:
                self._debug(f"{kind}: get_active_window_info fallback failed: {e}")

        if kind == "mouse_click":
            try:
                focused_snapshot = self.ui_resolver.resolve_focus_snapshot()
            except Exception as e:
                self._debug(f"{kind}: focused snapshot resolution failed: {e}")

        self._debug(
            f"{kind}: "
            f"window_title={self._short(getattr(window, 'title', None))}, "
            f"process={self._short(getattr(window, 'process_name', None))}, "
            f"x={x}, y={y}, "
            f"target_name={self._short(getattr(target_element, 'name', None))}, "
            f"target_type={self._short(getattr(target_element, 'control_type', None))}"
        )

        return {
            "kind": kind,
            **kwargs,
            "window": window,
            "target_element": target_element,
            "target_state": target_state,
            "ui_target": ui_target,
            "focused_snapshot": focused_snapshot,
        }

    def _build_raw_key_event(self, kind: str, key_name: str) -> dict[str, Any]:
        window = None
        target_element = None
        target_state = None
        ui_target = None

        try:
            focus_snapshot = self.ui_resolver.resolve_focus_snapshot()
            window = focus_snapshot.get("window")
            target_element = focus_snapshot.get("element")
            target_state = focus_snapshot.get("state")
            ui_target = focus_snapshot.get("ui_target")
        except Exception as e:
            self._debug(f"{kind}: resolve_focus_snapshot failed: {e}")

        if window is None:
            try:
                window = self.context.get_active_window_info()
            except Exception as e:
                self._debug(f"{kind}: get_active_window_info failed: {e}")

        if target_element is None:
            try:
                target_element, target_state = self.context.capture_focused_element_state()
            except Exception as e:
                self._debug(f"{kind}: capture_focused_element_state fallback failed for key={key_name!r}: {e}")

        self._debug(
            f"{kind}: "
            f"key={self._short(key_name)}, "
            f"window_title={self._short(getattr(window, 'title', None))}, "
            f"process={self._short(getattr(window, 'process_name', None))}, "
            f"focused_name={self._short(getattr(target_element, 'name', None))}, "
            f"focused_type={self._short(getattr(target_element, 'control_type', None))}"
        )

        return {
            "kind": kind,
            "key": key_name,
            "window": window,
            "target_element": target_element,
            "target_state": target_state,
            "ui_target": ui_target,
        }

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set() or not self.event_queue.empty():
            try:
                item = self.event_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            self._handle_raw_event(item)
            self.event_queue.task_done()

        self._flush_pending_semantic_events()

    def _handle_raw_event(self, raw: dict[str, Any]) -> None:
        kind = raw["kind"]
        window = raw.get("window")
        target_element = raw.get("target_element")
        target_state = raw.get("target_state")
        ui_target = raw.get("ui_target")

        window_title = getattr(window, "title", None)
        process_name = getattr(window, "process_name", None)
        target_name = (ui_target or {}).get("control_name") or getattr(target_element, "name", None)
        target_type = (ui_target or {}).get("control_type") or getattr(target_element, "control_type", None)

        matches_window_filter = self.window_filter.matches(window, target_element)

        if matches_window_filter:
            self.matched_filter_total += 1

        self._debug(
            f"handle_raw_event: kind={kind}, "
            f"window_title={self._short(window_title)}, "
            f"process={self._short(process_name)}, "
            f"matches_window_filter={matches_window_filter}"
        )

        if self.strict_window_filter and not matches_window_filter:
            self.dropped_by_filter += 1
            self._debug(
                f"DROPPED: kind={kind}, "
                f"window_title={self._short(window_title)}, "
                f"filter_contains={self.window_filter.title_contains!r}, "
                f"filter_regex={self.window_filter.title_regex!r}"
            )
            return

        payload: dict[str, Any] = {
            **{
                k: v
                for k, v in raw.items()
                if k not in {"kind", "window", "target_element", "target_state", "focused_snapshot", "ui_target"}
            },
            "window": dataclass_to_dict(window),
            "target_element": dataclass_to_dict(target_element),
            "target_state": target_state,
            "window_title": window_title or (ui_target or {}).get("window_title"),
            "process_name": process_name or (ui_target or {}).get("process_name"),
            "hwnd": getattr(window, "handle", None) or (ui_target or {}).get("hwnd"),
            "ui_target": ui_target
            or self.ui_resolver.build_ui_target(
                window=window,
                element=target_element,
                state=target_state,
                hwnd_hint=getattr(window, "handle", None),
            ),
            "keyboard_state": {
                "modifiers": sorted(self.pressed_modifiers),
            },
            "matches_window_filter": matches_window_filter,
            "target_name": target_name,
            "target_type": target_type,
        }

        if kind in {"key_down", "key_up"}:
            self._update_modifier_state(kind, payload.get("key"))
            typed_text = self._update_text_buffer(kind, payload.get("key"))
            if typed_text is not None:
                payload["text_buffer"] = typed_text

        post_focus_snapshot = self._capture_post_focus_snapshot(raw)
        payload.update(self._build_focus_transition_payload(post_focus_snapshot))

        if self.enable_state_capture:
            payload.update(self._capture_post_event_artifacts(raw, post_focus_snapshot))

        raw_event = Event(
            event_id=new_id(),
            session_id=self.session_id,
            timestamp_utc=utc_now_iso(),
            event_type=kind,
            payload=payload,
        )
        self._attach_visual_checkpoint(raw_event)

        self.writer.append_event(raw_event)
        self.stats[kind] += 1
        self.recorded_total += 1

        pre_focus_snapshot = self._build_pre_focus_snapshot(raw, payload)
        semantic_payloads = self.semantic_builder.process_event(
            event_type=kind,
            timestamp_utc=raw_event.timestamp_utc,
            key_name=payload.get("key"),
            pressed=payload.get("pressed"),
            pre_snapshot=pre_focus_snapshot,
            post_snapshot=post_focus_snapshot or pre_focus_snapshot,
            target_snapshot=self._build_target_snapshot(raw, payload),
            is_editable=self.ui_resolver.is_editable_target,
        )
        self._append_semantic_events(semantic_payloads, timestamp_utc=raw_event.timestamp_utc)

        self._debug(
            f"RECORDED: kind={kind}, "
            f"target_name={self._short(target_name)}, "
            f"target_type={self._short(target_type)}, "
            f"stats={dict(self.stats)}"
        )

    def _capture_post_event_artifacts(
        self,
        raw: dict[str, Any],
        post_focus_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        kind = raw.get("kind")

        should_capture_post_state = (
            (kind == "mouse_click" and raw.get("pressed") is False)
            or kind == "key_up"
        )
        if not should_capture_post_state:
            return {}

        delay_seconds = 0.05 if kind == "mouse_click" else 0.02
        time.sleep(delay_seconds)

        artifacts: dict[str, Any] = {}
        target_element = raw.get("target_element")
        target_state = raw.get("target_state")

        post_target_state = None
        try:
            post_target_state = self.context.capture_state_for_element(element=target_element)
        except Exception as e:
            self._debug(f"{kind}: post target state capture failed: {e}")

        if post_target_state is not None:
            artifacts["post_target_state"] = post_target_state
            diff = self._diff_state_snapshots(target_state, post_target_state)
            if diff:
                artifacts["target_state_changes"] = diff

        try:
            post_focused_element = (post_focus_snapshot or {}).get("element")
            post_focused_state = (post_focus_snapshot or {}).get("state")
        except Exception:
            post_focused_element, post_focused_state = None, None

        if post_focused_element is not None:
            artifacts["post_focused_element"] = dataclass_to_dict(post_focused_element)
        if post_focused_state is not None:
            artifacts["post_focused_state"] = post_focused_state
            diff = self._diff_state_snapshots(target_state, post_focused_state)
            if diff:
                artifacts["focused_state_changes"] = diff

        return artifacts

    def _capture_post_focus_snapshot(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        kind = raw.get("kind")
        should_capture = (
            (kind == "mouse_click" and raw.get("pressed") is False)
            or kind == "key_up"
        )
        if not should_capture:
            return None

        delay_seconds = 0.05 if kind == "mouse_click" else 0.02
        time.sleep(delay_seconds)

        try:
            return self.ui_resolver.resolve_focus_snapshot()
        except Exception as e:
            self._debug(f"{kind}: post focus snapshot failed: {e}")
            return None

    def _build_pre_focus_snapshot(
        self,
        raw: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if raw.get("kind") == "mouse_click":
            return raw.get("focused_snapshot")

        if raw.get("kind") in {"key_down", "key_up"}:
            return {
                "window": raw.get("window"),
                "element": raw.get("target_element"),
                "state": raw.get("target_state"),
                "ui_target": payload.get("ui_target"),
                "window_title": payload.get("window_title"),
                "process_name": payload.get("process_name"),
                "hwnd": payload.get("hwnd"),
                "value": self.ui_resolver.extract_text_value(
                    state=raw.get("target_state"),
                    element=raw.get("target_element"),
                ),
            }

        return None

    def _build_focus_transition_payload(
        self,
        post_focus_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not post_focus_snapshot:
            return {}
        return {
            "post_window_title": post_focus_snapshot.get("window_title"),
            "post_process_name": post_focus_snapshot.get("process_name"),
            "post_hwnd": post_focus_snapshot.get("hwnd"),
            "post_ui_target": post_focus_snapshot.get("ui_target"),
            "post_focused_element": post_focus_snapshot.get("element_dict"),
            "post_focused_state": post_focus_snapshot.get("state"),
        }

    def _build_target_snapshot(
        self,
        raw: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        ui_target = payload.get("ui_target")
        if ui_target is None and raw.get("target_element") is None and raw.get("target_state") is None:
            return None
        return {
            "window_title": payload.get("window_title"),
            "process_name": payload.get("process_name"),
            "hwnd": payload.get("hwnd"),
            "ui_target": ui_target,
            "element": raw.get("target_element"),
            "state": raw.get("target_state"),
            "value": self.ui_resolver.extract_text_value(
                state=raw.get("target_state"),
                element=raw.get("target_element"),
            ),
        }

    def _append_semantic_events(
        self,
        semantic_payloads: list[dict[str, Any]],
        *,
        timestamp_utc: str,
    ) -> None:
        for payload in semantic_payloads:
            event = Event(
                event_id=new_id(),
                session_id=self.session_id,
                timestamp_utc=timestamp_utc,
                event_type="input_commit",
                payload=payload,
            )
            self._attach_visual_checkpoint(event)
            self.writer.append_event(event)
            self.stats["input_commit"] += 1
            self.recorded_total += 1

    def _attach_visual_checkpoint(self, event: Event) -> None:
        if event.event_type == "input_commit":
            should_capture = self.visual_capture.should_capture_semantic(event.event_type)
        else:
            should_capture = self.visual_capture.should_capture_raw(event.event_type, event.payload)
        if not should_capture:
            return

        payload = self.visual_capture.capture_for_event(
            event_type=event.event_type,
            timestamp_utc=event.timestamp_utc,
            ui_target=event.payload.get("ui_target"),
            window_info=event.payload.get("window"),
            hwnd=event.payload.get("hwnd"),
            window_title=event.payload.get("window_title"),
            process_name=event.payload.get("process_name"),
            capture_stage="after",
            metadata={"session_id": event.session_id},
        )
        if payload is not None:
            event.payload["visual_checkpoint"] = payload

    def _read_uia_value(self, control: dict[str, Any]) -> str | None:
        state = control.get("state")
        element = control.get("element")
        payload_value = self.ui_resolver.extract_text_value(state=state, element=element)
        if payload_value is not None:
            return payload_value
        hwnd = (control.get("ui_target") or {}).get("handle") or control.get("hwnd")
        return self.context.read_uia_text(hwnd)

    def _read_native_value(self, control: dict[str, Any]) -> str | None:
        hwnd = (control.get("ui_target") or {}).get("handle") or control.get("hwnd")
        return self.context.read_native_text(hwnd)

    def _flush_pending_semantic_events(self) -> None:
        try:
            focus_snapshot = self.ui_resolver.resolve_focus_snapshot()
        except Exception:
            focus_snapshot = None

        timestamp_utc = utc_now_iso()
        semantic_payloads = self.semantic_builder.flush(
            timestamp_utc=timestamp_utc,
            snapshot=focus_snapshot,
            is_editable=self.ui_resolver.is_editable_target,
        )
        self._append_semantic_events(semantic_payloads, timestamp_utc=timestamp_utc)

    def _diff_state_snapshots(
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

    def _serialize_key(self, key: keyboard.Key | keyboard.KeyCode | None) -> str:
        if key is None:
            return "unknown"
        try:
            if hasattr(key, "char") and key.char is not None:
                return key.char
        except Exception:
            pass
        return str(key)

    def _update_modifier_state(self, kind: str, key_name: str | None) -> None:
        if not key_name:
            return

        modifier_aliases = {
            "Key.ctrl": "ctrl",
            "Key.ctrl_l": "ctrl",
            "Key.ctrl_r": "ctrl",
            "Key.alt": "alt",
            "Key.alt_l": "alt",
            "Key.alt_r": "alt",
            "Key.shift": "shift",
            "Key.shift_l": "shift",
            "Key.shift_r": "shift",
            "Key.cmd": "cmd",
        }
        normalized = modifier_aliases.get(key_name)
        if not normalized:
            return

        if kind == "key_down":
            self.pressed_modifiers.add(normalized)
        elif kind == "key_up":
            self.pressed_modifiers.discard(normalized)

    def _update_text_buffer(self, kind: str, key_name: str | None) -> str | None:
        if kind != "key_down" or not key_name:
            return None

        special_to_text = {
            "Key.space": " ",
            "Key.enter": "\n",
            "Key.tab": "\t",
        }

        if len(key_name) == 1:
            self.text_buffer += key_name
            return self.text_buffer[-200:]

        if key_name == "Key.backspace":
            self.text_buffer = self.text_buffer[:-1]
            return self.text_buffer[-200:]

        mapped = special_to_text.get(key_name)
        if mapped is not None:
            self.text_buffer += mapped
            return self.text_buffer[-200:]

        return None
