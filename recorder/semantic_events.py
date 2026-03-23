from __future__ import annotations

from typing import Any

from recorder.state_manager import StateManager


class SemanticEventBuilder:
    """Thin semantic adapter that delegates stateful decisions to StateManager."""

    def __init__(self, state_manager: StateManager | None = None) -> None:
        self.state_manager = state_manager or StateManager()

    def process_event(
        self,
        *,
        event_type: str,
        timestamp_utc: str,
        key_name: str | None,
        pressed: bool | None = None,
        pre_snapshot: dict[str, Any] | None,
        post_snapshot: dict[str, Any] | None,
        target_snapshot: dict[str, Any] | None = None,
        is_editable: Any,
    ) -> list[dict[str, Any]]:
        return self.state_manager.register_event(
            {
                "event_type": event_type,
                "timestamp_utc": timestamp_utc,
                "key_name": key_name,
                "pressed": pressed,
                "pre_snapshot": pre_snapshot,
                "post_snapshot": post_snapshot,
                "target_snapshot": target_snapshot,
            }
        )

    def flush(
        self,
        *,
        timestamp_utc: str,
        snapshot: dict[str, Any] | None,
        is_editable: Any,
    ) -> list[dict[str, Any]]:
        if snapshot is not None:
            self.state_manager.on_focus_gained(snapshot, timestamp_utc=timestamp_utc)
        committed = self.state_manager.resolve_commit(
            snapshot,
            reason="session_end",
            timestamp_utc=timestamp_utc,
            source_event_type="session_end",
            source_key=None,
        )
        return [committed] if committed is not None else []
