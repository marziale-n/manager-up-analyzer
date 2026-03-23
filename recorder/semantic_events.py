from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class InputSession:
    field_key: str
    ui_target: dict[str, Any]
    window_title: str | None
    process_name: str | None
    hwnd: int | None
    previous_value: str | None
    last_value: str | None
    started_at_utc: str | None

    @property
    def dirty(self) -> bool:
        return (self.previous_value or "") != (self.last_value or "")


class SemanticEventBuilder:
    """Tracks editable controls and emits semantic input_commit events."""

    def __init__(self) -> None:
        self.active_input: InputSession | None = None

    def process_event(
        self,
        *,
        event_type: str,
        timestamp_utc: str,
        key_name: str | None,
        pre_snapshot: dict[str, Any] | None,
        post_snapshot: dict[str, Any] | None,
        is_editable: Any,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        self._ensure_session(pre_snapshot, timestamp_utc=timestamp_utc, is_editable=is_editable)
        active_before_post = self.active_input
        post_field_key = self._snapshot_field_key(post_snapshot, is_editable=is_editable)

        if event_type == "key_up" and key_name == "Key.enter":
            commit_snapshot = post_snapshot or pre_snapshot
            committed = self._commit_active(
                reason="enter",
                source_event_type=event_type,
                source_key=key_name,
                commit_snapshot=commit_snapshot,
            )
            if committed is not None:
                events.append(committed)

            post_session = self._ensure_session(post_snapshot, timestamp_utc=timestamp_utc, is_editable=is_editable)
            if post_session is not None:
                post_session.previous_value = post_session.last_value
            return events

        if active_before_post is not None and post_field_key != active_before_post.field_key:
            committed = self._commit_active(
                reason="focus_lost",
                source_event_type=event_type,
                source_key=key_name,
                commit_snapshot=pre_snapshot or post_snapshot,
            )
            if committed is not None:
                events.append(committed)

        self._ensure_session(post_snapshot, timestamp_utc=timestamp_utc, is_editable=is_editable)

        return events

    def flush(
        self,
        *,
        timestamp_utc: str,
        snapshot: dict[str, Any] | None,
        is_editable: Any,
    ) -> list[dict[str, Any]]:
        self._ensure_session(snapshot, timestamp_utc=timestamp_utc, is_editable=is_editable)
        committed = self._commit_active(
            reason="session_end",
            source_event_type="session_end",
            source_key=None,
            commit_snapshot=snapshot,
        )
        return [committed] if committed is not None else []

    def _ensure_session(
        self,
        snapshot: dict[str, Any] | None,
        *,
        timestamp_utc: str,
        is_editable: Any,
    ) -> InputSession | None:
        if not snapshot:
            return None

        ui_target = snapshot.get("ui_target") or {}
        state = snapshot.get("state")
        if not is_editable(ui_target, state):
            return None

        field_key = self._build_field_key(snapshot)
        if field_key is None:
            return None

        value = self._normalize_text(snapshot.get("value"))
        if self.active_input is not None and self.active_input.field_key == field_key:
            self.active_input.ui_target = ui_target
            self.active_input.window_title = snapshot.get("window_title")
            self.active_input.process_name = snapshot.get("process_name")
            self.active_input.hwnd = snapshot.get("hwnd")
            self.active_input.last_value = value
            return self.active_input

        session = InputSession(
            field_key=field_key,
            ui_target=dict(ui_target),
            window_title=snapshot.get("window_title"),
            process_name=snapshot.get("process_name"),
            hwnd=snapshot.get("hwnd"),
            previous_value=value,
            last_value=value,
            started_at_utc=timestamp_utc,
        )
        self.active_input = session
        return session

    def _commit_active(
        self,
        *,
        reason: str,
        source_event_type: str,
        source_key: str | None,
        commit_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        session = self.active_input
        if session is None:
            return None

        final_value = session.last_value
        if commit_snapshot is not None:
            final_value = self._normalize_text(commit_snapshot.get("value")) or final_value

        if (session.previous_value or "") == (final_value or ""):
            self.active_input = None
            return None

        payload = {
            "window_title": session.window_title,
            "process_name": session.process_name,
            "hwnd": session.hwnd,
            "ui_target": dict(session.ui_target),
            "previous_value": session.previous_value,
            "final_value": final_value,
            "commit_reason": reason,
            "source_event_type": source_event_type,
            "source_key": source_key,
            "field_session_started_at_utc": session.started_at_utc,
        }
        self.active_input = None
        return payload

    def _build_field_key(self, snapshot: dict[str, Any]) -> str | None:
        ui_target = snapshot.get("ui_target") or {}
        parts = [
            snapshot.get("hwnd"),
            ui_target.get("handle"),
            ui_target.get("automation_id"),
            ui_target.get("control_id"),
            ui_target.get("control_name"),
            ui_target.get("control_type"),
        ]
        normalized = [self._normalize_text(part) for part in parts if part not in (None, "")]
        if not normalized:
            return None
        return "|".join(normalized)

    def _same_session(
        self,
        active: InputSession | None,
        other: InputSession | None,
    ) -> bool:
        if active is None and other is None:
            return True
        if active is None or other is None:
            return False
        return active.field_key == other.field_key

    def _snapshot_field_key(
        self,
        snapshot: dict[str, Any] | None,
        *,
        is_editable: Any,
    ) -> str | None:
        if not snapshot:
            return None
        ui_target = snapshot.get("ui_target") or {}
        if not is_editable(ui_target, snapshot.get("state")):
            return None
        return self._build_field_key(snapshot)

    def _normalize_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            joined = ", ".join(str(item).strip() for item in value if str(item).strip())
            return joined or None
        try:
            text = str(value)
        except Exception:
            return None
        text = text.strip()
        return text or None
