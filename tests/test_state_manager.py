from __future__ import annotations

import unittest

from recorder.state_manager import StateManager


def editable_control(
    *,
    hwnd: int = 100,
    handle: int = 101,
    value: str | None = None,
    control_name: str | None = "Descrizione",
    automation_id: str | None = "txtDescrizione",
    control_id: str | None = "txtDescrizione",
) -> dict[str, object]:
    return {
        "hwnd": hwnd,
        "window_title": "Dettaglio articolo",
        "process_name": "demo.exe",
        "value": value,
        "state": {
            "semantic_role": "text_input",
            "value_text": value,
            "control_id": control_id,
            "handle": handle,
        },
        "ui_target": {
            "control_name": control_name,
            "control_id": control_id,
            "automation_id": automation_id,
            "control_type": "Edit",
            "class_name": "Edit",
            "handle": handle,
            "hwnd": hwnd,
        },
    }


def button_control() -> dict[str, object]:
    return {
        "hwnd": 100,
        "window_title": "Dettaglio articolo",
        "process_name": "demo.exe",
        "value": "Salva",
        "state": {"semantic_role": "button"},
        "ui_target": {
            "control_name": "Salva",
            "control_id": "btnSalva",
            "automation_id": "btnSalva",
            "control_type": "Button",
            "class_name": "Button",
            "handle": 201,
            "hwnd": 100,
        },
    }


