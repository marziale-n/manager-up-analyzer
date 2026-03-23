from __future__ import annotations

import re
from typing import Any

from recorder.context import ElementInfo, UIContextResolver, WindowInfo, dataclass_to_dict


class UIElementResolver:
    """Builds a stable, JSON-friendly UI target from point/focus/handle context."""

    GRID_CONTROL_TYPES = {"datagrid", "grid", "table"}
    GRID_CONTAINER_TYPES = {"pane", "group", "custom", "list", "listitem", "dataitem"}
    LABEL_CONTROL_TYPES = {"text", "label", "static", "edit"}
    EDITABLE_TYPES = {
        "combobox",
        "custom",
        "datepicker",
        "document",
        "edit",
        "pane",
        "spinner",
    }
    EDITABLE_CLASSES = {
        "combobox",
        "datepick",
        "edit",
        "maskedit",
        "richedit",
        "richedit20w",
        "richedit50w",
        "thundertextbox",
    }

    def __init__(self, context: UIContextResolver | None = None) -> None:
        self.context = context or UIContextResolver()

    def resolve_point_snapshot(
        self,
        x: int,
        y: int,
        *,
        window: WindowInfo | None = None,
        element: ElementInfo | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if window is None:
            window = self.context.get_window_info_from_point(x, y)
        if element is None:
            element = self.context.get_element_from_point(x, y)
        if state is None:
            state = self.context.capture_state_for_element(element=element, point=(x, y))
        wrapper = self.context.get_wrapper_from_point(x, y)
        return self._build_snapshot(window=window, element=element, state=state, wrapper=wrapper, point=(x, y))

    def resolve_focus_snapshot(self) -> dict[str, Any]:
        window = self.context.get_active_window_info()
        element, state = self.context.capture_focused_element_state()
        if element is None:
            element = self.context.get_focused_element()
            if state is None and element is not None:
                state = self.context.capture_state_for_element(element=element, use_focused=True)
        wrapper = self.context.get_focused_wrapper()
        return self._build_snapshot(window=window, element=element, state=state, wrapper=wrapper)

    def resolve_handle_snapshot(
        self,
        hwnd: int | None,
        *,
        window: WindowInfo | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        element = self.context.get_element_info_from_handle(hwnd)
        resolved_hwnd = self._coalesce_hwnd(hwnd, getattr(element, "top_level_handle", None), getattr(element, "handle", None))
        if window is None:
            window = self.context.get_active_window_info()
        if window is None or (resolved_hwnd is not None and getattr(window, "handle", None) != resolved_hwnd):
            window = self._window_info_from_element(element)
        if state is None:
            state = self.context.capture_state_from_handle(hwnd)
        wrapper = self.context.get_wrapper_from_handle(hwnd)
        return self._build_snapshot(window=window, element=element, state=state, wrapper=wrapper, hwnd_hint=resolved_hwnd)

    def build_ui_target(
        self,
        *,
        window: WindowInfo | None,
        element: ElementInfo | None,
        state: dict[str, Any] | None,
        wrapper: Any | None = None,
        point: tuple[int, int] | None = None,
        hwnd_hint: int | None = None,
    ) -> dict[str, Any]:
        label = self._resolve_label(element=element, state=state, wrapper=wrapper)
        text_value = self.extract_text_value(state=state, element=element)
        bounds = self._rect_to_bounds(getattr(element, "rectangle", None))
        control_id = self._normalize_control_id(state.get("control_id") if state else None)
        automation_id = self._clean_string(getattr(element, "automation_id", None))
        handle = self._coalesce_hwnd(getattr(element, "handle", None), hwnd_hint)
        grid_context = self._extract_grid_context(wrapper=wrapper, element=element, state=state)

        ui_target = {
            "control_name": self._clean_string(getattr(element, "name", None)),
            "control_id": control_id,
            "automation_id": automation_id,
            "control_type": self._clean_string(getattr(element, "control_type", None)),
            "class_name": self._clean_string(getattr(element, "class_name", None)),
            "label": label,
            "text": text_value,
            "value": text_value,
            "bounds": bounds,
            "handle": handle,
            "window_title": self._window_title(window, element),
            "process_name": self._process_name(window, element),
            "hwnd": self._window_hwnd(window, element, hwnd_hint=hwnd_hint),
            "grid_context": grid_context,
        }

        return {key: ui_target.get(key) for key in ui_target}

    def extract_text_value(
        self,
        *,
        state: dict[str, Any] | None,
        element: ElementInfo | None = None,
    ) -> str | None:
        candidates: list[Any] = []
        if state:
            candidates.extend(
                [
                    state.get("value_text"),
                    state.get("selected_text"),
                    state.get("wrapper_value"),
                    state.get("control_text"),
                    state.get("edit_text"),
                    state.get("button_text"),
                    state.get("selected_item_text"),
                ]
            )
        if element is not None:
            candidates.append(getattr(element, "name", None))

        for value in candidates:
            if value is None:
                continue
            if isinstance(value, list):
                joined = ", ".join(str(item).strip() for item in value if str(item).strip())
                if joined:
                    return joined
                continue
            text = self._clean_string(value)
            if text:
                return text
        return None

    def is_editable_target(
        self,
        ui_target: dict[str, Any] | None,
        state: dict[str, Any] | None,
    ) -> bool:
        if not ui_target:
            return False

        control_type = (ui_target.get("control_type") or "").strip().lower()
        class_name = (ui_target.get("class_name") or "").strip().lower()
        semantic_role = ((state or {}).get("semantic_role") or "").strip().lower()

        if semantic_role == "text_input":
            return True
        if control_type in self.EDITABLE_TYPES:
            return True
        if class_name in self.EDITABLE_CLASSES:
            return True
        if control_type == "pane" and class_name in self.EDITABLE_CLASSES:
            return True
        return False

    def build_event_context(
        self,
        *,
        window: WindowInfo | None,
        element: ElementInfo | None,
        state: dict[str, Any] | None,
        wrapper: Any | None = None,
        point: tuple[int, int] | None = None,
        hwnd_hint: int | None = None,
    ) -> dict[str, Any]:
        ui_target = self.build_ui_target(
            window=window,
            element=element,
            state=state,
            wrapper=wrapper,
            point=point,
            hwnd_hint=hwnd_hint,
        )
        return self._build_snapshot(
            window=window,
            element=element,
            state=state,
            wrapper=wrapper,
            point=point,
            hwnd_hint=hwnd_hint,
            ui_target=ui_target,
        )

    def _build_snapshot(
        self,
        *,
        window: WindowInfo | None,
        element: ElementInfo | None,
        state: dict[str, Any] | None,
        wrapper: Any | None,
        point: tuple[int, int] | None = None,
        hwnd_hint: int | None = None,
        ui_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ui_target = ui_target or self.build_ui_target(
            window=window,
            element=element,
            state=state,
            wrapper=wrapper,
            point=point,
            hwnd_hint=hwnd_hint,
        )
        return {
            "window": window,
            "element": element,
            "state": state,
            "ui_target": ui_target,
            "window_title": ui_target.get("window_title"),
            "process_name": ui_target.get("process_name"),
            "hwnd": ui_target.get("hwnd"),
            "value": self.extract_text_value(state=state, element=element),
            "element_dict": dataclass_to_dict(element),
        }

    def _resolve_label(
        self,
        *,
        element: ElementInfo | None,
        state: dict[str, Any] | None,
        wrapper: Any | None,
    ) -> str | None:
        control_type = self._clean_string(getattr(element, "control_type", None))
        class_name = self._clean_string(getattr(element, "class_name", None))
        current_value = self.extract_text_value(state=state, element=element)
        editable_like = self.is_editable_target(
            {
                "control_type": control_type,
                "class_name": class_name,
            },
            state,
        )

        if editable_like:
            sibling_label = self._resolve_label_from_siblings(wrapper)
            if sibling_label:
                return sibling_label

            candidate_name = self._clean_string(getattr(element, "name", None))
            if candidate_name and candidate_name != current_value:
                return candidate_name
            return self._clean_string(getattr(element, "parent_name", None))

        direct_label = self._first_non_empty(
            self._clean_string(getattr(element, "name", None)),
            self._clean_string((state or {}).get("control_text")),
            self._clean_string((state or {}).get("button_text")),
        )
        if direct_label:
            return direct_label

        sibling_label = self._resolve_label_from_siblings(wrapper)
        if sibling_label:
            return sibling_label

        return self._clean_string(getattr(element, "parent_name", None))

    def _resolve_label_from_siblings(self, wrapper: Any | None) -> str | None:
        if wrapper is None:
            return None

        parent = self._safe_call(lambda: wrapper.parent())
        if parent is None:
            return None

        target_rect = self._extract_rect_from_wrapper(wrapper)
        if target_rect is None:
            return None

        candidates: list[tuple[int, str]] = []
        siblings = self._safe_call(lambda: parent.children()) or []
        for sibling in siblings:
            if sibling is wrapper:
                continue
            control_type = self._clean_string(self._safe_getattr(self._safe_getattr(sibling, "element_info"), "control_type"))
            class_name = self._clean_string(self._safe_call(lambda sibling=sibling: sibling.class_name()))
            normalized_type = (control_type or class_name or "").lower()
            if normalized_type not in self.LABEL_CONTROL_TYPES:
                continue

            sibling_text = self._first_non_empty(
                self._clean_string(self._safe_call(lambda sibling=sibling: sibling.window_text())),
                self._clean_string(self._safe_getattr(self._safe_getattr(sibling, "element_info"), "name")),
            )
            if not sibling_text:
                continue

            sibling_rect = self._extract_rect_from_wrapper(sibling)
            if sibling_rect is None:
                continue

            if sibling_rect["right"] <= target_rect["left"] + 12:
                distance = abs(target_rect["left"] - sibling_rect["right"])
            elif sibling_rect["bottom"] <= target_rect["top"] + 8:
                distance = abs(target_rect["top"] - sibling_rect["bottom"]) + 20
            else:
                continue
            candidates.append((distance, sibling_text))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _extract_grid_context(
        self,
        *,
        wrapper: Any | None,
        element: ElementInfo | None,
        state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        ancestry = list(getattr(element, "ancestry", None) or [])
        chain = [
            {
                "name": self._clean_string(getattr(element, "name", None)),
                "control_type": self._clean_string(getattr(element, "control_type", None)),
            }
        ]
        chain.extend(ancestry)

        grid_container = None
        for item in chain:
            control_type = (item.get("control_type") or "").lower()
            if control_type in self.GRID_CONTROL_TYPES | self.GRID_CONTAINER_TYPES:
                grid_container = item
                break

        row = self._safe_pattern_value(self._safe_getattr(self._safe_getattr(wrapper, "iface_grid_item"), "CurrentRow"))
        column = self._safe_pattern_value(self._safe_getattr(self._safe_getattr(wrapper, "iface_grid_item"), "CurrentColumn"))

        label_candidates = [
            self._clean_string(self._safe_getattr(self._safe_getattr(wrapper, "iface_table_item"), "CurrentColumnHeaderItems")),
            self._clean_string(self._safe_getattr(self._safe_getattr(wrapper, "iface_table_item"), "CurrentRowHeaderItems")),
        ]
        column_label = next((value for value in label_candidates if value), None)
        cell_value = self.extract_text_value(state=state, element=element)

        name = self._clean_string(grid_container.get("name")) if grid_container else None
        control_type = self._clean_string(grid_container.get("control_type")) if grid_container else None
        if not any([name, control_type, row, column, column_label, cell_value]):
            return None

        resolved_column = column_label or self._normalize_column(column)
        return {
            "grid_name": name,
            "grid_type": control_type,
            "row": self._normalize_row(row),
            "column": resolved_column,
            "cell_value": cell_value,
        }

    def _normalize_row(self, row: Any) -> int | None:
        try:
            if row in (None, ""):
                return None
            return int(row)
        except Exception:
            match = re.search(r"(\d+)", str(row))
            return int(match.group(1)) if match else None

    def _normalize_column(self, column: Any) -> str | None:
        if column in (None, ""):
            return None
        text = self._clean_string(column)
        if text:
            return text
        try:
            return str(int(column))
        except Exception:
            return None

    def _window_title(self, window: WindowInfo | None, element: ElementInfo | None) -> str | None:
        return self._first_non_empty(
            getattr(window, "title", None),
            getattr(element, "top_level_name", None),
        )

    def _process_name(self, window: WindowInfo | None, element: ElementInfo | None) -> str | None:
        return self._first_non_empty(
            getattr(window, "process_name", None),
            getattr(element, "top_level_process_name", None),
            getattr(element, "process_name", None),
        )

    def _window_hwnd(
        self,
        window: WindowInfo | None,
        element: ElementInfo | None,
        *,
        hwnd_hint: int | None,
    ) -> int | None:
        return self._coalesce_hwnd(
            getattr(window, "handle", None),
            getattr(element, "top_level_handle", None),
            hwnd_hint,
            getattr(element, "handle", None),
        )

    def _window_info_from_element(self, element: ElementInfo | None) -> WindowInfo | None:
        if element is None:
            return None
        return WindowInfo(
            title=self._clean_string(getattr(element, "top_level_name", None)),
            class_name=self._clean_string(getattr(element, "top_level_class_name", None)),
            handle=self._coalesce_hwnd(getattr(element, "top_level_handle", None)),
            pid=self._coalesce_hwnd(getattr(element, "top_level_pid", None)),
            process_name=self._clean_string(getattr(element, "top_level_process_name", None)),
            process_path=self._clean_string(getattr(element, "top_level_process_path", None)),
            is_visible=None,
            source="element_top_level",
        )

    def _normalize_control_id(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        try:
            return str(int(value))
        except Exception:
            return self._clean_string(value)

    def _rect_to_bounds(self, rect: dict[str, Any] | None) -> list[int] | None:
        if not rect:
            return None
        try:
            return [
                int(rect["left"]),
                int(rect["top"]),
                int(rect["right"]),
                int(rect["bottom"]),
            ]
        except Exception:
            return None

    def _extract_rect_from_wrapper(self, wrapper: Any) -> dict[str, int] | None:
        try:
            rect = wrapper.rectangle()
            return {
                "left": int(rect.left),
                "top": int(rect.top),
                "right": int(rect.right),
                "bottom": int(rect.bottom),
            }
        except Exception:
            return None

    def _coalesce_hwnd(self, *values: Any) -> int | None:
        for value in values:
            try:
                if value in (None, "", 0, "0"):
                    continue
                return int(value)
            except Exception:
                continue
        return None

    def _safe_pattern_value(self, value: Any) -> Any | None:
        if value in (None, ""):
            return None
        if isinstance(value, (str, int, float)):
            return value
        try:
            return str(value)
        except Exception:
            return None

    def _clean_string(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            pieces = [self._clean_string(item) for item in value]
            filtered = [piece for piece in pieces if piece]
            return ", ".join(filtered) if filtered else None
        try:
            text = str(value).strip()
        except Exception:
            return None
        return text or None

    def _first_non_empty(self, *values: Any) -> Any | None:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return None

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
