from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable


ControlDict = dict[str, Any]
ValueProvider = Callable[[ControlDict], Any]
Logger = Callable[[str], None]


@dataclass(slots=True)
class ControlMetadataSnapshot:
    ui_target: dict[str, Any]
    window_title: str | None
    process_name: str | None
    hwnd: int | None
    state: dict[str, Any] | None
    element: Any | None
    value: str | None


@dataclass(slots=True)
class ControlState:
    control_key: str
    metadata: ControlMetadataSnapshot
    current_value: str | None = None
    previous_committed_value: str | None = None
    edit_start_value: str | None = None
    typed_buffer: str | None = None
    is_focused: bool = False
    edit_session_active: bool = False
    focus_start: str | None = None
    last_update: str | None = None
    last_commit: str | None = None
    runtime_cached_value: str | None = None
    runtime_last_update: str | None = None
    last_value_source: str | None = None
    last_commit_signature: str | None = None
    last_commit_reason: str | None = None
    last_commit_value: str | None = None
    last_commit_timestamp: str | None = None
    latest_snapshot: dict[str, Any] | None = None


class StateManager:
    """Single source of truth for control state, edit lifecycles, and value resolution."""

    EDITABLE_TYPES = {
        "combobox",
        "custom",
        "datepicker",
        "document",
        "edit",
        "pane",
        "spinner",
    }
    EDITABLE_CLASSES = {
        "combobox",
        "datepick",
        "edit",
        "maskedit",
        "richedit",
        "richedit20w",
        "richedit50w",
        "thundertextbox",
    }
    NON_EDITABLE_TYPES = {
        "button",
        "checkbox",
        "group",
        "image",
        "list",
        "listitem",
        "menu",
        "menubar",
        "menuitem",
        "panecontainer",
        "progressbar",
        "radio",
        "scrollbar",
        "separator",
        "slider",
        "static",
        "statusbar",
        "tab",
        "table",
        "text",
        "toolbar",
        "tree",
        "treeitem",
        "window",
    }

    def __init__(
        self,
        *,
        ui_automation_value_provider: ValueProvider | None = None,
        native_value_provider: ValueProvider | None = None,
        debug_logger: Logger | None = None,
        duplicate_suppression_window_seconds: float = 0.75,
    ) -> None:
        self.ui_automation_value_provider = ui_automation_value_provider
        self.native_value_provider = native_value_provider
        self.debug_logger = debug_logger
        self.duplicate_suppression_window_seconds = duplicate_suppression_window_seconds
        self._states: dict[str, ControlState] = {}
        self._active_control_key: str | None = None
        self._lock = RLock()

    def register_event(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        timestamp_utc = event.get("timestamp_utc")
        event_type = event.get("event_type")
        key_name = event.get("key_name")
        pre_snapshot = self._normalize_control(event.get("pre_snapshot"))
        post_snapshot = self._normalize_control(event.get("post_snapshot"))
        commits: list[dict[str, Any]] = []

        with self._lock:
            pre_key = self._control_key_if_editable(pre_snapshot)
            post_key = self._control_key_if_editable(post_snapshot)

            if event_type in {"key_down", "key_up"} and pre_snapshot is not None and pre_key is not None:
                self.on_focus_gained(pre_snapshot, timestamp_utc=timestamp_utc)
                self.on_key_event(
                    pre_snapshot,
                    {
                        "event_type": event_type,
                        "key_name": key_name,
                        "timestamp_utc": timestamp_utc,
                    },
                )

            if event_type == "key_up" and key_name == "Key.enter":
                commit = self.resolve_commit(
                    pre_snapshot or post_snapshot,
                    reason="enter",
                    timestamp_utc=timestamp_utc,
                    source_event_type=event_type,
                    source_key=key_name,
                )
                if commit is not None:
                    commits.append(commit)
                if post_snapshot is not None and post_key is not None:
                    self.on_focus_gained(post_snapshot, timestamp_utc=timestamp_utc)
                return commits

            if pre_key is not None and pre_key != post_key:
                commit = self.on_focus_lost(
                    pre_snapshot,
                    timestamp_utc=timestamp_utc,
                    reason="focus_lost",
                    source_event_type=event_type,
                    source_key=key_name,
                )
                if commit is not None:
                    commits.append(commit)

            if post_snapshot is not None and post_key is not None:
                self.on_focus_gained(post_snapshot, timestamp_utc=timestamp_utc)

            return commits

    def on_focus_gained(
        self,
        control: dict[str, Any] | None,
        *,
        timestamp_utc: str | None = None,
    ) -> ControlState | None:
        normalized = self._normalize_control(control)
        if normalized is None or not self.is_editable_control(normalized):
            return None

        with self._lock:
            control_key = self._build_control_key(normalized)
            if control_key is None:
                return None

            if self._active_control_key and self._active_control_key != control_key:
                active = self._states.get(self._active_control_key)
                if active is not None:
                    active.is_focused = False

            state = self._get_or_create_state(control_key, normalized, timestamp_utc=timestamp_utc)
            self._update_state_from_control(state, normalized, timestamp_utc=timestamp_utc)
            state.is_focused = True
            self._active_control_key = control_key

            if not state.edit_session_active:
                initial_value = state.current_value
                state.edit_session_active = True
                state.edit_start_value = initial_value
                state.typed_buffer = None
                state.focus_start = timestamp_utc or state.focus_start
                self._debug(f"focus_gained control={control_key} start={initial_value!r}")

            return state

    def on_focus_lost(
        self,
        control: dict[str, Any] | None,
        *,
        timestamp_utc: str | None = None,
        reason: str = "focus_lost",
        source_event_type: str | None = None,
        source_key: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            commit = self.resolve_commit(
                control,
                reason=reason,
                timestamp_utc=timestamp_utc,
                source_event_type=source_event_type,
                source_key=source_key,
            )
            normalized = self._normalize_control(control)
            control_key = self._build_control_key(normalized) if normalized is not None else self._active_control_key
            if control_key is not None:
                state = self._states.get(control_key)
                if state is not None:
                    state.is_focused = False
            if self._active_control_key == control_key:
                self._active_control_key = None
            return commit

    def on_key_event(
        self,
        control: dict[str, Any] | None,
        key_event: dict[str, Any],
    ) -> ControlState | None:
        normalized = self._normalize_control(control)
        if normalized is None or not self.is_editable_control(normalized):
            return None

        with self._lock:
            control_key = self._build_control_key(normalized)
            if control_key is None:
                return None

            state = self._get_or_create_state(control_key, normalized, timestamp_utc=key_event.get("timestamp_utc"))
            self._update_state_from_control(state, normalized, timestamp_utc=key_event.get("timestamp_utc"))
            key_name = key_event.get("key_name")
            event_type = key_event.get("event_type")

            if event_type == "key_down":
                state.typed_buffer = self._apply_key_to_buffer(state.typed_buffer, key_name)
                if state.typed_buffer is not None:
                    self._debug(f"typed control={control_key} buffer={state.typed_buffer!r}")
            return state

    def on_runtime_event(self, runtime_event: dict[str, Any]) -> ControlState | None:
        normalized = self._control_from_runtime_event(runtime_event)
        if normalized is None:
            return None

        with self._lock:
            control_key = self._build_control_key(normalized)
            if control_key is None:
                return None

            state = self._get_or_create_state(control_key, normalized, timestamp_utc=runtime_event.get("timestamp_utc"))
            self._update_state_from_control(state, normalized, timestamp_utc=runtime_event.get("timestamp_utc"))

            runtime_value = self._extract_runtime_value(runtime_event, normalized)
            if runtime_value is not None:
                state.runtime_cached_value = runtime_value
                state.current_value = runtime_value
                state.runtime_last_update = runtime_event.get("timestamp_utc")
                state.last_value_source = "runtime_observer"
                self._debug(f"runtime_update control={control_key} value={runtime_value!r}")

            event_name = (runtime_event.get("event_type") or "").lower()
            if event_name in {"event_object_focus", "focus"} and self.is_editable_control(normalized):
                self.on_focus_gained(normalized, timestamp_utc=runtime_event.get("timestamp_utc"))

            return state

    def resolve_commit(
        self,
        control: dict[str, Any] | None,
        reason: str,
        *,
        timestamp_utc: str | None = None,
        source_event_type: str | None = None,
        source_key: str | None = None,
    ) -> dict[str, Any] | None:
        normalized = self._normalize_control(control)
        with self._lock:
            control_key = self._build_control_key(normalized) if normalized is not None else self._active_control_key
            if control_key is None:
                return None

            state = self._states.get(control_key)
            if state is None:
                return None

            if normalized is not None:
                self._update_state_from_control(state, normalized, timestamp_utc=timestamp_utc)

            if not state.edit_session_active:
                state.is_focused = False
                if self._active_control_key == control_key:
                    self._active_control_key = None
                return None

            final_value, value_source = self._resolve_final_value(state, normalized)
            previous_value = state.edit_start_value

            state.edit_session_active = False
            state.is_focused = False
            state.last_update = timestamp_utc or state.last_update
            if self._active_control_key == control_key:
                self._active_control_key = None

            if self._is_noop_commit(previous_value, final_value):
                state.typed_buffer = None
                state.edit_start_value = state.current_value
                self._debug(f"skip_commit control={control_key} reason={reason} skipped=no_change")
                return None

            commit_signature = self._build_commit_signature(control_key, previous_value, final_value, reason)
            if self._is_duplicate_commit(state, commit_signature, timestamp_utc):
                state.typed_buffer = None
                state.edit_start_value = state.current_value
                self._debug(f"skip_commit control={control_key} reason={reason} skipped=duplicate")
                return None

            payload = {
                "control_key": control_key,
                "window_title": state.metadata.window_title,
                "process_name": state.metadata.process_name,
                "hwnd": state.metadata.hwnd,
                "ui_target": dict(state.metadata.ui_target),
                "previous_value": previous_value,
                "final_value": final_value,
                "commit_reason": reason,
                "value_source": value_source,
                "source_event_type": source_event_type,
                "source_key": source_key,
                "field_session_started_at_utc": state.focus_start,
            }

            state.previous_committed_value = final_value
            state.current_value = final_value
            state.last_commit = timestamp_utc or state.last_commit
            state.last_value_source = value_source
            state.last_commit_signature = commit_signature
            state.last_commit_reason = reason
            state.last_commit_value = final_value
            state.last_commit_timestamp = timestamp_utc
            state.edit_start_value = final_value
            state.typed_buffer = None
            self._debug(
                f"commit control={control_key} reason={reason} previous={previous_value!r} final={final_value!r} source={value_source}"
            )
            return payload

    def get_control_state(self, control_key: str) -> ControlState | None:
        with self._lock:
            return self._states.get(control_key)

    def is_editable_control(self, control: dict[str, Any] | None) -> bool:
        normalized = self._normalize_control(control)
        if normalized is None:
            return False

        ui_target = normalized.get("ui_target") or {}
        state = normalized.get("state") or {}
        control_type = (ui_target.get("control_type") or state.get("control_type") or "").strip().lower()
        class_name = (ui_target.get("class_name") or state.get("class_name") or "").strip().lower()
        semantic_role = (state.get("semantic_role") or "").strip().lower()
        supports_value = any(
            state.get(name) not in (None, "", [], {})
            for name in (
                "value_text",
                "wrapper_value",
                "edit_text",
                "selected_text",
                "selected_item_text",
            )
        )

        if semantic_role == "text_input":
            return True
        if control_type in self.NON_EDITABLE_TYPES and not supports_value:
            return False
        if control_type in self.EDITABLE_TYPES:
            return True
        if class_name in self.EDITABLE_CLASSES:
            return True
        if supports_value and control_type not in {"button", "checkbox", "radio"}:
            return True
        return False

    def _get_or_create_state(
        self,
        control_key: str,
        control: dict[str, Any],
        *,
        timestamp_utc: str | None,
    ) -> ControlState:
        state = self._states.get(control_key)
        metadata = self._snapshot_metadata(control)
        if state is None:
            state = ControlState(
                control_key=control_key,
                metadata=metadata,
                current_value=metadata.value,
                previous_committed_value=metadata.value,
                edit_start_value=metadata.value,
                last_update=timestamp_utc,
                latest_snapshot=dict(control),
            )
            self._states[control_key] = state
            return state

        state.metadata = metadata
        state.latest_snapshot = dict(control)
        return state

    def _update_state_from_control(
        self,
        state: ControlState,
        control: dict[str, Any],
        *,
        timestamp_utc: str | None,
    ) -> None:
        metadata = self._snapshot_metadata(control)
        state.metadata = metadata
        state.latest_snapshot = dict(control)
        if metadata.value is not None:
            state.current_value = metadata.value
            state.last_value_source = "payload"
        state.last_update = timestamp_utc or state.last_update

    def _resolve_final_value(
        self,
        state: ControlState,
        control: dict[str, Any] | None,
    ) -> tuple[str | None, str]:
        providers: list[tuple[str, Callable[[], Any]]] = [
            ("runtime_observer", lambda: state.runtime_cached_value),
            (
                "ui_automation",
                lambda: self.ui_automation_value_provider(control or state.latest_snapshot or {})
                if self.ui_automation_value_provider is not None
                else None,
            ),
            (
                "native_text",
                lambda: self.native_value_provider(control or state.latest_snapshot or {})
                if self.native_value_provider is not None
                else None,
            ),
            ("payload", lambda: self._value_from_payload(control or state.latest_snapshot or {})),
            ("typed_buffer", lambda: state.typed_buffer),
        ]

        for source_name, provider in providers:
            try:
                raw_value = provider()
            except Exception:
                raw_value = None
            normalized = self._normalize_value(raw_value)
            if normalized is None:
                continue
            state.last_value_source = source_name
            state.current_value = normalized
            self._debug(f"resolved_value control={state.control_key} source={source_name} value={normalized!r}")
            return normalized, source_name

        state.last_value_source = "none"
        self._debug(f"resolved_value control={state.control_key} source=none value=None")
        return None, "none"

    def _extract_runtime_value(
        self,
        runtime_event: dict[str, Any],
        control: dict[str, Any],
    ) -> str | None:
        candidates = [
            runtime_event.get("value"),
            runtime_event.get("text"),
        ]
        control_state = runtime_event.get("control_state") or {}
        previous_control_state = runtime_event.get("previous_control_state") or {}
        changes = runtime_event.get("control_state_changes") or {}
        candidates.extend(
            [
                control_state.get("value_text"),
                control_state.get("selected_text"),
                control_state.get("wrapper_value"),
                control_state.get("control_text"),
                control_state.get("edit_text"),
                control_state.get("button_text"),
                self._extract_change_after_value(changes),
                previous_control_state.get("value_text"),
                self._value_from_payload(control),
            ]
        )
        for candidate in candidates:
            normalized = self._normalize_value(candidate)
            if normalized is not None:
                return normalized
        return None

    def _extract_change_after_value(self, changes: dict[str, Any]) -> Any:
        for key in ("value_text", "selected_text", "wrapper_value", "control_text", "edit_text", "button_text"):
            change = changes.get(key)
            if isinstance(change, dict) and "after" in change:
                return change.get("after")
        return None

    def _is_noop_commit(self, before: str | None, after: str | None) -> bool:
        return (before or "") == (after or "")

    def _build_commit_signature(
        self,
        control_key: str,
        previous_value: str | None,
        final_value: str | None,
        reason: str,
    ) -> str:
        return "|".join(
            [
                control_key,
                reason,
                previous_value or "",
                final_value or "",
            ]
        )

    def _is_duplicate_commit(
        self,
        state: ControlState,
        commit_signature: str,
        timestamp_utc: str | None,
    ) -> bool:
        if state.last_commit_signature != commit_signature:
            return False
        if timestamp_utc is None or state.last_commit_timestamp is None:
            return True
        previous_seconds = self._timestamp_to_seconds(state.last_commit_timestamp)
        current_seconds = self._timestamp_to_seconds(timestamp_utc)
        if previous_seconds is None or current_seconds is None:
            return True
        return (current_seconds - previous_seconds) <= self.duplicate_suppression_window_seconds

    def _timestamp_to_seconds(self, timestamp_utc: str) -> float | None:
        try:
            import datetime as _datetime

            normalized = timestamp_utc.replace("Z", "+00:00")
            return _datetime.datetime.fromisoformat(normalized).timestamp()
        except Exception:
            return None

    def _control_from_runtime_event(self, runtime_event: dict[str, Any]) -> dict[str, Any] | None:
        ui_target = runtime_event.get("ui_target") or {}
        if not ui_target and not runtime_event.get("hwnd"):
            return None
        return self._normalize_control(
            {
                "ui_target": ui_target,
                "window_title": runtime_event.get("window_title"),
                "process_name": runtime_event.get("process_name"),
                "hwnd": runtime_event.get("hwnd") or ui_target.get("hwnd"),
                "state": runtime_event.get("control_state"),
                "element": runtime_event.get("element"),
                "value": runtime_event.get("value"),
            }
        )

    def _snapshot_metadata(self, control: dict[str, Any]) -> ControlMetadataSnapshot:
        ui_target = dict(control.get("ui_target") or {})
        state = control.get("state")
        return ControlMetadataSnapshot(
            ui_target=ui_target,
            window_title=self._normalize_value(control.get("window_title") or ui_target.get("window_title")),
            process_name=self._normalize_value(control.get("process_name") or ui_target.get("process_name")),
            hwnd=self._normalize_int(control.get("hwnd") or ui_target.get("hwnd")),
            state=dict(state) if isinstance(state, dict) else state,
            element=control.get("element"),
            value=self._value_from_payload(control),
        )

    def _control_key_if_editable(self, control: dict[str, Any] | None) -> str | None:
        if control is None or not self.is_editable_control(control):
            return None
        return self._build_control_key(control)

    def _build_control_key(self, control: dict[str, Any] | None) -> str | None:
        normalized = self._normalize_control(control)
        if normalized is None:
            return None

        ui_target = normalized.get("ui_target") or {}
        state = normalized.get("state") or {}
        element = normalized.get("element") or {}
        parts: list[str] = []

        strongest = [
            ("hwnd", normalized.get("hwnd") or ui_target.get("hwnd")),
            ("handle", ui_target.get("handle") or state.get("handle") or element.get("handle")),
            ("automation_id", ui_target.get("automation_id") or element.get("automation_id")),
            ("control_id", ui_target.get("control_id") or state.get("control_id")),
        ]
        fallback = [
            ("name", ui_target.get("control_name") or element.get("name")),
            ("type", ui_target.get("control_type") or state.get("control_type") or element.get("control_type")),
            ("class", ui_target.get("class_name") or state.get("class_name") or element.get("class_name")),
            ("window", normalized.get("window_title") or ui_target.get("window_title")),
            ("process", normalized.get("process_name") or ui_target.get("process_name") or element.get("process_name")),
        ]

        for label, value in strongest + fallback:
            normalized_value = self._normalize_identity_value(value)
            if normalized_value is None:
                continue
            parts.append(f"{label}={normalized_value}")

        if not parts:
            return None
        return "|".join(parts)

    def _normalize_control(self, control: dict[str, Any] | None) -> dict[str, Any] | None:
        if not control:
            return None

        ui_target = control.get("ui_target") or {}
        state = control.get("state") or control.get("control_state")
        element = control.get("element")
        if element is not None and not isinstance(element, dict):
            element = self._object_to_dict(element)

        normalized = {
            "ui_target": dict(ui_target) if isinstance(ui_target, dict) else {},
            "state": dict(state) if isinstance(state, dict) else state,
            "element": element if isinstance(element, dict) else {},
            "window_title": control.get("window_title") or ui_target.get("window_title"),
            "process_name": control.get("process_name") or ui_target.get("process_name"),
            "hwnd": control.get("hwnd") or ui_target.get("hwnd"),
            "value": control.get("value"),
        }
        return normalized

    def _object_to_dict(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        names = (
            "name",
            "automation_id",
            "control_type",
            "class_name",
            "handle",
            "process_name",
            "top_level_handle",
        )
        result: dict[str, Any] = {}
        for name in names:
            try:
                result[name] = getattr(value, name, None)
            except Exception:
                result[name] = None
        return result

    def _value_from_payload(self, control: dict[str, Any]) -> str | None:
        state = control.get("state") or {}
        ui_target = control.get("ui_target") or {}
        candidates = [
            control.get("value"),
            ui_target.get("value"),
            ui_target.get("text"),
            state.get("value_text"),
            state.get("selected_text"),
            state.get("wrapper_value"),
            state.get("control_text"),
            state.get("edit_text"),
            state.get("button_text"),
            state.get("selected_item_text"),
        ]
        for candidate in candidates:
            normalized = self._normalize_value(candidate)
            if normalized is not None:
                return normalized
        return None

    def _apply_key_to_buffer(self, existing: str | None, key_name: str | None) -> str | None:
        buffer = existing or ""
        if not key_name:
            return buffer or None
        if len(key_name) == 1:
            buffer += key_name
            return buffer[-200:] or None
        if key_name == "Key.space":
            buffer += " "
            return buffer[-200:] or None
        if key_name == "Key.tab":
            buffer += "\t"
            return buffer[-200:] or None
        if key_name == "Key.backspace":
            buffer = buffer[:-1]
            return buffer or None
        return buffer or None

    def _normalize_value(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            joined = ", ".join(str(item).strip() for item in value if str(item).strip())
            return joined or None
        try:
            text = str(value).strip()
        except Exception:
            return None
        return text or None

    def _normalize_identity_value(self, value: Any) -> str | None:
        normalized = self._normalize_value(value)
        if normalized is None:
            return None
        return normalized.lower()

    def _normalize_int(self, value: Any) -> int | None:
        try:
            if value in (None, "", 0, "0"):
                return None
            return int(value)
        except Exception:
            return None

    def _debug(self, message: str) -> None:
        if self.debug_logger is None:
            return
        try:
            self.debug_logger(message)
        except Exception:
            pass
