from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


TEXT_SPECIAL_KEYS = {
    "Key.space": " ",
    "Key.tab": "\t",
    "Key.enter": "\n",
}

MODIFIER_KEYS = {
    "Key.ctrl",
    "Key.ctrl_l",
    "Key.ctrl_r",
    "Key.alt",
    "Key.alt_l",
    "Key.alt_r",
    "Key.shift",
    "Key.shift_l",
    "Key.shift_r",
    "Key.cmd",
}


@dataclass
class Step:
    step_id: int
    timestamp_utc: str
    action: str
    target: dict[str, Any] | None
    window: dict[str, Any] | None
    data: dict[str, Any]


def load_events(events_file: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with events_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def safe_get(d: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = d
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def build_target(payload: dict[str, Any]) -> dict[str, Any] | None:
    target = payload.get("target_element")
    if not isinstance(target, dict):
        return None

    return {
        "name": target.get("name"),
        "automation_id": target.get("automation_id"),
        "control_type": target.get("control_type"),
        "class_name": target.get("class_name"),
        "handle": target.get("handle"),
        "rectangle": target.get("rectangle"),
        "parent_name": target.get("parent_name"),
        "parent_control_type": target.get("parent_control_type"),
        "top_level_name": target.get("top_level_name"),
        "top_level_handle": target.get("top_level_handle"),
        "top_level_process_name": target.get("top_level_process_name"),
    }


def build_window(payload: dict[str, Any]) -> dict[str, Any] | None:
    window = payload.get("window")
    if not isinstance(window, dict):
        return None

    return {
        "title": window.get("title"),
        "class_name": window.get("class_name"),
        "handle": window.get("handle"),
        "pid": window.get("pid"),
        "process_name": window.get("process_name"),
        "process_path": window.get("process_path"),
    }


def is_mouse_click_press(event: dict[str, Any]) -> bool:
    return (
        event.get("event_type") == "mouse_click"
        and safe_get(event, "payload", "pressed") is True
    )


def normalize_key(key: str | None) -> str | None:
    if key is None:
        return None
    return str(key)


def key_to_text(key: str | None) -> str | None:
    if key is None:
        return None

    if len(key) == 1:
        return key

    if key in TEXT_SPECIAL_KEYS:
        return TEXT_SPECIAL_KEYS[key]

    if key == "Key.backspace":
        return "__BACKSPACE__"

    return None


def is_modifier_key(key: str | None) -> bool:
    return key in MODIFIER_KEYS


def read_modifiers(payload: dict[str, Any]) -> list[str]:
    keyboard_state = payload.get("keyboard_state")
    if not isinstance(keyboard_state, dict):
        return []
    modifiers = keyboard_state.get("modifiers")
    if not isinstance(modifiers, list):
        return []
    return [str(x) for x in modifiers]


def extract_click_step(event: dict[str, Any], step_id: int) -> Step:
    payload = event.get("payload", {})
    target = build_target(payload)
    window = build_window(payload)

    data = {
        "x": payload.get("x"),
        "y": payload.get("y"),
        "button": payload.get("button"),
        "matches_window_filter": payload.get("matches_window_filter"),
        "target_name": payload.get("target_name"),
        "target_type": payload.get("target_type"),
    }

    return Step(
        step_id=step_id,
        timestamp_utc=event.get("timestamp_utc"),
        action="click",
        target=target,
        window=window,
        data=data,
    )


def extract_key_sequence(
    events: list[dict[str, Any]],
    start_index: int,
    step_id: int,
) -> tuple[Step | None, int]:
    event = events[start_index]
    if event.get("event_type") != "key_down":
        return None, start_index + 1

    payload = event.get("payload", {})
    key = normalize_key(payload.get("key"))
    modifiers = read_modifiers(payload)

    if is_modifier_key(key):
        return None, start_index + 1

    # Hotkey candidate
    if modifiers and key not in {"Key.esc"}:
        target = build_target(payload)
        window = build_window(payload)

        step = Step(
            step_id=step_id,
            timestamp_utc=event.get("timestamp_utc"),
            action="hotkey",
            target=target,
            window=window,
            data={
                "key": key,
                "modifiers": modifiers,
                "matches_window_filter": payload.get("matches_window_filter"),
            },
        )
        return step, start_index + 1

    # Text typing aggregation
    chars: list[str] = []
    idx = start_index

    target = build_target(payload)
    window = build_window(payload)
    first_timestamp = event.get("timestamp_utc")

    while idx < len(events):
        current = events[idx]
        if current.get("event_type") != "key_down":
            break

        current_payload = current.get("payload", {})
        current_key = normalize_key(current_payload.get("key"))
        current_modifiers = read_modifiers(current_payload)

        if is_modifier_key(current_key):
            idx += 1
            continue

        if current_modifiers:
            break

        text_piece = key_to_text(current_key)
        if text_piece is None:
            break

        if text_piece == "__BACKSPACE__":
            if chars:
                chars.pop()
        else:
            chars.append(text_piece)

        idx += 1

    if not chars:
        return None, start_index + 1

    step = Step(
        step_id=step_id,
        timestamp_utc=first_timestamp,
        action="type_text",
        target=target,
        window=window,
        data={
            "text": "".join(chars),
            "length": len(chars),
            "matches_window_filter": payload.get("matches_window_filter"),
        },
    )

    return step, idx


def extract_grid_update_step(event: dict[str, Any], step_id: int) -> Step:
    changes = event.get("changes", [])
    target = build_target(event)
    window = build_window(event)
    
    # Riassunto dei cambiamenti
    summary = []
    for change in changes[:10]: # Limita a 10 per non ingolfare il report
        name = change.get("name") or f"Cell {change.get('index')}"
        summary.append(f"{name}: {change.get('before')} -> {change.get('after')}")
    
    if len(changes) > 10:
        summary.append(f"... and {len(changes) - 10} more changes")

    data = {
        "changes": changes,
        "summary": "\n".join(summary),
        "count": len(changes),
    }

    return Step(
        step_id=step_id,
        timestamp_utc=event.get("timestamp_utc"),
        action="grid_update",
        target=target,
        window=window,
        data=data,
    )


def build_steps(events: list[dict[str, Any]]) -> list[Step]:
    steps: list[Step] = []
    step_id = 1
    i = 0

    while i < len(events):
        event = events[i]
        event_type = event.get("event_type")

        if event_type == "grid_update":
            steps.append(extract_grid_update_step(event, step_id))
            step_id += 1
            i += 1
            continue

        if is_mouse_click_press(event):
            steps.append(extract_click_step(event, step_id))
            step_id += 1
            i += 1
            continue

        if event_type == "key_down":
            step, next_i = extract_key_sequence(events, i, step_id)
            if step is not None:
                steps.append(step)
                step_id += 1
                i = next_i
                continue

        i += 1

    return steps


def write_steps(steps: list[Step], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        json.dump([asdict(step) for step in steps], f, ensure_ascii=False, indent=2)


def render_step(step: Step) -> str:
    target = step.target or {}
    window = step.window or {}

    target_desc = (
        target.get("automation_id")
        or target.get("name")
        or target.get("control_type")
        or "unknown_target"
    )

    window_desc = window.get("title") or window.get("process_name") or "unknown_window"

    if step.action == "click":
        return f"{step.step_id}. CLICK on '{target_desc}' in '{window_desc}'"
    if step.action == "type_text":
        return f"{step.step_id}. TYPE '{step.data.get('text', '')}' in '{window_desc}'"
    if step.action == "hotkey":
        mods = "+".join(step.data.get("modifiers", []))
        key = step.data.get("key", "")
        combo = f"{mods}+{key}" if mods else key
        return f"{step.step_id}. HOTKEY {combo} in '{window_desc}'"
    if step.action == "grid_update":
        return f"{step.step_id}. GRID UPDATE in '{target_desc}':\n    " + step.data.get("summary", "").replace("\n", "\n    ")

    return f"{step.step_id}. {step.action}"


def write_report(steps: list[Step], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Test Execution Report")
    lines.append("")
    lines.append(f"Total semantic steps: {len(steps)}")
    lines.append("")

    current_window = None
    for step in steps:
        window_title = (step.window or {}).get("title") or "Unknown Window"
        if window_title != current_window:
            current_window = window_title
            lines.append(f"## Window: {window_title}")
            lines.append("")
        lines.append(f"- {render_step(step)}")

    lines.append("")

    with output_file.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build semantic steps from events.jsonl")
    parser.add_argument("--events", required=True, help="Path to events.jsonl")
    parser.add_argument("--steps-out", help="Output path for steps.json")
    parser.add_argument("--report-out", help="Output path for report.md")
    args = parser.parse_args()

    events_file = Path(args.events)
    if not events_file.exists():
        raise FileNotFoundError(f"Events file not found: {events_file}")

    session_dir = events_file.parent
    steps_out = Path(args.steps_out) if args.steps_out else session_dir / "steps.json"
    report_out = Path(args.report_out) if args.report_out else session_dir / "report.md"

    events = load_events(events_file)
    steps = build_steps(events)

    write_steps(steps, steps_out)
    write_report(steps, report_out)

    print(f"Loaded events: {len(events)}")
    print(f"Generated steps: {len(steps)}")
    print(f"Steps written to: {steps_out}")
    print(f"Report written to: {report_out}")


if __name__ == "__main__":
    main()