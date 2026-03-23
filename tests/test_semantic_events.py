from __future__ import annotations

import unittest

from recorder.semantic_events import SemanticEventBuilder


def editable_snapshot(
    *,
    hwnd: int = 100,
    handle: int = 101,
    value: str | None = None,
    control_name: str | None = "Descrizione",
) -> dict[str, object]:
    return {
        "hwnd": hwnd,
        "window_title": "Dettaglio articolo",
        "process_name": "demo.exe",
        "value": value,
        "state": {"semantic_role": "text_input"},
        "ui_target": {
            "control_name": control_name,
            "control_id": "txtDescrizione",
            "automation_id": "txtDescrizione",
            "control_type": "Edit",
            "class_name": "Edit",
            "handle": handle,
        },
    }


def button_snapshot() -> dict[str, object]:
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
        },
    }


def is_editable(ui_target: dict[str, object] | None, state: dict[str, object] | None) -> bool:
    return (ui_target or {}).get("control_type") == "Edit" or (state or {}).get("semantic_role") == "text_input"


class SemanticEventBuilderTests(unittest.TestCase):
    def test_commits_on_focus_loss(self) -> None:
        builder = SemanticEventBuilder()

        self.assertEqual(
            builder.process_event(
                event_type="mouse_click",
                timestamp_utc="2026-03-23T14:00:00Z",
                key_name=None,
                pre_snapshot=None,
                post_snapshot=editable_snapshot(value=""),
                is_editable=is_editable,
            ),
            [],
        )

        self.assertEqual(
            builder.process_event(
                event_type="key_up",
                timestamp_utc="2026-03-23T14:00:01Z",
                key_name="a",
                pre_snapshot=editable_snapshot(value=""),
                post_snapshot=editable_snapshot(value="abc"),
                is_editable=is_editable,
            ),
            [],
        )

        events = builder.process_event(
            event_type="mouse_click",
            timestamp_utc="2026-03-23T14:00:02Z",
            key_name=None,
            pre_snapshot=editable_snapshot(value="abc"),
            post_snapshot=button_snapshot(),
            is_editable=is_editable,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["previous_value"], None)
        self.assertEqual(events[0]["final_value"], "abc")
        self.assertEqual(events[0]["commit_reason"], "focus_lost")

    def test_commits_on_enter_and_restarts_session(self) -> None:
        builder = SemanticEventBuilder()

        builder.process_event(
            event_type="mouse_click",
            timestamp_utc="2026-03-23T14:01:00Z",
            key_name=None,
            pre_snapshot=None,
            post_snapshot=editable_snapshot(value="ciao"),
            is_editable=is_editable,
        )

        enter_events = builder.process_event(
            event_type="key_up",
            timestamp_utc="2026-03-23T14:01:01Z",
            key_name="Key.enter",
            pre_snapshot=editable_snapshot(value="ciao"),
            post_snapshot=editable_snapshot(value="ciao"),
            is_editable=is_editable,
        )

        self.assertEqual(len(enter_events), 0)

        builder.process_event(
            event_type="key_up",
            timestamp_utc="2026-03-23T14:01:02Z",
            key_name="x",
            pre_snapshot=editable_snapshot(value="ciao"),
            post_snapshot=editable_snapshot(value="ciaox"),
            is_editable=is_editable,
        )

        blur_events = builder.process_event(
            event_type="key_up",
            timestamp_utc="2026-03-23T14:01:03Z",
            key_name="Key.tab",
            pre_snapshot=editable_snapshot(value="ciaox"),
            post_snapshot=button_snapshot(),
            is_editable=is_editable,
        )

        self.assertEqual(len(blur_events), 1)
        self.assertEqual(blur_events[0]["previous_value"], "ciao")
        self.assertEqual(blur_events[0]["final_value"], "ciaox")


if __name__ == "__main__":
    unittest.main()
