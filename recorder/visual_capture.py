from __future__ import annotations

import ctypes
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import ImageGrab


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
    _user32.GetWindowRect.restype = ctypes.c_int
except Exception:
    _user32 = None


ImageGrabber = Callable[[tuple[int, int, int, int]], Any]

_SAFE_EVENT_RE = re.compile(r"[^a-z0-9_]+")


@dataclass(slots=True)
class VisualCheckpointConfig:
    enabled: bool = True
    on_click: bool | None = True
    on_input_commit: bool | None = True
    on_runtime_change: bool | None = True

    def click_enabled(self) -> bool:
        return self.enabled and (self.on_click if self.on_click is not None else True)

    def input_commit_enabled(self) -> bool:
        return self.enabled and (self.on_input_commit if self.on_input_commit is not None else True)

    def runtime_change_enabled(self) -> bool:
        return self.enabled and (self.on_runtime_change if self.on_runtime_change is not None else True)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "on_click": self.click_enabled(),
            "on_input_commit": self.input_commit_enabled(),
            "on_runtime_change": self.runtime_change_enabled(),
        }


class EventSequence:
    def __init__(self, start: int = 0) -> None:
        self._value = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._value += 1
            return self._value


class VisualCaptureManager:
    RUNTIME_EVENT_TYPES = {
        "event_system_dialogstart",
        "event_system_foreground",
        "event_object_valuechange",
        "event_object_statechange",
    }

    def __init__(
        self,
        *,
        session_dir: Path,
        config: VisualCheckpointConfig | None = None,
        event_sequence: EventSequence | None = None,
        image_grabber: ImageGrabber | None = None,
    ) -> None:
        self.session_dir = Path(session_dir)
        self.config = config or VisualCheckpointConfig()
        self.event_sequence = event_sequence or EventSequence()
        self.image_grabber = image_grabber or self._default_grabber
        self._manifest_lock = threading.Lock()
        self.artifacts_dir = self.session_dir / "artifacts"
        self.screenshots_dir = self.artifacts_dir / "screenshots"
        self.crops_dir = self.artifacts_dir / "crops"
        self.manifest_path = self.session_dir / "visual_artifacts.jsonl"

        if self.config.enabled:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            self.crops_dir.mkdir(parents=True, exist_ok=True)

    def should_capture_raw(self, event_type: str, payload: dict[str, Any]) -> bool:
        return self.config.click_enabled() and event_type == "mouse_click" and payload.get("pressed") is False

    def should_capture_semantic(self, event_type: str) -> bool:
        return self.config.input_commit_enabled() and event_type == "input_commit"

    def should_capture_runtime(self, payload: dict[str, Any]) -> bool:
        if not self.config.runtime_change_enabled():
            return False
        event_type = str(payload.get("event_type") or "").strip().lower()
        if event_type in self.RUNTIME_EVENT_TYPES:
            return True
        return event_type == "event_object_show" and bool(((payload.get("raw") or {}).get("is_window_object")))

    def capture_for_event(
        self,
        *,
        event_type: str,
        timestamp_utc: str | None,
        ui_target: dict[str, Any] | None = None,
        window_info: dict[str, Any] | None = None,
        hwnd: int | None = None,
        window_title: str | None = None,
        process_name: str | None = None,
        capture_stage: str = "after",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.config.enabled:
            return None

        sequence = self.event_sequence.next()
        safe_event_type = self._safe_event_name(event_type)
        resolved_hwnd = self._first_int(
            hwnd,
            (window_info or {}).get("handle"),
            (ui_target or {}).get("hwnd"),
            (ui_target or {}).get("handle"),
        )
        resolved_window_bounds = self._normalize_bounds((window_info or {}).get("bounds"))
        if resolved_window_bounds is None:
            resolved_window_bounds = self._get_window_bounds(resolved_hwnd)
        resolved_control_bounds = self._normalize_bounds((ui_target or {}).get("bounds"))

        payload: dict[str, Any] = {
            "enabled": True,
            "event_sequence": sequence,
            "window_image_path": None,
            "control_image_path": None,
            "capture_scope": "none",
            "capture_stage": capture_stage,
            "window_bounds": list(resolved_window_bounds) if resolved_window_bounds is not None else None,
            "control_bounds": list(resolved_control_bounds) if resolved_control_bounds is not None else None,
            "capture_success": False,
            "capture_error": None,
            "window_image_width": None,
            "window_image_height": None,
            "window_image_sha256": None,
            "control_image_width": None,
            "control_image_height": None,
            "control_image_sha256": None,
            "window_title": window_title or (window_info or {}).get("title") or (ui_target or {}).get("window_title"),
            "process_name": process_name or (window_info or {}).get("process_name") or (ui_target or {}).get("process_name"),
            "hwnd": resolved_hwnd,
            "control_identity_key": self._control_identity_key(ui_target),
        }

        try:
            if resolved_window_bounds is None:
                raise RuntimeError("window bounds unavailable")

            window_image = self.image_grabber(resolved_window_bounds)
            screenshot_filename = f"{sequence:06d}_{safe_event_type}_window.png"
            screenshot_path = self.screenshots_dir / screenshot_filename
            window_stats = self._save_image(window_image, screenshot_path)
            payload["window_image_path"] = self._relative_path(screenshot_path)
            payload["window_image_width"] = window_stats["width"]
            payload["window_image_height"] = window_stats["height"]
            payload["window_image_sha256"] = window_stats["sha256"]
            payload["capture_scope"] = "window"
            payload["capture_success"] = True

            if self._can_crop_control(resolved_window_bounds, resolved_control_bounds):
                crop_box = (
                    resolved_control_bounds[0] - resolved_window_bounds[0],
                    resolved_control_bounds[1] - resolved_window_bounds[1],
                    resolved_control_bounds[2] - resolved_window_bounds[0],
                    resolved_control_bounds[3] - resolved_window_bounds[1],
                )
                control_image = window_image.crop(crop_box)
                control_filename = f"{sequence:06d}_{safe_event_type}_control.png"
                control_path = self.crops_dir / control_filename
                control_stats = self._save_image(control_image, control_path)
                payload["control_image_path"] = self._relative_path(control_path)
                payload["control_image_width"] = control_stats["width"]
                payload["control_image_height"] = control_stats["height"]
                payload["control_image_sha256"] = control_stats["sha256"]
                payload["capture_scope"] = "window+control"
        except Exception as exc:
            payload["capture_success"] = False
            payload["capture_error"] = self._short_error(exc)

        self._append_manifest(
            {
                "event_sequence": sequence,
                "timestamp_utc": timestamp_utc,
                "event_type": event_type,
                "capture_stage": capture_stage,
                "capture_success": payload["capture_success"],
                "window_image_path": payload["window_image_path"],
                "control_image_path": payload["control_image_path"],
                "window_bounds": payload["window_bounds"],
                "control_bounds": payload["control_bounds"],
                "window_title": payload["window_title"],
                "process_name": payload["process_name"],
                "hwnd": payload["hwnd"],
                "metadata": metadata or {},
            }
        )
        return payload

    def _append_manifest(self, entry: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        with self._manifest_lock:
            with self.manifest_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _save_image(self, image: Any, path: Path) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")
        data = path.read_bytes()
        width, height = image.size
        return {
            "width": int(width),
            "height": int(height),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.session_dir).as_posix()

    def _default_grabber(self, bbox: tuple[int, int, int, int]) -> Any:
        return ImageGrab.grab(bbox=bbox, all_screens=True)

    def _get_window_bounds(self, hwnd: int | None) -> tuple[int, int, int, int] | None:
        if hwnd is None or _user32 is None:
            return None
        rect = RECT()
        try:
            if not _user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
                return None
        except Exception:
            return None
        bounds = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        return bounds if self._valid_bounds(bounds) else None

    def _can_crop_control(
        self,
        window_bounds: tuple[int, int, int, int] | None,
        control_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        if window_bounds is None or control_bounds is None:
            return False
        wx1, wy1, wx2, wy2 = window_bounds
        cx1, cy1, cx2, cy2 = control_bounds
        return wx1 <= cx1 < cx2 <= wx2 and wy1 <= cy1 < cy2 <= wy2

    def _normalize_bounds(self, bounds: Any) -> tuple[int, int, int, int] | None:
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
            return None
        try:
            normalized = tuple(int(value) for value in bounds)
        except (TypeError, ValueError):
            return None
        return normalized if self._valid_bounds(normalized) else None

    def _valid_bounds(self, bounds: tuple[int, int, int, int]) -> bool:
        left, top, right, bottom = bounds
        return right > left and bottom > top

    def _first_int(self, *values: Any) -> int | None:
        for value in values:
            try:
                if value is None:
                    continue
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def _safe_event_name(self, event_type: str) -> str:
        normalized = str(event_type or "event").strip().lower().replace("-", "_").replace(" ", "_")
        normalized = _SAFE_EVENT_RE.sub("_", normalized).strip("_")
        return normalized or "event"

    def _control_identity_key(self, ui_target: dict[str, Any] | None) -> str | None:
        if not ui_target:
            return None
        candidates = [
            ui_target.get("control_id"),
            ui_target.get("automation_id"),
            ui_target.get("handle"),
            ui_target.get("control_name"),
            ui_target.get("label"),
        ]
        for candidate in candidates:
            if candidate in (None, ""):
                continue
            return str(candidate)
        return None

    def _short_error(self, exc: Exception) -> str:
        return str(exc).strip()[:200] or exc.__class__.__name__
