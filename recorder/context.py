from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
from typing import Any

import psutil
from pywinauto import Desktop


# =========================
# Win32 constants / helpers
# =========================

HWINEVENTHOOK = wintypes.HANDLE
GA_PARENT = 1
GA_ROOT = 2
GA_ROOTOWNER = 3

user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND

user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND

user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindowEnabled.argtypes = [wintypes.HWND]
user32.IsWindowEnabled.restype = wintypes.BOOL

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
user32.GetDlgCtrlID.restype = ctypes.c_int
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
EM_GETSEL = 0x00B0
EM_GETREADONLY = 0x00CF
BM_GETCHECK = 0x00F0
BM_GETSTATE = 0x00F2
CB_GETCOUNT = 0x0146
CB_GETCURSEL = 0x0147
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149
CB_GETDROPPEDSTATE = 0x0157
LB_GETCURSEL = 0x0188
LB_GETTEXT = 0x0189
LB_GETTEXTLEN = 0x018A
LB_GETCOUNT = 0x018B

BST_UNCHECKED = 0x0000
BST_CHECKED = 0x0001
BST_INDETERMINATE = 0x0002

GWL_STYLE = -16
GWL_EXSTYLE = -20
BS_CHECKBOX = 0x00000002
BS_AUTOCHECKBOX = 0x00000003
BS_RADIOBUTTON = 0x00000004
BS_3STATE = 0x00000005
BS_AUTO3STATE = 0x00000006
BS_AUTORADIOBUTTON = 0x00000009


# =========================
# Data models
# =========================

@dataclass(slots=True)
class WindowInfo:
    title: str | None
    class_name: str | None
    handle: int | None
    pid: int | None
    process_name: str | None
    process_path: str | None
    is_visible: bool | None = None
    source: str | None = None


@dataclass(slots=True)
class ElementInfo:
    name: str | None
    automation_id: str | None
    control_type: str | None
    class_name: str | None
    handle: int | None
    rectangle: dict[str, int] | None
    parent_name: str | None
    parent_control_type: str | None

    # Useful for robust app/window association
    process_id: int | None = None
    process_name: str | None = None
    process_path: str | None = None
    framework_id: str | None = None

    top_level_name: str | None = None
    top_level_class_name: str | None = None
    top_level_handle: int | None = None
    top_level_pid: int | None = None
    top_level_process_name: str | None = None
    top_level_process_path: str | None = None
    ancestry: list[dict[str, Any]] | None = None


# =========================
# Resolver
# =========================

