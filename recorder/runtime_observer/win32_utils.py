from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
from typing import Any

import psutil


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HWINEVENTHOOK = wintypes.HANDLE
GA_PARENT = 1
GA_ROOT = 2
GA_ROOTOWNER = 3

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MENUSTART = 0x0004
EVENT_SYSTEM_MENUEND = 0x0005
EVENT_SYSTEM_DIALOGSTART = 0x0010
EVENT_SYSTEM_DIALOGEND = 0x0011
EVENT_SYSTEM_CAPTURESTART = 0x0008
EVENT_SYSTEM_CAPTUREEND = 0x0009
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_FOCUS = 0x8005
EVENT_OBJECT_NAMECHANGE = 0x800C
EVENT_OBJECT_VALUECHANGE = 0x800E
EVENT_OBJECT_STATECHANGE = 0x800A
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_REORDER = 0x8004

WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0x00000000

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x00000102


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


WinEventProcType = ctypes.WINFUNCTYPE(
    None,
    HWINEVENTHOOK,
    wintypes.DWORD,
    wintypes.HWND,
    ctypes.c_long,
    ctypes.c_long,
    wintypes.DWORD,
    wintypes.DWORD,
)


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.SetWinEventHook.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HMODULE,
    WinEventProcType,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
]
user32.SetWinEventHook.restype = HWINEVENTHOOK
user32.UnhookWinEvent.argtypes = [HWINEVENTHOOK]
user32.UnhookWinEvent.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = wintypes.LPARAM

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
user32.WaitForInputIdle.argtypes = [wintypes.HANDLE, wintypes.DWORD]
user32.WaitForInputIdle.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


@dataclass(slots=True)
class WindowIdentity:
    title: str | None
    class_name: str | None
    handle: int | None
    pid: int | None
    process_name: str | None
    process_path: str | None
    visible: bool | None = None


def dataclass_to_dict(obj: Any | None) -> dict[str, Any] | None:
    if obj is None:
        return None
    return asdict(obj)


def safe_int(value: Any) -> int | None:
    try:
        if value in (None, 0, "", "0"):
            return None
        return int(value)
    except Exception:
        return None


def is_window(hwnd: int | None) -> bool:
    if not hwnd:
        return False
    try:
        return bool(user32.IsWindow(hwnd))
    except Exception:
        return False


def normalize_root_hwnd(hwnd: int | None) -> int | None:
    if not hwnd or not is_window(hwnd):
        return None
    try:
        root_owner = int(user32.GetAncestor(hwnd, GA_ROOTOWNER) or 0)
        if root_owner:
            hwnd = root_owner
    except Exception:
        pass
    try:
        root = int(user32.GetAncestor(hwnd, GA_ROOT) or 0)
        if root:
            hwnd = root
    except Exception:
        pass
    return hwnd if is_window(hwnd) else None


def get_foreground_hwnd() -> int | None:
    try:
        hwnd = int(user32.GetForegroundWindow() or 0)
    except Exception:
        return None
    return normalize_root_hwnd(hwnd)


def window_from_point(x: int, y: int) -> int | None:
    try:
        hwnd = int(user32.WindowFromPoint(POINT(x=x, y=y)) or 0)
    except Exception:
        return None
    return normalize_root_hwnd(hwnd)


def get_pid_from_hwnd(hwnd: int | None) -> int | None:
    if not hwnd or not is_window(hwnd):
        return None
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:
        return None


def get_window_text(hwnd: int | None) -> str | None:
    if not hwnd or not is_window(hwnd):
        return None
    try:
        length = int(user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(length + 1 if length > 0 else 512)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        text = buffer.value.strip()
        return text or None
    except Exception:
        return None


def get_class_name(hwnd: int | None) -> str | None:
    if not hwnd or not is_window(hwnd):
        return None
    try:
        buffer = ctypes.create_unicode_buffer(256)
        copied = int(user32.GetClassNameW(hwnd, buffer, len(buffer)))
        if copied <= 0:
            return None
        text = buffer.value.strip()
        return text or None
    except Exception:
        return None


def get_process_info(pid: int | None) -> tuple[str | None, str | None]:
    if not pid:
        return None, None
    try:
        proc = psutil.Process(pid)
        return proc.name(), proc.exe()
    except Exception:
        return None, None


def build_window_identity(hwnd: int | None) -> WindowIdentity | None:
    hwnd = normalize_root_hwnd(hwnd)
    if not hwnd:
        return None
    pid = get_pid_from_hwnd(hwnd)
    process_name, process_path = get_process_info(pid)
    visible = None
    try:
        visible = bool(user32.IsWindowVisible(hwnd))
    except Exception:
        pass
    return WindowIdentity(
        title=get_window_text(hwnd),
        class_name=get_class_name(hwnd),
        handle=hwnd,
        pid=pid,
        process_name=process_name,
        process_path=process_path,
        visible=visible,
    )


def event_name(event_id: int) -> str:
    mapping = {
        EVENT_SYSTEM_FOREGROUND: "foreground_changed",
        EVENT_SYSTEM_MENUSTART: "menu_start",
        EVENT_SYSTEM_MENUEND: "menu_end",
        EVENT_SYSTEM_DIALOGSTART: "dialog_start",
        EVENT_SYSTEM_DIALOGEND: "dialog_end",
        EVENT_SYSTEM_CAPTURESTART: "capture_start",
        EVENT_SYSTEM_CAPTUREEND: "capture_end",
        EVENT_OBJECT_SHOW: "object_show",
        EVENT_OBJECT_HIDE: "object_hide",
        EVENT_OBJECT_FOCUS: "object_focus",
        EVENT_OBJECT_NAMECHANGE: "object_name_change",
        EVENT_OBJECT_VALUECHANGE: "object_value_change",
        EVENT_OBJECT_STATECHANGE: "object_state_change",
        EVENT_OBJECT_LOCATIONCHANGE: "object_location_change",
        EVENT_OBJECT_REORDER: "object_reorder",
    }
    return mapping.get(event_id, f"win_event_{event_id}")


def pump_messages_once() -> None:
    msg = MSG()
    PM_REMOVE = 0x0001
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def wait_for_input_idle(pid: int | None, timeout_ms: int = 50) -> str | None:
    if not pid:
        return None
    handle = None
    try:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not handle:
            return None
        result = int(user32.WaitForInputIdle(handle, timeout_ms))
        if result == 0:
            return "idle"
        if result == WAIT_TIMEOUT:
            return "busy_or_timeout"
        return f"status_{result}"
    except Exception:
        return None
    finally:
        if handle:
            kernel32.CloseHandle(handle)
