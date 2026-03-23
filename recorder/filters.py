from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from recorder.context import ElementInfo, WindowInfo


@dataclass(slots=True)
class WindowCandidate:
    title: str | None = None
    class_name: str | None = None
    handle: int | None = None
    pid: int | None = None
    process_name: str | None = None


@dataclass(slots=True)
class WindowFilter:
    title_contains: str | None = None
    title_regex: str | None = None
    process_name: str | None = None
    pid: int | None = None
    hwnd: int | None = None

    def has_constraints(self) -> bool:
        return any(
            [
                self.title_contains,
                self.title_regex,
                self.process_name,
                self.pid is not None,
                self.hwnd is not None,
            ]
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "title_contains": self.title_contains,
            "title_regex": self.title_regex,
            "process_name": self.process_name,
            "pid": self.pid,
            "hwnd": self.hwnd,
        }

    def matches_window(self, window: Any | None) -> bool:
        if not self.has_constraints():
            return True
        if window is None:
            return False
        return self._matches_any([self._window_candidate_from_obj(window)])

    def matches(
        self,
        window: WindowInfo | None,
        target_element: ElementInfo | None = None,
    ) -> bool:
        if not self.has_constraints():
            return True
        return self._matches_any(self._iter_candidates(window, target_element))

    def _matches_any(self, candidates: Iterable[WindowCandidate]) -> bool:
        normalized_candidates = [candidate for candidate in candidates if candidate is not None]
        if not normalized_candidates:
            return False
        return any(self._matches_candidate(candidate) for candidate in normalized_candidates)

    def _matches_candidate(self, candidate: WindowCandidate) -> bool:
        if self.hwnd is not None and candidate.handle == self.hwnd:
            return True

        if self.pid is not None:
            if candidate.pid != self.pid:
                return False
            if self.process_name and not self._matches_process_name(candidate.process_name):
                return False
            return True

        if self.process_name:
            if not self._matches_process_name(candidate.process_name):
                return False
            if self.title_contains or self.title_regex:
                return self._matches_title(candidate.title)
            return True

        if self.title_contains or self.title_regex:
            return self._matches_title(candidate.title)

        return False

    def _matches_title(self, title: str | None) -> bool:
        if not (self.title_contains or self.title_regex):
            return True

        value = (title or "").strip()
        if not value:
            return False

        if self.title_contains and self.title_contains.lower() not in value.lower():
            return False

        if self.title_regex and re.search(self.title_regex, value) is None:
            return False

        return True

    def _matches_process_name(self, process_name: str | None) -> bool:
        if not self.process_name:
            return True
        value = (process_name or "").strip()
        if not value:
            return False
        return value.lower() == self.process_name.lower()

    def _iter_candidates(
        self,
        window: WindowInfo | None,
        target_element: ElementInfo | None,
    ) -> list[WindowCandidate]:
        candidates: list[WindowCandidate] = []

        if window is not None:
            candidates.append(self._window_candidate_from_obj(window))

        if target_element is not None:
            candidates.append(
                WindowCandidate(
                    title=target_element.top_level_name,
                    class_name=target_element.top_level_class_name,
                    handle=target_element.top_level_handle,
                    pid=target_element.top_level_pid,
                    process_name=target_element.top_level_process_name,
                )
            )
            candidates.append(
                WindowCandidate(
                    title=target_element.top_level_name,
                    class_name=target_element.class_name,
                    handle=target_element.handle,
                    pid=target_element.process_id,
                    process_name=target_element.process_name,
                )
            )

        unique: dict[tuple[Any, ...], WindowCandidate] = {}
        for candidate in candidates:
            key = (
                candidate.handle,
                candidate.pid,
                (candidate.process_name or "").lower(),
                (candidate.title or "").lower(),
            )
            unique[key] = candidate

        return list(unique.values())

    def _window_candidate_from_obj(self, window: Any) -> WindowCandidate:
        return WindowCandidate(
            title=getattr(window, "title", None),
            class_name=getattr(window, "class_name", None),
            handle=getattr(window, "handle", None),
            pid=getattr(window, "pid", None),
            process_name=getattr(window, "process_name", None),
        )
