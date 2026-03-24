from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from recorder.context import UIContextResolver
from recorder.ui_resolver import UIElementResolver


@dataclass(slots=True)
class SemanticEnrichmentConfig:
    enrich_control_identity: bool = True
    enrich_control_state: bool = True
    enrich_label_mapping: bool = True
    enrich_dialogs: bool = True
    enrich_grid_context: bool = True
    enrich_ui_snapshots: bool = True
    include_confidence_metadata: bool = True
    ui_snapshot_max_controls: int = 25

    def to_metadata(self) -> dict[str, Any]:
        return {
            "enrich_control_identity": self.enrich_control_identity,
            "enrich_control_state": self.enrich_control_state,
            "enrich_label_mapping": self.enrich_label_mapping,
            "enrich_dialogs": self.enrich_dialogs,
            "enrich_grid_context": self.enrich_grid_context,
            "enrich_ui_snapshots": self.enrich_ui_snapshots,
            "include_confidence_metadata": self.include_confidence_metadata,
            "ui_snapshot_max_controls": self.ui_snapshot_max_controls,
        }


class SemanticEnricher:
    DIALOG_CLASS_NAMES = {"#32770", "thunderrt6formdc"}
    DIALOG_OPEN_EVENTS = {"dialog_start"}
    DIALOG_CLOSE_EVENTS = {"dialog_end"}
    STATEFUL_RUNTIME_EVENTS = {
        "dialog_end",
        "dialog_start",
        "foreground_changed",
        "object_focus",
        "object_statechange",
        "object_valuechange",
    }
    UI_CHECKPOINT_EVENTS = {
        "dialog_start",
        "dialog_end",
        "foreground_changed",
        "input_commit",
        "mouse_click",
        "object_focus",
        "object_statechange",
        "object_valuechange",
    }

    def __init__(
        self,
        *,
        context: UIContextResolver | None = None,
        ui_resolver: UIElementResolver | None = None,
        config: SemanticEnrichmentConfig | None = None,
    ) -> None:
        self.context = context or UIContextResolver()
        self.ui_resolver = ui_resolver or UIElementResolver(self.context)
        self.config = config or SemanticEnrichmentConfig()
        self._lock = RLock()
        self._last_user_event: dict[str, Any] | None = None
        self._open_dialogs: dict[int, dict[str, Any]] = {}

    def note_user_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        timestamp_utc: str | None,
    ) -> None:
        summary = self._build_trigger_summary(event_type=event_type, payload=payload, timestamp_utc=timestamp_utc)
        if summary is None:
            return

        with self._lock:
            self._last_user_event = summary
            dialog_hwnd = self._normalize_int(payload.get("hwnd"))
            control_context = payload.get("control_context") or {}
            control_type = (control_context.get("type") or "").strip().lower()
            clicked_button = self._normalize_text(control_context.get("label_text") or control_context.get("name"))
            if dialog_hwnd is not None and control_type == "button" and clicked_button:
                dialog_state = self._open_dialogs.get(dialog_hwnd)
                if dialog_state is not None:
                    dialog_state["clicked_button"] = clicked_button

    def enrich_recorder_payload(
        self,
        *,
        event_type: str,
        timestamp_utc: str | None,
        payload: dict[str, Any],
        pre_snapshot: dict[str, Any] | None = None,
        post_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._apply_shared_enrichment(
            event_type=event_type,
            timestamp_utc=timestamp_utc,
            payload=payload,
            before_snapshot=pre_snapshot or self._snapshot_from_payload(payload),
            after_snapshot=post_snapshot or self._post_snapshot_from_payload(payload),
            channel="event",
        )
        return payload

    def enrich_input_commit_payload(
        self,
        *,
        timestamp_utc: str | None,
        payload: dict[str, Any],
        latest_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        before_state = None
        after_state = None
        if self.config.enrich_control_state:
            before_state = self._state_from_snapshot(
                latest_snapshot,
                value_override=payload.get("previous_value"),
                preferred_source="event",
            )
            after_state = self._state_from_snapshot(
                latest_snapshot,
                value_override=payload.get("final_value"),
                preferred_source=payload.get("value_source") or "runtime",
            )

        self._apply_shared_enrichment(
            event_type="input_commit",
            timestamp_utc=timestamp_utc,
            payload=payload,
            before_snapshot=latest_snapshot,
            after_snapshot=latest_snapshot,
            channel="event",
            before_state=before_state,
            after_state=after_state,
        )
        return payload

    def enrich_runtime_payload(
        self,
        *,
        timestamp_utc: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        runtime_event_type = str(payload.get("event_type") or "")
        before_snapshot = {
            "ui_target": payload.get("ui_target"),
            "state": payload.get("previous_control_state"),
            "element": payload.get("element"),
            "window_title": payload.get("window_title"),
            "process_name": payload.get("process_name"),
            "hwnd": payload.get("hwnd"),
        }
        current_state = payload.get("control_state")
        if (
            current_state is None
            and self.config.enrich_control_state
            and runtime_event_type in self.STATEFUL_RUNTIME_EVENTS
        ):
            current_state = self.context.capture_state_from_handle(self._normalize_int(payload.get("hwnd")))
            if current_state is not None:
                payload["control_state"] = current_state

        after_snapshot = {
            "ui_target": payload.get("ui_target"),
            "state": current_state,
            "element": payload.get("element"),
            "window_title": payload.get("window_title"),
            "process_name": payload.get("process_name"),
            "hwnd": payload.get("hwnd"),
        }

        self._apply_shared_enrichment(
            event_type=runtime_event_type,
            timestamp_utc=timestamp_utc,
            payload=payload,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            channel="runtime",
        )

        if self.config.enrich_dialogs:
            dialog = self._build_dialog_context(
                event_type=runtime_event_type,
                timestamp_utc=timestamp_utc,
                payload=payload,
            )
            if dialog is not None:
                payload["dialog"] = dialog
                triggered_by = dialog.get("triggered_by")
                if triggered_by is not None:
                    payload["triggered_by"] = triggered_by
                if self.config.include_confidence_metadata:
                    existing_sources = list((payload.get("provenance") or {}).get("source") or [])
                    payload["provenance"] = self._build_provenance(
                        sources=existing_sources + ["runtime"],
                        payload=payload,
                        method="runtime_observer_enrichment",
                    )

        return payload

    def _apply_shared_enrichment(
        self,
        *,
        event_type: str,
        timestamp_utc: str | None,
        payload: dict[str, Any],
        before_snapshot: dict[str, Any] | None,
        after_snapshot: dict[str, Any] | None,
        channel: str,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
    ) -> None:
        sources: list[str] = [channel]
        identity_snapshot = self._snapshot_from_payload(payload) or after_snapshot or before_snapshot

        if self.config.enrich_control_identity:
            window_context = self._build_window_context(payload, identity_snapshot, source=channel)
            control_context = self._build_control_context(payload, identity_snapshot, source=channel)
            if window_context is not None:
                payload["window_context"] = window_context
            if control_context is not None:
                payload["control_context"] = control_context
            if payload.get("window") or payload.get("ui_target"):
                sources.append("runtime" if channel == "runtime" else "event")

        if self.config.enrich_control_state:
            resolved_before_state = before_state or self._state_from_snapshot(before_snapshot, preferred_source=channel)
            resolved_after_state = after_state or self._state_from_snapshot(after_snapshot, preferred_source=channel)
            if resolved_before_state is not None:
                payload["state_before"] = resolved_before_state
                sources.append(resolved_before_state.get("source") or channel)
            if resolved_after_state is not None:
                payload["state_after"] = resolved_after_state
                sources.append(resolved_after_state.get("source") or channel)

        if self.config.enrich_ui_snapshots and self._should_attach_ui_checkpoint(event_type, payload):
            ui_checkpoint = self.context.capture_ui_snapshot(
                self._normalize_int(payload.get("hwnd")),
                max_controls=self.config.ui_snapshot_max_controls,
            )
            if ui_checkpoint is not None:
                payload["ui_checkpoint"] = ui_checkpoint
                sources.append("runtime")

        if self.config.include_confidence_metadata:
            payload["provenance"] = self._build_provenance(
                sources=sources,
                payload=payload,
                method="runtime_observer_enrichment" if channel == "runtime" else "event_enrichment",
            )

    def _build_window_context(
        self,
        payload: dict[str, Any],
        snapshot: dict[str, Any] | None,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        window = payload.get("window") or {}
        element = (snapshot or {}).get("element") or payload.get("element") or payload.get("target_element") or {}
        if element is not None and not isinstance(element, dict):
            element = {}
        class_name = self._normalize_text(
            window.get("class_name")
            or element.get("top_level_class_name")
            or payload.get("class_name")
        )
        caption = self._normalize_text(
            payload.get("window_title")
            or window.get("title")
            or element.get("top_level_name")
        )
        hwnd = self._normalize_int(payload.get("hwnd") or window.get("handle") or element.get("top_level_handle"))
        pid = self._normalize_int(window.get("pid") or element.get("top_level_pid"))
        process_name = self._normalize_text(
            payload.get("process_name")
            or window.get("process_name")
            or element.get("top_level_process_name")
        )

        if not any([caption, class_name, hwnd, process_name]):
            return None

        metadata = {
            "caption": caption,
            "form_name": self._infer_form_name(class_name),
            "form_class": class_name,
            "hwnd": hwnd,
            "pid": pid,
            "process_name": process_name,
        }
        if self.config.include_confidence_metadata:
            metadata.update(
                {
                    "source": source,
                    "confidence": "high" if caption or hwnd else "medium",
                    "inference_method": "window_payload_resolution",
                }
            )
        return metadata

    def _build_control_context(
        self,
        payload: dict[str, Any],
        snapshot: dict[str, Any] | None,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        ui_target = dict((snapshot or {}).get("ui_target") or payload.get("ui_target") or {})
        element = dict((snapshot or {}).get("element") or payload.get("element") or payload.get("target_element") or {})
        state = dict((snapshot or {}).get("state") or payload.get("control_state") or payload.get("target_state") or {})
        if not any([ui_target, element, state]):
            return None

        label_metadata = ui_target.get("label_metadata") if self.config.enrich_label_mapping else None
        bounds = self._normalize_bounds_dict(ui_target.get("bounds"))
        parent = ui_target.get("parent") or {
            "name": self._normalize_text(element.get("parent_name")),
            "control_type": self._normalize_text(element.get("parent_control_type")),
        }
        control_context = {
            "name": self._normalize_text(ui_target.get("control_name") or element.get("name")),
            "type": self._normalize_text(ui_target.get("control_type") or state.get("control_type") or element.get("control_type")),
            "class_name": self._normalize_text(ui_target.get("class_name") or state.get("class_name") or element.get("class_name")),
            "hwnd": self._normalize_int(ui_target.get("handle") or state.get("handle") or element.get("handle")),
            "control_id": self._normalize_text(ui_target.get("control_id") or state.get("control_id")),
            "automation_id": self._normalize_text(ui_target.get("automation_id") or element.get("automation_id")),
            "parent_control_name": self._normalize_text((parent or {}).get("name")),
            "parent_control_type": self._normalize_text((parent or {}).get("control_type")),
            "parent_hierarchy": self._normalize_ancestry(ui_target.get("ancestry") or element.get("ancestry")),
            "bounds": bounds,
            "label_text": self._normalize_text((label_metadata or {}).get("text") or ui_target.get("label")),
            "label_control_id": self._normalize_text((label_metadata or {}).get("label_control_id")),
            "target_control_id": self._normalize_text((label_metadata or {}).get("target_control_id") or ui_target.get("control_id")),
        }

        if self.config.enrich_label_mapping and label_metadata is not None:
            control_context["label"] = dict(label_metadata)

        if self.config.enrich_grid_context and ui_target.get("grid_context") is not None:
            control_context["grid"] = dict(ui_target.get("grid_context") or {})

        selection_context = self._selection_context(state=state, payload=payload)
        if selection_context is not None:
            control_context["selection"] = selection_context

        if self.config.include_confidence_metadata:
            control_context.update(
                {
                    "source": source,
                    "confidence": "high" if control_context.get("hwnd") or control_context.get("automation_id") else "medium",
                    "inference_method": "ui_target_enrichment",
                }
            )

        if not any(value is not None for key, value in control_context.items() if key not in {"label", "grid", "selection"}):
            return None
        return control_context

    def _selection_context(
        self,
        *,
        state: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        selected_index = self._normalize_int(state.get("selected_index"))
        selected_text = self._normalize_text(state.get("selected_text"))
        is_expanded = state.get("is_expanded")
        if selected_index is None and selected_text is None and is_expanded is None:
            return None

        selection = {
            "selected_index": selected_index,
            "selected_text": selected_text,
            "lookup_open": bool(is_expanded) if is_expanded is not None else None,
            "lookup_window_caption": self._normalize_text(payload.get("window_title")),
        }
        if self.config.include_confidence_metadata:
            selection.update(
                {
                    "source": "runtime" if state else "event",
                    "confidence": "high" if selected_index is not None or selected_text else "medium",
                    "inference_method": "control_state_selection",
                }
            )
        return selection

    def _state_from_snapshot(
        self,
        snapshot: dict[str, Any] | None,
        *,
        value_override: Any | None = None,
        preferred_source: str,
    ) -> dict[str, Any] | None:
        if not snapshot:
            return None

        state = dict(snapshot.get("state") or snapshot.get("control_state") or {})
        ui_target = dict(snapshot.get("ui_target") or {})
        value = self._normalize_text(
            value_override
            if value_override is not None
            else snapshot.get("value")
            or ui_target.get("value")
            or ui_target.get("text")
            or state.get("value_text")
            or state.get("selected_text")
            or state.get("wrapper_value")
            or state.get("control_text")
            or state.get("edit_text")
            or state.get("button_text")
        )
        result = {
            "value": value,
            "enabled": self._normalize_bool(state.get("is_enabled") if "is_enabled" in state else state.get("enabled")),
            "visible": self._normalize_bool(state.get("is_visible") if "is_visible" in state else state.get("visible")),
            "focused": self._normalize_bool(state.get("has_focus") if "has_focus" in state else state.get("focused")),
            "tab_index": self._normalize_int(state.get("tab_index")),
            "selected_index": self._normalize_int(state.get("selected_index")),
            "selected_text": self._normalize_text(state.get("selected_text")),
            "checked": self._normalize_bool(state.get("checked")),
            "read_only": self._normalize_bool(state.get("is_read_only") if "is_read_only" in state else state.get("read_only")),
            "validation_state": self._infer_validation_state(state),
        }
        if self.config.include_confidence_metadata:
            result.update(
                {
                    "source": preferred_source,
                    "confidence": "high" if value is not None else "medium",
                    "inference_method": "snapshot_state_projection",
                }
            )

        non_metadata_keys = {
            "value",
            "enabled",
            "visible",
            "focused",
            "tab_index",
            "selected_index",
            "selected_text",
            "checked",
            "read_only",
            "validation_state",
        }
        if not any(result.get(key) is not None for key in non_metadata_keys):
            return None
        return result

    def _build_dialog_context(
        self,
        *,
        event_type: str,
        timestamp_utc: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        hwnd = self._normalize_int(payload.get("hwnd"))
        if not self._looks_like_dialog(event_type=event_type, payload=payload):
            return None

        dialog_details = self.context.capture_dialog_details(hwnd) if hwnd is not None else None
        with self._lock:
            if event_type in self.DIALOG_OPEN_EVENTS:
                dialog_state = {
                    "opened_at": timestamp_utc,
                    "triggered_by": dict(self._last_user_event) if self._last_user_event is not None else None,
                    "clicked_button": None,
                }
                if dialog_details is not None:
                    dialog_state.update(dialog_details)
                if hwnd is not None:
                    self._open_dialogs[hwnd] = dialog_state
            elif event_type in self.DIALOG_CLOSE_EVENTS and hwnd is not None:
                dialog_state = dict(self._open_dialogs.pop(hwnd, {}))
                if dialog_details is not None:
                    dialog_state.update({key: value for key, value in dialog_details.items() if value is not None})
                dialog_state["closed_at"] = timestamp_utc
            else:
                dialog_state = dict(self._open_dialogs.get(hwnd, {})) if hwnd is not None else {}
                if dialog_details is not None:
                    dialog_state.update(dialog_details)

        if not dialog_state and dialog_details is None:
            return None

        dialog = {
            "type": dialog_state.get("dialog_type") or (dialog_details or {}).get("dialog_type"),
            "title": dialog_state.get("dialog_title") or (dialog_details or {}).get("dialog_title") or self._normalize_text(payload.get("window_title")),
            "message": dialog_state.get("dialog_message") or (dialog_details or {}).get("dialog_message"),
            "buttons": dialog_state.get("available_buttons") or (dialog_details or {}).get("available_buttons"),
            "clicked_button": dialog_state.get("clicked_button"),
            "dialog_hwnd": hwnd,
            "opened_at": dialog_state.get("opened_at"),
            "closed_at": dialog_state.get("closed_at"),
        }
        if self.config.include_confidence_metadata:
            dialog.update(
                {
                    "source": "runtime",
                    "confidence": "high" if dialog.get("buttons") or dialog.get("message") else "medium",
                    "inference_method": "dialog_runtime_capture",
                }
            )

        triggered_by = dialog_state.get("triggered_by")
        if triggered_by is not None:
            dialog["triggered_by"] = triggered_by
        if not any(dialog.get(key) is not None for key in ("title", "message", "buttons", "dialog_hwnd")):
            return None
        return dialog

    def _looks_like_dialog(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        if event_type in self.DIALOG_OPEN_EVENTS | self.DIALOG_CLOSE_EVENTS:
            return True
        raw = payload.get("raw") or {}
        if not raw.get("is_window_object"):
            return False
        class_name = self._normalize_text(
            ((payload.get("window") or {}).get("class_name"))
            or ((payload.get("ui_target") or {}).get("class_name"))
        )
        if class_name and class_name.strip().lower() in self.DIALOG_CLASS_NAMES:
            return True
        return False

    def _should_attach_ui_checkpoint(self, event_type: str, payload: dict[str, Any]) -> bool:
        if payload.get("visual_checkpoint") is not None:
            return True
        if event_type == "mouse_click":
            return payload.get("pressed") is False
        return event_type in self.UI_CHECKPOINT_EVENTS

    def _build_trigger_summary(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        timestamp_utc: str | None,
    ) -> dict[str, Any] | None:
        if event_type not in {"input_commit", "key_up", "mouse_click"}:
            return None
        if event_type == "mouse_click" and payload.get("pressed") is True:
            return None
        control_context = payload.get("control_context") or self._build_control_context(
            payload,
            self._snapshot_from_payload(payload),
            source="event",
        )
        return {
            "event_type": event_type,
            "timestamp_utc": timestamp_utc,
            "window_caption": self._normalize_text(payload.get("window_title")),
            "control_name": self._normalize_text((control_context or {}).get("name")),
            "control_type": self._normalize_text((control_context or {}).get("type")),
            "control_hwnd": self._normalize_int((control_context or {}).get("hwnd")),
        }

    def _post_snapshot_from_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        post_ui_target = payload.get("post_ui_target")
        post_state = payload.get("post_focused_state") or payload.get("post_target_state")
        post_element = payload.get("post_focused_element")
        if post_ui_target is None and post_state is None and post_element is None:
            return None
        return {
            "ui_target": post_ui_target,
            "state": post_state,
            "element": post_element,
            "window_title": payload.get("post_window_title") or payload.get("window_title"),
            "process_name": payload.get("post_process_name") or payload.get("process_name"),
            "hwnd": payload.get("post_hwnd") or payload.get("hwnd"),
        }

    def _snapshot_from_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        ui_target = payload.get("ui_target")
        state = payload.get("target_state") or payload.get("control_state")
        element = payload.get("target_element") or payload.get("element")
        if ui_target is None and state is None and element is None:
            return None
        return {
            "ui_target": ui_target,
            "state": state,
            "element": element,
            "window_title": payload.get("window_title"),
            "process_name": payload.get("process_name"),
            "hwnd": payload.get("hwnd"),
            "value": payload.get("value"),
        }

    def _build_provenance(
        self,
        *,
        sources: list[str],
        payload: dict[str, Any],
        method: str,
    ) -> dict[str, Any]:
        unique_sources = [source for source in dict.fromkeys(source for source in sources if source)]
        confidence = "high"
        if payload.get("dialog") and not (payload.get("dialog") or {}).get("message"):
            confidence = "medium"
        if payload.get("control_context") and not (payload.get("control_context") or {}).get("hwnd"):
            confidence = "medium"
        if payload.get("state_before") is None and payload.get("state_after") is None:
            confidence = "low"
        return {
            "source": unique_sources,
            "confidence": confidence,
            "inference_method": method,
        }

    def _infer_form_name(self, class_name: str | None) -> str | None:
        normalized = (class_name or "").strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        if lowered in self.DIALOG_CLASS_NAMES or lowered.startswith("thunderrt6"):
            return None
        return normalized

    def _infer_validation_state(self, state: dict[str, Any]) -> str | None:
        invalid = state.get("is_invalid")
        if invalid is True:
            return "invalid"
        if invalid is False:
            return "valid"
        return self._normalize_text(state.get("validation_state"))

    def _normalize_ancestry(self, value: Any) -> list[dict[str, Any]] | None:
        if not isinstance(value, list):
            return None
        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            row = {
                "name": self._normalize_text(item.get("name")),
                "control_type": self._normalize_text(item.get("control_type")),
                "class_name": self._normalize_text(item.get("class_name")),
                "handle": self._normalize_int(item.get("handle")),
            }
            if any(row.get(key) is not None for key in row):
                normalized.append(row)
        return normalized or None

    def _normalize_bounds_dict(self, value: Any) -> dict[str, int] | None:
        if isinstance(value, dict):
            try:
                x = int(value["x"])
                y = int(value["y"])
                w = int(value["w"])
                h = int(value["h"])
            except Exception:
                return None
            return {"x": x, "y": y, "w": w, "h": h}
        if isinstance(value, list) and len(value) == 4:
            try:
                left, top, right, bottom = [int(part) for part in value]
            except Exception:
                return None
            return {
                "x": left,
                "y": top,
                "w": max(0, right - left),
                "h": max(0, bottom - top),
            }
        return None

    def _normalize_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            parts = [self._normalize_text(item) for item in value]
            joined = ", ".join(part for part in parts if part)
            return joined or None
        try:
            text = str(value).strip()
        except Exception:
            return None
        return text or None

    def _normalize_int(self, value: Any) -> int | None:
        try:
            if value in (None, "", 0, "0"):
                return None
            return int(value)
        except Exception:
            return None

    def _normalize_bool(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on", "checked"}:
                return True
            if normalized in {"false", "0", "no", "off", "unchecked"}:
                return False
        return bool(value)
