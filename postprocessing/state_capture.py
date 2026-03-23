from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class StateSnapshot:
    snapshot_id: int
    timestamp_utc: str
    event_id: str
    event_type: str
    window: dict[str, Any] | None
    target: dict[str, Any] | None
    observed_state: dict[str, Any]


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


def is_semantic_click(event: dict[str, Any]) -> bool:
    return (
        event.get("event_type") == "mouse_click"
        and safe_get(event, "payload", "pressed") is True
    )


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
        "source": window.get("source"),
    }


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
        "process_id": target.get("process_id"),
        "process_name": target.get("process_name"),
        "process_path": target.get("process_path"),
        "framework_id": target.get("framework_id"),
        "top_level_name": target.get("top_level_name"),
        "top_level_class_name": target.get("top_level_class_name"),
        "top_level_handle": target.get("top_level_handle"),
        "top_level_pid": target.get("top_level_pid"),
        "top_level_process_name": target.get("top_level_process_name"),
        "top_level_process_path": target.get("top_level_process_path"),
    }


def normalize_text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def build_target_descriptor(target: dict[str, Any] | None) -> str | None:
    if not target:
        return None

    return (
        target.get("automation_id")
        or target.get("name")
        or target.get("control_type")
        or target.get("class_name")
    )


def build_window_descriptor(window: dict[str, Any] | None, target: dict[str, Any] | None) -> str | None:
    if window:
        return (
            window.get("title")
            or window.get("process_name")
            or window.get("class_name")
        )

    if target:
        return (
            target.get("top_level_name")
            or target.get("top_level_process_name")
        )

    return None


def is_result_like_control(target: dict[str, Any] | None) -> bool:
    if not target:
        return False

    automation_id = str(target.get("automation_id") or "").lower()
    name = str(target.get("name") or "").lower()
    control_type = str(target.get("control_type") or "").lower()

    result_markers = [
        "result",
        "results",
        "display",
        "screen",
        "output",
    ]

    if any(marker in automation_id for marker in result_markers):
        return True
    if any(marker in name for marker in result_markers):
        return True
    if control_type in {"text", "edit", "document"} and name:
        return True

    return False


def extract_observed_state(payload: dict[str, Any]) -> dict[str, Any]:
    target = build_target(payload)
    window = build_window(payload)

    target_name = normalize_text_value(payload.get("target_name"))
    target_type = normalize_text_value(payload.get("target_type"))

    text_value_if_any = None
    if target is not None:
        text_value_if_any = normalize_text_value(target.get("name"))

    observed_state = {
        "target_descriptor": build_target_descriptor(target),
        "window_descriptor": build_window_descriptor(window, target),
        "text_value_if_any": text_value_if_any,
        "is_result_like_control": is_result_like_control(target),
        "matches_window_filter": payload.get("matches_window_filter"),
        "coordinates": {
            "x": payload.get("x"),
            "y": payload.get("y"),
        },
        "mouse_button": payload.get("button"),
        "target_name": target_name,
        "target_type": target_type,
    }

    return observed_state


def build_snapshots(events: list[dict[str, Any]]) -> list[StateSnapshot]:
    snapshots: list[StateSnapshot] = []
    snapshot_id = 1

    for event in events:
        if not is_semantic_click(event):
            continue

        payload = event.get("payload", {})
        window = build_window(payload)
        target = build_target(payload)
        observed_state = extract_observed_state(payload)

        snapshots.append(
            StateSnapshot(
                snapshot_id=snapshot_id,
                timestamp_utc=event.get("timestamp_utc"),
                event_id=event.get("event_id"),
                event_type=event.get("event_type"),
                window=window,
                target=target,
                observed_state=observed_state,
            )
        )
        snapshot_id += 1

    return snapshots


def write_snapshots(snapshots: list[StateSnapshot], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        json.dump([asdict(snapshot) for snapshot in snapshots], f, ensure_ascii=False, indent=2)


def write_state_report(snapshots: list[StateSnapshot], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# State Capture Report")
    lines.append("")
    lines.append(f"Total snapshots: {len(snapshots)}")
    lines.append("")

    current_window = None
    for snapshot in snapshots:
        window_desc = (
            (snapshot.window or {}).get("title")
            or snapshot.observed_state.get("window_descriptor")
            or "Unknown Window"
        )
        if window_desc != current_window:
            current_window = window_desc
            lines.append(f"## Window: {window_desc}")
            lines.append("")

        target_desc = (
            snapshot.observed_state.get("target_descriptor")
            or "unknown_target"
        )
        text_value = snapshot.observed_state.get("text_value_if_any")
        result_like = snapshot.observed_state.get("is_result_like_control")

        suffix = ""
        if text_value:
            suffix += f" | text='{text_value}'"
        if result_like:
            suffix += " | result_like_control=true"

        lines.append(
            f"- Snapshot {snapshot.snapshot_id}: target={target_desc}{suffix}"
        )

    lines.append("")

    with output_file.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build lightweight state snapshots from events.jsonl")
    parser.add_argument("--events", required=True, help="Path to events.jsonl")
    parser.add_argument("--snapshots-out", help="Output path for state_snapshots.json")
    parser.add_argument("--report-out", help="Output path for state_report.md")
    args = parser.parse_args()

    events_file = Path(args.events)
    if not events_file.exists():
        raise FileNotFoundError(f"Events file not found: {events_file}")

    session_dir = events_file.parent
    snapshots_out = (
        Path(args.snapshots_out)
        if args.snapshots_out
        else session_dir / "state_snapshots.json"
    )
    report_out = (
        Path(args.report_out)
        if args.report_out
        else session_dir / "state_report.md"
    )

    events = load_events(events_file)
    snapshots = build_snapshots(events)

    write_snapshots(snapshots, snapshots_out)
    write_state_report(snapshots, report_out)

    print(f"Loaded events: {len(events)}")
    print(f"Generated snapshots: {len(snapshots)}")
    print(f"Snapshots written to: {snapshots_out}")
    print(f"Report written to: {report_out}")


if __name__ == "__main__":
    main()