class StateManagerTests(unittest.TestCase):
    def test_state_lifecycle_tracks_start_current_and_commit(self) -> None:
        manager = StateManager()
        control = editable_control(value="old")

        manager.on_focus_gained(control, timestamp_utc="2026-03-23T10:00:00Z")
        manager.on_key_event(
            editable_control(value="old"),
            {"event_type": "key_down", "key_name": "x", "timestamp_utc": "2026-03-23T10:00:01Z"},
        )

        commit = manager.on_focus_lost(
            editable_control(value="oldx"),
            timestamp_utc="2026-03-23T10:00:02Z",
            reason="focus_lost",
        )

        self.assertIsNotNone(commit)
        assert commit is not None
        self.assertEqual(commit["previous_value"], "old")
        self.assertEqual(commit["final_value"], "oldx")
        self.assertEqual(commit["value_source"], "payload")

        state = manager.get_control_state(commit["control_key"])
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.previous_committed_value, "oldx")
        self.assertEqual(state.edit_start_value, "oldx")
        self.assertFalse(state.edit_session_active)
        self.assertFalse(state.is_focused)

    def test_identity_is_stable_with_partial_metadata(self) -> None:
        manager = StateManager()
        first = editable_control(value="a", control_name=None, automation_id=None, control_id="42")
        second = editable_control(value="b", control_name=None, automation_id=None, control_id="42")

        first_key = manager._build_control_key(first)
        second_key = manager._build_control_key(second)

        self.assertEqual(first_key, second_key)
        self.assertIn("control_id=42", first_key)

    def test_value_resolution_fallback_order_prefers_runtime_then_uia_then_native_then_payload_then_buffer(self) -> None:
        calls: list[str] = []

        def uia_provider(control: dict[str, object]) -> str | None:
            calls.append("uia")
            return control.get("uia_value")  # type: ignore[return-value]

        def native_provider(control: dict[str, object]) -> str | None:
            calls.append("native")
            return control.get("native_value")  # type: ignore[return-value]

        manager = StateManager(
            ui_automation_value_provider=uia_provider,
            native_value_provider=native_provider,
        )
        control = editable_control(value=None)
        manager.on_focus_gained(control, timestamp_utc="2026-03-23T10:10:00Z")
        key = manager._build_control_key(control)
        state = manager.get_control_state(key)
        assert state is not None

        state.runtime_cached_value = "runtime"
        final_value, source = manager._resolve_final_value(state, dict(control))
        self.assertEqual((final_value, source), ("runtime", "runtime_observer"))
        self.assertEqual(calls, [])

        state.runtime_cached_value = None
        final_value, source = manager._resolve_final_value(state, {**control, "uia_value": "uia"})
        self.assertEqual((final_value, source), ("uia", "ui_automation"))
        self.assertEqual(calls, ["uia"])

        calls.clear()
        final_value, source = manager._resolve_final_value(state, {**control, "native_value": "native"})
        self.assertEqual((final_value, source), ("native", "native_text"))
        self.assertEqual(calls, ["uia", "native"])

        calls.clear()
        final_value, source = manager._resolve_final_value(state, editable_control(value="payload"))
        self.assertEqual((final_value, source), ("payload", "payload"))
        self.assertEqual(calls, ["uia", "native"])

        calls.clear()
        state.typed_buffer = "typed"
        final_value, source = manager._resolve_final_value(state, editable_control(value=None))
        self.assertEqual((final_value, source), ("typed", "typed_buffer"))
        self.assertEqual(calls, ["uia", "native"])

    def test_runtime_event_enriches_cached_value(self) -> None:
        manager = StateManager()
        control = editable_control(value="old")
        manager.on_focus_gained(control, timestamp_utc="2026-03-23T10:20:00Z")
        key = manager._build_control_key(control)

        manager.on_runtime_event(
            {
                "event_type": "EVENT_OBJECT_VALUECHANGE",
                "timestamp_utc": "2026-03-23T10:20:01Z",
                "hwnd": 100,
                "window_title": "Dettaglio articolo",
                "process_name": "demo.exe",
                "ui_target": control["ui_target"],
                "control_state": {
                    "semantic_role": "text_input",
                    "value_text": "new runtime",
                    "control_id": "txtDescrizione",
                },
            }
        )

        state = manager.get_control_state(key)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.runtime_cached_value, "new runtime")
        self.assertEqual(state.current_value, "new runtime")

    def test_duplicate_commit_suppression_and_noop_filtering(self) -> None:
        manager = StateManager()
        control = editable_control(value="start")
        manager.on_focus_gained(control, timestamp_utc="2026-03-23T10:30:00Z")

        noop = manager.resolve_commit(
            editable_control(value="start"),
            reason="focus_lost",
            timestamp_utc="2026-03-23T10:30:01Z",
        )
        self.assertIsNone(noop)

        manager.on_focus_gained(editable_control(value="start"), timestamp_utc="2026-03-23T10:30:02Z")
        first = manager.resolve_commit(
            editable_control(value="changed"),
            reason="enter",
            timestamp_utc="2026-03-23T10:30:03Z",
        )
        self.assertIsNotNone(first)

        manager.on_focus_gained(editable_control(value="changed"), timestamp_utc="2026-03-23T10:30:04Z")
        duplicate = manager.resolve_commit(
            editable_control(value="changed"),
            reason="enter",
            timestamp_utc="2026-03-23T10:30:04.100000Z",
        )
        self.assertIsNone(duplicate)

    def test_multi_control_isolation(self) -> None:
        manager = StateManager()
        first = editable_control(hwnd=100, handle=101, value="a", control_id="a", automation_id="a")
        second = editable_control(hwnd=100, handle=102, value="b", control_id="b", automation_id="b")

        manager.on_focus_gained(first, timestamp_utc="2026-03-23T10:40:00Z")
        manager.on_key_event(first, {"event_type": "key_down", "key_name": "1", "timestamp_utc": "2026-03-23T10:40:01Z"})
        manager.on_focus_gained(second, timestamp_utc="2026-03-23T10:40:02Z")
        manager.on_key_event(second, {"event_type": "key_down", "key_name": "2", "timestamp_utc": "2026-03-23T10:40:03Z"})

        first_key = manager._build_control_key(first)
        second_key = manager._build_control_key(second)
        first_state = manager.get_control_state(first_key)
        second_state = manager.get_control_state(second_key)

        self.assertIsNotNone(first_state)
        self.assertIsNotNone(second_state)
        assert first_state is not None
        assert second_state is not None
        self.assertEqual(first_state.typed_buffer, "1")
        self.assertEqual(second_state.typed_buffer, "2")
        self.assertNotEqual(first_state.control_key, second_state.control_key)


if __name__ == "__main__":
    unittest.main()
