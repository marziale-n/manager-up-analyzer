from __future__ import annotations

import argparse
import time
import uuid
from datetime import datetime
from pathlib import Path
from threading import Event

from recorder.filters import WindowFilter
from recorder.recorder import InteractionRecorder
from recorder.runtime_observer.runtime_manager import RuntimeObserverManager
from recorder.window_selector import WindowInfo as SelectedWindowInfo
from recorder.window_selector import refresh_window_reference


def build_window_filter(
    *,
    window_title: str | None = None,
    window_title_regex: str | None = None,
    process_name: str | None = None,
    pid: int | None = None,
    hwnd: int | None = None,
) -> WindowFilter:
    return WindowFilter(
        title_contains=window_title,
        title_regex=window_title_regex,
        process_name=process_name,
        pid=pid,
        hwnd=hwnd,
    )


def refresh_selected_target(
    *,
    window_title: str | None = None,
    process_name: str | None = None,
    pid: int | None = None,
    hwnd: int | None = None,
) -> dict[str, str | int | None]:
    if hwnd is None or pid is None or not window_title or not process_name:
        return {
            "window_title": window_title,
            "process_name": process_name,
            "pid": pid,
            "hwnd": hwnd,
        }

    seed = SelectedWindowInfo(
        hwnd=hwnd,
        title=window_title,
        pid=pid,
        process_name=process_name,
    )
    refreshed = refresh_window_reference(seed)
    if refreshed is None:
        return {
            "window_title": window_title,
            "process_name": process_name,
            "pid": pid,
            "hwnd": hwnd,
        }

    return {
        "window_title": refreshed.title,
        "process_name": refreshed.process_name,
        "pid": refreshed.pid,
        "hwnd": refreshed.hwnd,
    }


def make_session_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]


def run_session(
    *,
    window_title: str | None = None,
    window_title_regex: str | None = None,
    output_dir: str | None = None,
    runtime_observer_only: bool = False,
    stop_event: Event | None = None,
    process_name: str | None = None,
    pid: int | None = None,
    hwnd: int | None = None,
    mouse_move_interval: float = 0.25,
    cpu_threshold: float = 12.0,
    session_id: str | None = None,
    enable_state_capture: bool = False,
) -> str:
    stop_event = stop_event or Event()

    refreshed_target = refresh_selected_target(
        window_title=window_title,
        process_name=process_name,
        pid=pid,
        hwnd=hwnd,
    )
    window_title = refreshed_target["window_title"]
    process_name = refreshed_target["process_name"]
    pid = refreshed_target["pid"]
    hwnd = refreshed_target["hwnd"]

    base_output_dir = Path(output_dir or "output").resolve()
    base_output_dir.mkdir(parents=True, exist_ok=True)

    shared_session_id = session_id or make_session_id()
    window_filter = build_window_filter(
        window_title=window_title,
        window_title_regex=window_title_regex,
        process_name=process_name,
        pid=pid,
        hwnd=hwnd,
    )

    recorder: InteractionRecorder | None = None
    if not runtime_observer_only:
        recorder = InteractionRecorder(
            output_dir=str(base_output_dir),
            window_filter=window_filter,
            mouse_move_interval_seconds=mouse_move_interval,
            session_id=shared_session_id,
            external_stop_event=stop_event,
            strict_window_filter=True,
            enable_state_capture=enable_state_capture,
        )

    runtime_manager = RuntimeObserverManager(
        output_dir=str(base_output_dir),
        session_id=shared_session_id,
        window_filter=window_filter,
        cpu_threshold=cpu_threshold,
        enable_state_capture=enable_state_capture,
        event_listeners=[recorder.on_runtime_event] if recorder is not None else None,
    )

    print(f"[RUNTIME] shared session id: {shared_session_id}")
    if window_title:
        print(f"[RUNTIME] target window title: {window_title}")
    if process_name:
        print(f"[RUNTIME] target process: {process_name}")
    if pid is not None:
        print(f"[RUNTIME] target pid: {pid}")
    if hwnd is not None:
        print(f"[RUNTIME] target hwnd: {hwnd}")

    try:
        runtime_manager.start()

        if runtime_observer_only:
            print("[RUNTIME] runtime observer only mode started. Use the GUI Stop button or Ctrl+C to stop.")
            while not stop_event.is_set():
                time.sleep(0.2)
        else:
            recorder.start()
            stop_event.set()
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        try:
            if recorder is not None:
                recorder.stop()
        except Exception:
            pass
        runtime_manager.stop()

    return str(runtime_manager.session_dir)


def main(
    window_title: str | None = None,
    output_dir: str | None = None,
    runtime_observer_only: bool = False,
    stop_event: Event | None = None,
    process_name: str | None = None,
    pid: int | None = None,
    hwnd: int | None = None,
    window_title_regex: str | None = None,
    mouse_move_interval: float = 0.25,
    cpu_threshold: float = 12.0,
    session_id: str | None = None,
    enable_state_capture: bool = False,
) -> str:
    return run_session(
        window_title=window_title,
        window_title_regex=window_title_regex,
        output_dir=output_dir,
        runtime_observer_only=runtime_observer_only,
        stop_event=stop_event,
        process_name=process_name,
        pid=pid,
        hwnd=hwnd,
        mouse_move_interval=mouse_move_interval,
        cpu_threshold=cpu_threshold,
        session_id=session_id,
        enable_state_capture=enable_state_capture,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recorder + Runtime Observer for Windows desktop apps")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--window-title", default=None)
    parser.add_argument("--window-title-regex", default=None)
    parser.add_argument("--process-name", default=None)
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--hwnd", type=int, default=None)
    parser.add_argument("--mouse-move-interval", type=float, default=0.25)
    parser.add_argument("--cpu-threshold", type=float, default=12.0)
    parser.add_argument("--runtime-observer-only", action="store_true")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--enable-state-capture", action="store_true")
    return parser


def cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    main(
        window_title=args.window_title,
        window_title_regex=args.window_title_regex,
        output_dir=args.output_dir,
        runtime_observer_only=args.runtime_observer_only,
        process_name=args.process_name,
        pid=args.pid,
        hwnd=args.hwnd,
        mouse_move_interval=args.mouse_move_interval,
        cpu_threshold=args.cpu_threshold,
        session_id=args.session_id,
        enable_state_capture=args.enable_state_capture,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
