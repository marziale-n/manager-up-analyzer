from __future__ import annotations

import argparse

from recorder.filters import WindowFilter
from recorder.recorder import InteractionRecorder
from recorder.semantic_enrichment import SemanticEnrichmentConfig
from recorder.visual_capture import VisualCheckpointConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Windows Test Recorder MVP")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--window-title", default=None)
    parser.add_argument("--window-title-regex", default=None)
    parser.add_argument("--process-name", default=None)
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--hwnd", type=int, default=None)
    parser.add_argument("--mouse-move-interval", type=float, default=1)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--enable-visual-checkpoints", action="store_true")
    parser.add_argument("--disable-visual-checkpoints", action="store_true")
    parser.add_argument("--visual-checkpoint-on-click", action="store_true")
    parser.add_argument("--visual-checkpoint-on-input-commit", action="store_true")
    parser.add_argument("--disable-enrich-control-identity", action="store_true")
    parser.add_argument("--disable-enrich-control-state", action="store_true")
    parser.add_argument("--disable-enrich-label-mapping", action="store_true")
    parser.add_argument("--disable-enrich-dialogs", action="store_true")
    parser.add_argument("--disable-enrich-grid-context", action="store_true")
    parser.add_argument("--disable-enrich-ui-snapshots", action="store_true")
    parser.add_argument("--disable-confidence-metadata", action="store_true")
    parser.add_argument("--ui-snapshot-max-controls", type=int, default=25)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    window_filter = WindowFilter(
        title_contains=args.window_title,
        title_regex=args.window_title_regex,
        process_name=args.process_name,
        pid=args.pid,
        hwnd=args.hwnd,
    )

    recorder = InteractionRecorder(
        output_dir=args.output_dir,
        window_filter=window_filter,
        mouse_move_interval_seconds=args.mouse_move_interval,
        session_id=args.session_id,
        visual_checkpoint_config=VisualCheckpointConfig(
            enabled=not args.disable_visual_checkpoints,
            on_click=True if args.visual_checkpoint_on_click else None,
            on_input_commit=True if args.visual_checkpoint_on_input_commit else None,
        ),
        semantic_enrichment_config=SemanticEnrichmentConfig(
            enrich_control_identity=not args.disable_enrich_control_identity,
            enrich_control_state=not args.disable_enrich_control_state,
            enrich_label_mapping=not args.disable_enrich_label_mapping,
            enrich_dialogs=not args.disable_enrich_dialogs,
            enrich_grid_context=not args.disable_enrich_grid_context,
            enrich_ui_snapshots=not args.disable_enrich_ui_snapshots,
            include_confidence_metadata=not args.disable_confidence_metadata,
            ui_snapshot_max_controls=max(1, int(args.ui_snapshot_max_controls or 25)),
        ),
    )

    print("Windows Test Recorder MVP")
    print("Recording started.")
    print("Press ESC to stop.")
    if args.window_title:
        print(f"Window filter: {args.window_title}")
    if args.window_title_regex:
        print(f"Window filter regex: {args.window_title_regex}")
    if args.process_name:
        print(f"Process filter: {args.process_name}")
    if args.pid is not None:
        print(f"PID filter: {args.pid}")
    if args.hwnd is not None:
        print(f"HWND filter: {args.hwnd}")
    if args.session_id:
        print(f"Shared session id: {args.session_id}")
    if not args.disable_visual_checkpoints:
        print("Visual checkpoints enabled.")

    recorder.start()

    print(f"Recording finished. Session output: {recorder.session_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
