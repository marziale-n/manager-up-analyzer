from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from recorder.visual_capture import EventSequence, VisualCaptureManager, VisualCheckpointConfig


class VisualCaptureManagerTests(unittest.TestCase):
    def test_disabled_feature_produces_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = VisualCaptureManager(
                session_dir=Path(tmp),
                config=VisualCheckpointConfig(enabled=False),
            )

            payload = manager.capture_for_event(
                event_type="mouse_click",
                timestamp_utc="2026-03-23T14:00:00Z",
                ui_target={"bounds": [10, 10, 30, 30]},
                window_info={"bounds": [0, 0, 100, 100]},
            )

            self.assertIsNone(payload)
            self.assertFalse((Path(tmp) / "artifacts").exists())

    def test_click_capture_saves_window_image_with_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = VisualCaptureManager(
                session_dir=Path(tmp),
                config=VisualCheckpointConfig(enabled=True),
                event_sequence=EventSequence(),
                image_grabber=lambda bbox: Image.new("RGB", (bbox[2] - bbox[0], bbox[3] - bbox[1]), "white"),
            )

            payload = manager.capture_for_event(
                event_type="mouse_click",
                timestamp_utc="2026-03-23T14:00:00Z",
                ui_target={"bounds": [10, 10, 30, 30], "control_id": "btnOk"},
                window_info={"bounds": [0, 0, 100, 100], "title": "Demo", "process_name": "demo.exe"},
                hwnd=123,
            )

            self.assertTrue(payload["capture_success"])
            self.assertEqual(payload["event_sequence"], 1)
            self.assertEqual(payload["capture_scope"], "window+control")
            self.assertEqual(payload["window_image_path"], "artifacts/screenshots/000001_mouse_click_window.png")
            self.assertEqual(payload["control_image_path"], "artifacts/crops/000001_mouse_click_control.png")
            self.assertTrue((Path(tmp) / payload["window_image_path"]).exists())
            self.assertTrue((Path(tmp) / payload["control_image_path"]).exists())

    def test_input_commit_with_missing_control_bounds_keeps_window_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = VisualCaptureManager(
                session_dir=Path(tmp),
                config=VisualCheckpointConfig(enabled=True),
                image_grabber=lambda bbox: Image.new("RGB", (bbox[2] - bbox[0], bbox[3] - bbox[1]), "blue"),
            )

            payload = manager.capture_for_event(
                event_type="input_commit",
                timestamp_utc="2026-03-23T14:00:01Z",
                ui_target={"control_id": "txtDescrizione"},
                window_info={"bounds": [100, 100, 220, 180]},
            )

            self.assertTrue(payload["capture_success"])
            self.assertEqual(payload["capture_scope"], "window")
            self.assertIsNone(payload["control_image_path"])

    def test_capture_failure_is_reported_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = VisualCaptureManager(
                session_dir=Path(tmp),
                config=VisualCheckpointConfig(enabled=True),
                image_grabber=lambda bbox: (_ for _ in ()).throw(RuntimeError("grab failed")),
            )

            payload = manager.capture_for_event(
                event_type="event_object_valuechange",
                timestamp_utc="2026-03-23T14:00:02Z",
                ui_target={"bounds": [10, 10, 20, 20]},
                window_info={"bounds": [0, 0, 50, 50]},
            )

            self.assertFalse(payload["capture_success"])
            self.assertEqual(payload["capture_scope"], "none")
            self.assertEqual(payload["window_image_path"], None)
            self.assertIn("grab failed", payload["capture_error"])

    def test_manifest_tracks_generated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = VisualCaptureManager(
                session_dir=Path(tmp),
                config=VisualCheckpointConfig(enabled=True),
                image_grabber=lambda bbox: Image.new("RGB", (bbox[2] - bbox[0], bbox[3] - bbox[1]), "green"),
            )

            payload = manager.capture_for_event(
                event_type="mouse_click",
                timestamp_utc="2026-03-23T14:00:03Z",
                ui_target={"bounds": [10, 10, 20, 20]},
                window_info={"bounds": [0, 0, 40, 40]},
            )

            manifest_lines = (Path(tmp) / "visual_artifacts.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest_lines), 1)
            entry = json.loads(manifest_lines[0])
            self.assertEqual(entry["event_sequence"], payload["event_sequence"])
            self.assertEqual(entry["window_image_path"], payload["window_image_path"])


if __name__ == "__main__":
    unittest.main()
