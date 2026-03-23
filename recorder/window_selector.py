from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import psutil
import win32con
import win32gui
import win32process


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process_name: str
    class_name: str | None = None
    process_path: str | None = None

    @property
    def display_name(self) -> str:
        return f"{self.process_name} [pid={self.pid}, hwnd={self.hwnd}] — {self.title}"


def _normalize_root_hwnd(hwnd: int) -> int | None:
    if not hwnd:
        return None
    try:
        hwnd = int(win32gui.GetAncestor(hwnd, win32con.GA_ROOTOWNER) or hwnd)
    except Exception:
        pass
    try:
        hwnd = int(win32gui.GetAncestor(hwnd, win32con.GA_ROOT) or hwnd)
    except Exception:
        pass
    return hwnd or None


def _is_real_user_window(hwnd: int) -> bool:
    hwnd = _normalize_root_hwnd(hwnd)
    if not hwnd:
        return False

    if not win32gui.IsWindowVisible(hwnd):
        return False

    title = win32gui.GetWindowText(hwnd)
    if not title or not title.strip():
        return False

    if win32gui.GetParent(hwnd) != 0:
        return False

    try:
        ex_style = int(win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE))
        if ex_style & win32con.WS_EX_TOOLWINDOW:
            return False
    except Exception:
        pass

    return True


def list_open_windows() -> List[WindowInfo]:
    results: List[WindowInfo] = []

    def callback(hwnd: int, _: object) -> None:
        hwnd = _normalize_root_hwnd(hwnd)
        if not _is_real_user_window(hwnd):
            return

        title = win32gui.GetWindowText(hwnd).strip()

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process = psutil.Process(pid)
            process_name = process.name()
            process_path = process.exe()
        except Exception:
            return

        results.append(
            WindowInfo(
                hwnd=hwnd,
                title=title,
                pid=pid,
                process_name=process_name,
                class_name=_safe_get_class_name(hwnd),
                process_path=process_path,
            )
        )

    win32gui.EnumWindows(callback, None)

    unique = {}
    for item in results:
        key = item.hwnd
        unique[key] = item

    ordered = sorted(
        unique.values(),
        key=lambda x: (x.process_name.lower(), x.title.lower())
    )
    return ordered


def find_window_by_display_name(display_name: str) -> Optional[WindowInfo]:
    for item in list_open_windows():
        if item.display_name == display_name:
            return item
    return None


def refresh_window_reference(window: WindowInfo) -> Optional[WindowInfo]:
    current_windows = list_open_windows()

    for item in current_windows:
        if item.hwnd == window.hwnd:
            return item

    for item in current_windows:
        if item.pid == window.pid and item.title == window.title:
            return item

    for item in current_windows:
        if item.pid == window.pid:
            return item

    for item in current_windows:
        if item.process_name == window.process_name and item.title == window.title:
            return item

    return None


def _safe_get_class_name(hwnd: int) -> str | None:
    try:
        value = win32gui.GetClassName(hwnd)
    except Exception:
        return None
    value = value.strip()
    return value or None