class UIContextResolver:
    RISKY_STATE_CAPTURE_CLASSES = {
        "combobox",
        "edit",
        "listbox",
        "maskedit",
        "richedit",
        "richedit20w",
        "richedit50w",
    }
    RISKY_STATE_CAPTURE_TYPES = {
        "combobox",
        "edit",
        "list",
        "listitem",
    }

    def __init__(self) -> None:
        self.desktop_uia = Desktop(backend="uia")
        self.desktop_win32 = Desktop(backend="win32")

    # -------------------------
    # Public API
    # -------------------------

    def get_active_window_info(self) -> WindowInfo | None:
        """
        Robust active window resolution:
        1) Win32 GetForegroundWindow
        2) pywinauto UIA get_active
        3) pywinauto win32 get_active
        """
        hwnd = self._get_foreground_root_hwnd()
        if hwnd:
            info = self._build_window_info_from_hwnd(hwnd, source="win32_foreground")
            if info is not None:
                return info

        for backend_name, desktop in (("uia", self.desktop_uia), ("win32", self.desktop_win32)):
            try:
                wrapper = desktop.get_active()
                info = self._extract_window_info_from_wrapper(wrapper, source=f"pywinauto_{backend_name}_active")
                if info is not None:
                    return info
            except Exception:
                continue

        return None

    def get_window_info_from_point(self, x: int, y: int) -> WindowInfo | None:
        """
        Best-effort mapping from screen coordinates to the owning top-level window.
        This is the most robust way to assign mouse events to a specific app/window.
        """
        hwnd = self._window_from_point_root_hwnd(x, y)
        if hwnd:
            info = self._build_window_info_from_hwnd(hwnd, source="win32_point")
            if info is not None:
                return info

        # Fallback to pywinauto top-level from point
        for backend_name, desktop in (("uia", self.desktop_uia), ("win32", self.desktop_win32)):
            try:
                wrapper = desktop.top_from_point(x, y)
                info = self._extract_window_info_from_wrapper(wrapper, source=f"pywinauto_{backend_name}_top_from_point")
                if info is not None:
                    return info
            except Exception:
                continue

        return None

    def get_element_from_point(self, x: int, y: int) -> ElementInfo | None:
        for desktop in (self.desktop_uia, self.desktop_win32):
            try:
                wrapper = desktop.from_point(x, y)
                return self._extract_element_info(wrapper, point_x=x, point_y=y)
            except Exception:
                continue
        return None

    def get_focused_element(self) -> ElementInfo | None:
        """
        Focus resolution is trickier across thread boundaries.
        We still try pywinauto active->get_focus first, then active wrapper itself.
        """
        for desktop in (self.desktop_uia, self.desktop_win32):
            try:
                active = desktop.get_active()
                if hasattr(active, "get_focus"):
                    try:
                        focused = active.get_focus()
                        info = self._extract_element_info(focused)
                        if info is not None:
                            return info
                    except Exception:
                        pass

                info = self._extract_element_info(active)
                if info is not None:
                    return info
            except Exception:
                continue
        return None

    def get_element_info_from_handle(self, hwnd: int | None) -> ElementInfo | None:
        wrapper = self._get_wrapper_from_handle(hwnd)
        if wrapper is not None:
            try:
                return self._extract_element_info(wrapper)
            except Exception:
                pass

        hwnd = self._safe_int(hwnd)
        if not hwnd:
            return None

        window = self._build_window_info_from_hwnd(hwnd, source="direct_handle")
        if window is None:
            return None

        return ElementInfo(
            name=self._get_control_text(hwnd),
            automation_id=self._safe_str(self._safe_call(lambda: user32.GetDlgCtrlID(hwnd))),
            control_type=None,
            class_name=window.class_name,
            handle=hwnd,
            rectangle=None,
            parent_name=None,
            parent_control_type=None,
            process_id=window.pid,
            process_name=window.process_name,
            process_path=window.process_path,
            framework_id=None,
            top_level_name=window.title,
            top_level_class_name=window.class_name,
            top_level_handle=window.handle,
            top_level_pid=window.pid,
            top_level_process_name=window.process_name,
            top_level_process_path=window.process_path,
            ancestry=None,
        )

    def get_wrapper_from_handle(self, hwnd: int | None) -> Any | None:
        return self._get_wrapper_from_handle(hwnd)

    def get_wrapper_from_point(self, x: int, y: int) -> Any | None:
        return self._get_wrapper_from_point(x, y)

    def get_focused_wrapper(self) -> Any | None:
        return self._get_focused_wrapper()

    def capture_state_from_point(self, x: int, y: int) -> dict[str, Any] | None:
        return self.capture_state_for_element(point=(x, y))

    def capture_state_for_element(
        self,
        element: ElementInfo | None = None,
        hwnd: int | None = None,
        point: tuple[int, int] | None = None,
        use_focused: bool = False,
    ) -> dict[str, Any] | None:
        wrapper = None
        resolved_hwnd = self._safe_int(hwnd)

        if resolved_hwnd is None and element is not None:
            resolved_hwnd = self._safe_int(element.handle) or self._safe_int(element.top_level_handle)

        if resolved_hwnd is not None:
            wrapper = self._get_wrapper_from_handle(resolved_hwnd)

        if wrapper is None and point is not None:
            point_x, point_y = point
            wrapper = self._get_wrapper_from_point(point_x, point_y)

        if wrapper is None and use_focused:
            wrapper = self._get_focused_wrapper()

        if wrapper is None and element is not None and element.handle is not None:
            resolved_hwnd = self._safe_int(element.handle)

        if wrapper is not None and resolved_hwnd is None:
            resolved_hwnd = self._safe_int(self._safe_getattr(wrapper, "handle"))
            if resolved_hwnd is None:
                resolved_hwnd = self._safe_int(
                    self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "handle")
                )

        snapshot = self._extract_control_state(wrapper, resolved_hwnd)
        if snapshot is None:
            return None

        if element is not None:
            snapshot.setdefault("top_level_handle", element.top_level_handle)
            snapshot.setdefault("top_level_name", element.top_level_name)
            snapshot.setdefault("top_level_pid", element.top_level_pid)

        return snapshot

    def capture_state_from_handle(self, hwnd: int | None) -> dict[str, Any] | None:
        return self.capture_state_for_element(hwnd=hwnd)

    def capture_focused_element_state(self) -> tuple[ElementInfo | None, dict[str, Any] | None]:
        wrapper = self._get_focused_wrapper()
        if wrapper is None:
            return None, None

        element = None
        try:
            element = self._extract_element_info(wrapper)
        except Exception:
            element = None

        hwnd = self._safe_int(self._safe_getattr(wrapper, "handle"))
        if hwnd is None:
            hwnd = self._safe_int(self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "handle"))

        state = self._extract_control_state(wrapper, hwnd)
        return element, state

    def capture_dialog_details(
        self,
        hwnd: int | None,
        *,
        max_controls: int = 24,
    ) -> dict[str, Any] | None:
        hwnd = self._safe_int(hwnd)
        if hwnd is None:
            return None

        window = self._build_window_info_from_hwnd(hwnd, source="dialog_handle")
        wrapper = self._get_wrapper_from_handle(hwnd)
        if window is None and wrapper is None:
            return None

        texts: list[str] = []
        buttons: list[str] = []
        controls = self._enumerate_wrapper_controls(wrapper, max_controls=max_controls)

        for control in controls:
            control_type = (control.get("control_type") or "").strip().lower()
            text = self._normalize_text_candidate(control.get("text") or control.get("name"))
            if not text:
                continue
            if control_type in {"button"}:
                buttons.append(text)
                continue
            if control_type in {"text", "label", "static", "document", "edit"}:
                texts.append(text)

        title = self._first_non_empty(
            getattr(window, "title", None),
            self._safe_call(lambda: wrapper.window_text()) if wrapper is not None else None,
        )
        normalized_title = self._normalize_text_candidate(title)
        message_parts = [text for text in texts if text != normalized_title]
        message = "\n".join(dict.fromkeys(message_parts)) or None

        return {
            "dialog_hwnd": hwnd,
            "dialog_title": normalized_title,
            "dialog_message": message,
            "available_buttons": list(dict.fromkeys(buttons)) or None,
            "dialog_type": self._classify_dialog_type(normalized_title, message),
            "controls_preview": controls or None,
        }

    def capture_ui_snapshot(
        self,
        hwnd: int | None,
        *,
        max_controls: int = 25,
    ) -> dict[str, Any] | None:
        hwnd = self._safe_int(hwnd)
        if hwnd is None:
            hwnd = self._get_foreground_root_hwnd()
        if hwnd is None:
            return None

        window = self._build_window_info_from_hwnd(hwnd, source="ui_snapshot")
        wrapper = self._get_wrapper_from_handle(hwnd)
        if window is None and wrapper is None:
            return None

        controls = self._enumerate_wrapper_controls(wrapper, max_controls=max_controls)
        return {
            "window": dataclass_to_dict(window),
            "visible_controls": controls or None,
            "control_count": len(controls),
            "max_controls": max_controls,
        }

    def read_uia_text(self, hwnd: int | None) -> str | None:
        wrapper = self._get_wrapper_from_handle(hwnd)
        if wrapper is None:
            return None
        value = self._first_non_empty(
            self._safe_call(lambda: wrapper.get_value()),
            self._safe_getattr(self._safe_getattr(wrapper, "iface_value"), "CurrentValue"),
            self._safe_getattr(self._safe_getattr(wrapper, "iface_range_value"), "CurrentValue"),
            self._safe_getattr(self._safe_getattr(wrapper, "iface_range_value"), "Value"),
            self._safe_call(lambda: wrapper.selected_text()),
            self._safe_call(lambda: wrapper.window_text()),
            self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "name"),
        )
        return self._normalize_text_candidate(value)

    def read_native_text(self, hwnd: int | None) -> str | None:
        hwnd = self._safe_int(hwnd)
        if hwnd is None:
            return None
        class_name = self._get_class_name(hwnd)
        state = self._capture_win32_specific_state(hwnd, class_name, self._get_window_long(hwnd, GWL_STYLE))
        value = self._first_non_empty(
            state.get("selected_text"),
            state.get("edit_text"),
            state.get("button_text"),
            self._get_control_text(hwnd),
        )
        return self._normalize_text_candidate(value)

    # -------------------------
    # Win32 core helpers
    # -------------------------

    def _get_foreground_root_hwnd(self) -> int | None:
        try:
            hwnd = int(user32.GetForegroundWindow() or 0)
            if not hwnd:
                return None
            return self._normalize_root_hwnd(hwnd)
        except Exception:
            return None

    def _window_from_point_root_hwnd(self, x: int, y: int) -> int | None:
        try:
            hwnd = int(user32.WindowFromPoint(POINT(x=x, y=y)) or 0)
            if not hwnd:
                return None
            return self._normalize_root_hwnd(hwnd)
        except Exception:
            return None

    def _normalize_root_hwnd(self, hwnd: int | None) -> int | None:
        if not hwnd:
            return None

        try:
            if not bool(user32.IsWindow(hwnd)):
                return None
        except Exception:
            return None

        # 1. Troviamo il GA_ROOT (il top-level fisico nell'albero parent/child)
        root = None
        try:
            root = int(user32.GetAncestor(hwnd, GA_ROOT) or 0)
        except Exception:
            pass

        # 2. Troviamo il GA_ROOTOWNER (il possessore logico)
        try:
            root_owner = int(user32.GetAncestor(hwnd, GA_ROOTOWNER) or 0)
            if root_owner:
                # FIX VB6: Accettiamo il Root Owner SOLO se è una finestra visibile.
                # Altrimenti, applicazioni legacy ci daranno proxy window nascoste con rect 0x0.
                if bool(user32.IsWindowVisible(root_owner)):
                    return root_owner
        except Exception:
            pass

        # 3. Fallback sul GA_ROOT se l'owner è nascosto o non esiste
        if root:
            return root

        return hwnd

    def _build_window_info_from_hwnd(self, hwnd: int | None, source: str) -> WindowInfo | None:
        if not hwnd:
            return None

        try:
            if not bool(user32.IsWindow(hwnd)):
                return None
        except Exception:
            return None

        hwnd = self._normalize_root_hwnd(hwnd)
        if not hwnd:
            return None

        pid = self._get_pid_from_hwnd(hwnd)
        process_name, process_path = self._get_process_info(pid)
        title = self._get_window_text(hwnd)
        class_name = self._get_class_name(hwnd)

        is_visible = None
        try:
            is_visible = bool(user32.IsWindowVisible(hwnd))
        except Exception:
            pass

        return WindowInfo(
            title=title,
            class_name=class_name,
            handle=int(hwnd),
            pid=pid,
            process_name=process_name,
            process_path=process_path,
            is_visible=is_visible,
            source=source,
        )

    def _extract_window_info_from_wrapper(self, wrapper: Any, source: str) -> WindowInfo | None:
        if wrapper is None:
            return None

        hwnd = self._safe_int(self._safe_getattr(wrapper, "handle"))
        if hwnd:
            info = self._build_window_info_from_hwnd(hwnd, source=source)
            if info is not None:
                return info

        title = self._safe_call(lambda: wrapper.window_text())
        class_name = self._safe_call(lambda: wrapper.class_name())

        pid = self._safe_call(lambda: int(wrapper.process_id()))
        if pid is None:
            pid = self._safe_int(self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "process_id"))

        process_name, process_path = self._get_process_info(pid)

        if not any([title, class_name, hwnd, pid, process_name, process_path]):
            return None

        return WindowInfo(
            title=title,
            class_name=class_name,
            handle=hwnd,
            pid=pid,
            process_name=process_name,
            process_path=process_path,
            is_visible=None,
            source=source,
        )

    # -------------------------
    # Element extraction
    # -------------------------

    def _extract_element_info(
        self,
        wrapper: Any,
        point_x: int | None = None,
        point_y: int | None = None,
    ) -> ElementInfo:
        name = self._first_non_empty(
            self._safe_call(lambda: wrapper.window_text()),
            self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "name"),
        )

        automation_id = self._first_non_empty(
            self._safe_call(lambda: wrapper.automation_id()),
            self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "automation_id"),
        )

        control_type = self._first_non_empty(
            self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "control_type"),
            self._safe_call(lambda: wrapper.friendly_class_name()),
        )

        class_name = self._first_non_empty(
            self._safe_call(lambda: wrapper.class_name()),
            self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "class_name"),
        )

        handle = self._safe_int(self._safe_getattr(wrapper, "handle"))
        if not handle:
            handle = self._safe_int(self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "handle"))

        rectangle = self._extract_rectangle(wrapper)

        parent = self._safe_call(lambda: wrapper.parent())
        parent_name = self._first_non_empty(
            self._safe_call(lambda: parent.window_text()) if parent is not None else None,
            self._safe_getattr(self._safe_getattr(parent, "element_info"), "name") if parent is not None else None,
        )
        parent_control_type = (
            self._safe_getattr(self._safe_getattr(parent, "element_info"), "control_type")
            if parent is not None
            else None
        )

        process_id = self._safe_call(lambda: int(wrapper.process_id()))
        if process_id is None:
            process_id = self._safe_int(self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "process_id"))

        process_name, process_path = self._get_process_info(process_id)

        framework_id = self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "framework_id")

        top_level_wrapper = self._safe_call(lambda: wrapper.top_level_parent())
        top_level_handle = self._safe_int(self._safe_getattr(top_level_wrapper, "handle")) if top_level_wrapper else None

        # If pywinauto didn't give a top-level handle, derive it from point or local handle.
        if not top_level_handle and point_x is not None and point_y is not None:
            top_level_handle = self._window_from_point_root_hwnd(point_x, point_y)
        if not top_level_handle and handle:
            top_level_handle = self._normalize_root_hwnd(handle)

        top_level_window = self._build_window_info_from_hwnd(top_level_handle, source="derived_top_level")
        if top_level_window is None and top_level_wrapper is not None:
            top_level_window = self._extract_window_info_from_wrapper(
                top_level_wrapper,
                source="pywinauto_top_level_parent",
            )

        ancestry = self._extract_ancestry(wrapper)

        return ElementInfo(
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            handle=handle,
            rectangle=rectangle,
            parent_name=parent_name,
            parent_control_type=parent_control_type,
            process_id=process_id,
            process_name=process_name,
            process_path=process_path,
            framework_id=framework_id,
            top_level_name=top_level_window.title if top_level_window else None,
            top_level_class_name=top_level_window.class_name if top_level_window else None,
            top_level_handle=top_level_window.handle if top_level_window else None,
            top_level_pid=top_level_window.pid if top_level_window else None,
            top_level_process_name=top_level_window.process_name if top_level_window else None,
            top_level_process_path=top_level_window.process_path if top_level_window else None,
            ancestry=ancestry,
        )

    def _extract_ancestry(self, wrapper: Any, max_depth: int = 5) -> list[dict[str, Any]] | None:
        chain: list[dict[str, Any]] = []
        current = wrapper

        for _ in range(max_depth):
            current = self._safe_call(lambda current=current: current.parent())
            if current is None:
                break

            name = self._first_non_empty(
                self._safe_call(lambda current=current: current.window_text()),
                self._safe_getattr(self._safe_getattr(current, "element_info"), "name"),
            )
            control_type = self._first_non_empty(
                self._safe_getattr(self._safe_getattr(current, "element_info"), "control_type"),
                self._safe_call(lambda current=current: current.friendly_class_name()),
            )
            class_name = self._first_non_empty(
                self._safe_call(lambda current=current: current.class_name()),
                self._safe_getattr(self._safe_getattr(current, "element_info"), "class_name"),
            )
            handle = self._safe_int(self._safe_getattr(current, "handle"))
            if handle is None:
                handle = self._safe_int(self._safe_getattr(self._safe_getattr(current, "element_info"), "handle"))

            chain.append(
                {
                    "name": name,
                    "control_type": control_type,
                    "class_name": class_name,
                    "handle": handle,
                }
            )

        return chain or None

    def _extract_control_state(self, wrapper: Any, hwnd: int | None) -> dict[str, Any] | None:
        hwnd = self._safe_int(hwnd)
        class_name = self._first_non_empty(
            self._safe_call(lambda: wrapper.class_name()) if wrapper is not None else None,
            self._get_class_name(hwnd),
        )
        control_type = self._first_non_empty(
            self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "control_type") if wrapper is not None else None,
            self._safe_call(lambda: wrapper.friendly_class_name()) if wrapper is not None else None,
        )
        control_text = self._first_non_empty(
            self._safe_call(lambda: wrapper.window_text()) if wrapper is not None else None,
            self._get_control_text(hwnd),
        )
        allow_wrapper_state = self._allow_wrapper_state_capture(class_name, control_type)
        texts_preview = self._extract_texts_preview(wrapper) if allow_wrapper_state else None
        style = self._get_window_long(hwnd, GWL_STYLE)
        ex_style = self._get_window_long(hwnd, GWL_EXSTYLE)
        control_id = self._get_dialog_control_id(hwnd)

        snapshot: dict[str, Any] = {
            "handle": hwnd,
            "class_name": class_name,
            "control_type": control_type,
            "control_id": control_id,
            "style": style,
            "ex_style": ex_style,
            "control_text": control_text,
            "texts_preview": texts_preview,
            "semantic_role": self._classify_semantic_role(class_name, control_type, style),
        }

        if hwnd is not None:
            snapshot["value_text"] = self._get_control_text(hwnd)

        snapshot.update(self._capture_basic_window_state(hwnd))
        if allow_wrapper_state:
            snapshot.update(self._capture_wrapper_specific_state(wrapper))
        snapshot.update(self._capture_win32_specific_state(hwnd, class_name, style))

        snapshot["value_text"] = self._first_non_empty(
            snapshot.get("selected_text"),
            snapshot.get("wrapper_value"),
            snapshot.get("control_text"),
            snapshot.get("edit_text"),
            snapshot.get("button_text"),
        )
        snapshot["non_empty"] = {
            key: value
            for key, value in snapshot.items()
            if value not in (None, "", [], {})
        }
        return snapshot

    def _capture_basic_window_state(self, hwnd: int | None) -> dict[str, Any]:
        if hwnd is None:
            return {}

        state: dict[str, Any] = {}

        try:
            state["is_visible"] = bool(user32.IsWindowVisible(hwnd))
        except Exception:
            pass

        try:
            state["is_enabled"] = bool(user32.IsWindowEnabled(hwnd))
        except Exception:
            pass

        return state

    def _capture_wrapper_specific_state(self, wrapper: Any) -> dict[str, Any]:
        if wrapper is None:
            return {}

        state: dict[str, Any] = {}

        wrapper_value = self._first_non_empty(
            self._safe_call(lambda: wrapper.get_value()),
            self._safe_getattr(self._safe_getattr(wrapper, "iface_value"), "CurrentValue"),
            self._safe_getattr(self._safe_getattr(wrapper, "iface_range_value"), "CurrentValue"),
            self._safe_getattr(self._safe_getattr(wrapper, "iface_range_value"), "Value"),
        )
        if wrapper_value not in (None, ""):
            state["wrapper_value"] = wrapper_value

        toggle_state = self._safe_getattr(self._safe_getattr(wrapper, "iface_toggle"), "CurrentToggleState")
        if toggle_state is not None:
            state["toggle_state"] = str(toggle_state)
            state["checked"] = str(toggle_state) in {"1", "ToggleState_On"}

        selection_items = self._safe_call(lambda: wrapper.selected_text())
        if selection_items not in (None, ""):
            state["selected_text"] = selection_items

        children_count = self._safe_call(lambda: len(wrapper.children()))
        if children_count is not None:
            state["children_count"] = children_count

        is_enabled = self._safe_call(lambda: wrapper.is_enabled())
        if is_enabled is not None:
            state["is_enabled"] = bool(is_enabled)

        is_visible = self._safe_call(lambda: wrapper.is_visible())
        if is_visible is not None:
            state["is_visible"] = bool(is_visible)

        has_focus = self._safe_call(lambda: wrapper.has_focus())
        if has_focus is not None:
            state["has_focus"] = bool(has_focus)

        return state

    def _capture_win32_specific_state(
        self,
        hwnd: int | None,
        class_name: str | None,
        style: int | None,
    ) -> dict[str, Any]:
        if hwnd is None:
            return {}

        normalized_class = (class_name or "").lower()
        state: dict[str, Any] = {}

        if normalized_class == "edit":
            edit_text = self._get_control_text(hwnd)
            selection_start, selection_end = self._get_edit_selection(hwnd)
            state.update(
                {
                    "edit_text": edit_text,
                    "selection_start": selection_start,
                    "selection_end": selection_end,
                    "is_read_only": self._get_edit_read_only(hwnd),
                }
            )

        if normalized_class == "button":
            button_kind = self._classify_button_kind(style)
            button_text = self._get_control_text(hwnd)
            state["button_kind"] = button_kind
            state["button_text"] = button_text
            if button_kind in {"checkbox", "radio", "tri_state"}:
                checked_state = self._get_button_check_state(hwnd)
                state["toggle_state"] = checked_state
                state["checked"] = checked_state == "checked"

        if normalized_class == "combobox":
            state.update(self._get_combobox_state(hwnd))

        if normalized_class == "listbox":
            state.update(self._get_listbox_state(hwnd))

        return state

    def _extract_texts_preview(self, wrapper: Any, max_items: int = 10) -> list[str] | None:
        if wrapper is None:
            return None
        values = self._safe_call(lambda: wrapper.texts())
        if not values:
            return None
        preview = [str(item) for item in values[:max_items] if str(item).strip()]
        return preview or None

    def _extract_rectangle(self, wrapper: Any) -> dict[str, int] | None:
        try:
            rect = wrapper.rectangle()
            return {
                "left": int(rect.left),
                "top": int(rect.top),
                "right": int(rect.right),
                "bottom": int(rect.bottom),
            }
        except Exception:
            try:
                rect = self._safe_getattr(self._safe_getattr(wrapper, "element_info"), "rectangle")
                if rect is None:
                    return None
                return {
                    "left": int(rect.left),
                    "top": int(rect.top),
                    "right": int(rect.right),
                    "bottom": int(rect.bottom),
                }
            except Exception:
                return None

    def _enumerate_wrapper_controls(
        self,
        wrapper: Any | None,
        *,
        max_controls: int,
    ) -> list[dict[str, Any]]:
        if wrapper is None or max_controls <= 0:
            return []

        results: list[dict[str, Any]] = []
        queue: list[tuple[Any, int | None]] = [(wrapper, None)]

        while queue and len(results) < max_controls:
            current, parent_handle = queue.pop(0)
            node = self._serialize_wrapper_control(current, parent_handle=parent_handle)
            if node is not None:
                results.append(node)

            children = self._safe_call(lambda current=current: current.children()) or []
            current_handle = node.get("handle") if node is not None else None
            for child in children:
                queue.append((child, current_handle))

        return results

    def _serialize_wrapper_control(
        self,
        wrapper: Any,
        *,
        parent_handle: int | None,
    ) -> dict[str, Any] | None:
        element = self._safe_getattr(wrapper, "element_info")
        handle = self._safe_int(
            self._safe_getattr(wrapper, "handle")
            or self._safe_getattr(element, "handle")
        )
        rect = self._extract_rectangle(wrapper)
        control_type = self._first_non_empty(
            self._safe_getattr(element, "control_type"),
            self._safe_call(lambda: wrapper.friendly_class_name()),
        )
        name = self._normalize_text_candidate(self._safe_getattr(element, "name"))
        text = self._normalize_text_candidate(self._safe_call(lambda: wrapper.window_text()))
        class_name = self._normalize_text_candidate(self._safe_call(lambda: wrapper.class_name()))
        automation_id = self._normalize_text_candidate(self._safe_getattr(element, "automation_id"))
        visible = self._safe_call(lambda: wrapper.is_visible())

        if visible is False:
            return None

        return {
            "handle": handle,
            "parent_handle": parent_handle,
            "name": name,
            "automation_id": automation_id,
            "control_type": self._normalize_text_candidate(control_type),
            "class_name": class_name,
            "text": text,
            "bounds": self._rect_to_bounds(rect),
            "enabled": self._safe_call(lambda: bool(wrapper.is_enabled())),
            "visible": bool(visible) if visible is not None else None,
            "focused": self._safe_call(lambda: bool(wrapper.has_focus())),
        }

    def _classify_dialog_type(
        self,
        title: str | None,
        message: str | None,
    ) -> str | None:
        haystack = " ".join(part for part in (title, message) if part).lower()
        if not haystack:
            return None
        if any(token in haystack for token in ("errore", "error", "incongruenza", "invalid", "failed")):
            return "error"
        if any(token in haystack for token in ("warning", "attenzione", "attenzione!", "avviso")):
            return "warning"
        if any(token in haystack for token in ("confirm", "conferma", "sicuro", "question", "domanda")):
            return "confirmation"
        if any(token in haystack for token in ("info", "informazione", "completed", "completato")):
            return "information"
        return "dialog"

    def _rect_to_bounds(self, rect: dict[str, Any] | None) -> dict[str, int] | None:
        if not rect:
            return None
        try:
            left = int(rect["left"])
            top = int(rect["top"])
            right = int(rect["right"])
            bottom = int(rect["bottom"])
        except Exception:
            return None
        return {
            "x": left,
            "y": top,
            "w": max(0, right - left),
            "h": max(0, bottom - top),
        }

    # -------------------------
    # Process / text / class helpers
    # -------------------------

    def _get_pid_from_hwnd(self, hwnd: int | None) -> int | None:
        if not hwnd:
            return None
        try:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            value = int(pid.value)
            return value if value > 0 else None
        except Exception:
            return None

    def _get_process_info(self, pid: int | None) -> tuple[str | None, str | None]:
        if not pid:
            return None, None
        try:
            proc = psutil.Process(pid)
            return proc.name(), proc.exe()
        except Exception:
            return None, None

    def _get_window_text(self, hwnd: int | None) -> str | None:
        if not hwnd:
            return None
        try:
            length = int(user32.GetWindowTextLengthW(hwnd))
            buf = ctypes.create_unicode_buffer(length + 1 if length > 0 else 512)
            copied = int(user32.GetWindowTextW(hwnd, buf, len(buf)))
            text = buf.value if copied >= 0 else ""
            text = text.strip()
            return text or None
        except Exception:
            return None

    def _get_class_name(self, hwnd: int | None) -> str | None:
        if not hwnd:
            return None
        try:
            buf = ctypes.create_unicode_buffer(256)
            copied = int(user32.GetClassNameW(hwnd, buf, len(buf)))
            text = buf.value if copied > 0 else ""
            text = text.strip()
            return text or None
        except Exception:
            return None

    def _get_control_text(self, hwnd: int | None) -> str | None:
        if not hwnd:
            return None
        try:
            length = int(user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0))
        except Exception:
            length = 0

        try:
            buf = ctypes.create_unicode_buffer(length + 1 if length > 0 else 512)
            user32.SendMessageW(hwnd, WM_GETTEXT, len(buf), ctypes.addressof(buf))
            text = buf.value.strip()
            if text:
                return text
        except Exception:
            pass

        return self._get_window_text(hwnd)

    def _get_window_long(self, hwnd: int | None, index: int) -> int | None:
        if not hwnd:
            return None
        try:
            return int(user32.GetWindowLongW(hwnd, index))
        except Exception:
            return None

    def _get_dialog_control_id(self, hwnd: int | None) -> int | None:
        if not hwnd:
            return None
        try:
            value = int(user32.GetDlgCtrlID(hwnd))
            return value if value >= 0 else None
        except Exception:
            return None

    def _get_edit_selection(self, hwnd: int) -> tuple[int | None, int | None]:
        start = wintypes.DWORD()
        end = wintypes.DWORD()
        try:
            user32.SendMessageW(
                hwnd,
                EM_GETSEL,
                ctypes.addressof(start),
                ctypes.addressof(end),
            )
            return int(start.value), int(end.value)
        except Exception:
            return None, None

    def _get_edit_read_only(self, hwnd: int) -> bool | None:
        try:
            return bool(user32.SendMessageW(hwnd, EM_GETREADONLY, 0, 0))
        except Exception:
            return None

    def _get_button_check_state(self, hwnd: int) -> str | None:
        try:
            value = int(user32.SendMessageW(hwnd, BM_GETCHECK, 0, 0))
        except Exception:
            return None

        mapping = {
            BST_UNCHECKED: "unchecked",
            BST_CHECKED: "checked",
            BST_INDETERMINATE: "indeterminate",
        }
        return mapping.get(value, f"state_{value}")

    def _get_combobox_state(self, hwnd: int) -> dict[str, Any]:
        count = self._send_message_int(hwnd, CB_GETCOUNT)
        selected_index = self._send_message_int(hwnd, CB_GETCURSEL)
        selected_text = self._get_combobox_item_text(hwnd, selected_index)
        return {
            "item_count": count if count is not None and count >= 0 else None,
            "selected_index": selected_index if selected_index is not None and selected_index >= 0 else None,
            "selected_text": selected_text,
            "is_expanded": bool(self._send_message_int(hwnd, CB_GETDROPPEDSTATE) or 0),
        }

    def _get_listbox_state(self, hwnd: int) -> dict[str, Any]:
        count = self._send_message_int(hwnd, LB_GETCOUNT)
        selected_index = self._send_message_int(hwnd, LB_GETCURSEL)
        selected_text = self._get_listbox_item_text(hwnd, selected_index)
        return {
            "item_count": count if count is not None and count >= 0 else None,
            "selected_index": selected_index if selected_index is not None and selected_index >= 0 else None,
            "selected_text": selected_text,
        }

    def _get_combobox_item_text(self, hwnd: int, index: int | None) -> str | None:
        if index is None or index < 0:
            return None
        length = self._send_message_int(hwnd, CB_GETLBTEXTLEN, index)
        if length is None or length < 0:
            return None
        try:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.SendMessageW(hwnd, CB_GETLBTEXT, index, ctypes.addressof(buf))
            text = buf.value.strip()
            return text or None
        except Exception:
            return None

    def _get_listbox_item_text(self, hwnd: int, index: int | None) -> str | None:
        if index is None or index < 0:
            return None
        length = self._send_message_int(hwnd, LB_GETTEXTLEN, index)
        if length is None or length < 0:
            return None
        try:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.SendMessageW(hwnd, LB_GETTEXT, index, ctypes.addressof(buf))
            text = buf.value.strip()
            return text or None
        except Exception:
            return None

    def _send_message_int(self, hwnd: int | None, message: int, wparam: int = 0, lparam: int = 0) -> int | None:
        if not hwnd:
            return None
        try:
            return int(user32.SendMessageW(hwnd, message, wparam, lparam))
        except Exception:
            return None

    def _classify_semantic_role(
        self,
        class_name: str | None,
        control_type: str | None,
        style: int | None,
    ) -> str | None:
        normalized_class = (class_name or "").lower()
        normalized_type = (control_type or "").lower()

        if normalized_class == "edit" or normalized_type == "edit":
            return "text_input"
        if normalized_class == "combobox" or normalized_type == "combobox":
            return "selection"
        if normalized_class == "listbox" or normalized_type in {"list", "listitem"}:
            return "list_selection"
        if normalized_class == "button":
            return self._classify_button_kind(style)
        if normalized_type in {"table", "datagrid", "pane"}:
            return "grid_or_container"
        return normalized_type or normalized_class or None

    def _classify_button_kind(self, style: int | None) -> str:
        button_type = (style or 0) & 0x0F
        if button_type in {BS_CHECKBOX, BS_AUTOCHECKBOX}:
            return "checkbox"
        if button_type in {BS_RADIOBUTTON, BS_AUTORADIOBUTTON}:
            return "radio"
        if button_type in {BS_3STATE, BS_AUTO3STATE}:
            return "tri_state"
        return "button"

    def _allow_wrapper_state_capture(
        self,
        class_name: str | None,
        control_type: str | None,
    ) -> bool:
        normalized_class = (class_name or "").strip().lower()
        normalized_type = (control_type or "").strip().lower()

        if normalized_class in self.RISKY_STATE_CAPTURE_CLASSES:
            return False
        if normalized_type in self.RISKY_STATE_CAPTURE_TYPES:
            return False
        if "thunder" in normalized_class or "vb" in normalized_class:
            return False
        if "thunder" in normalized_type or "vb" in normalized_type:
            return False
        return True

    def _get_wrapper_from_handle(self, hwnd: int | None) -> Any | None:
        hwnd = self._safe_int(hwnd)
        if not hwnd:
            return None

        for desktop in (self.desktop_uia, self.desktop_win32):
            try:
                wrapper = desktop.window(handle=hwnd).wrapper_object()
                if wrapper is not None:
                    return wrapper
            except Exception:
                continue
        return None

    def _get_wrapper_from_point(self, x: int, y: int) -> Any | None:
        for desktop in (self.desktop_uia, self.desktop_win32):
            try:
                wrapper = desktop.from_point(x, y)
                if wrapper is not None:
                    return wrapper
            except Exception:
                continue
        return None

    def _get_focused_wrapper(self) -> Any | None:
        for desktop in (self.desktop_uia, self.desktop_win32):
            try:
                active = desktop.get_active()
                if hasattr(active, "get_focus"):
                    focused = self._safe_call(lambda: active.get_focus())
                    if focused is not None:
                        return focused
                if active is not None:
                    return active
            except Exception:
                continue
        return None

    # -------------------------
    # Generic safe helpers
    # -------------------------

    def _safe_call(self, fn: Any) -> Any | None:
        try:
            return fn()
        except Exception:
            return None

    def _safe_getattr(self, obj: Any, attr: str) -> Any | None:
        try:
            return getattr(obj, attr, None)
        except Exception:
            return None

    def _safe_int(self, value: Any) -> int | None:
        try:
            if value in (None, 0, "0", ""):
                return None
            return int(value)
        except Exception:
            return None

    def _safe_str(self, value: Any) -> str | None:
        if value is None:
            return None
        try:
            text = str(value).strip()
        except Exception:
            return None
        return text or None

    def _normalize_text_candidate(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            joined = ", ".join(str(item).strip() for item in value if str(item).strip())
            return joined or None
        return self._safe_str(value)

    def _first_non_empty(self, *values: Any) -> Any | None:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return None


def dataclass_to_dict(obj: Any | None) -> dict[str, Any] | None:
    if obj is None:
        return None
    return asdict(obj)
