# Runtime Observer Pack

This pack adds a multi-channel runtime observer for Windows desktop testing.

## Current behavior

The observer is now aligned with the same target selected by the recorder/GUI.
The selected application is identified with a shared window filter that can include:

- `hwnd`
- `pid`
- `process_name`
- window title or title regex

This means the runtime observer no longer records unrelated system events just because another app became the foreground window.
When `hwnd` or `pid` are available, they take precedence over the title so the observer keeps following the selected app even if the window title changes.

## Included channels
- `system`: foreground changes, dialogs, menus, focus, show/hide, value/name/state changes
- `process`: CPU-based busy detection with `processing_started` and `processing_finished`
- `timeline`: unified JSONL output in `runtime_timeline.jsonl`

## Files
- `recorder/runtime_observer/win_event_monitor.py`
- `recorder/runtime_observer/busy_monitor.py`
- `recorder/runtime_observer/runtime_manager.py`
- `recorder/runtime_cli.py`
- updated `main.py`

## Output
A session folder is created in `output/<session_id>/` with:
- `runtime_timeline.jsonl`
- `runtime_metadata.json`

Runtime events now include, when available:
- `element`: resolved control metadata for the raw `hwnd`
- `control_state`: current control snapshot
- `previous_control_state`: previous snapshot cached for the same control
- `control_state_changes`: top-level diff between previous and current snapshot

These extra control snapshots are disabled by default and are enabled only with `--enable-state-capture`, because some legacy desktop applications may react badly to deep control inspection.

## Usage
Run full stack (observer + existing recorder):

```powershell
python main.py --window-title-regex ".*Calcolatrice.*"
```

Run only the runtime observer:

```powershell
python main.py --runtime-observer-only --window-title-regex ".*Calcolatrice.*"
```

Run with an exact target selected by GUI or passed manually:

```powershell
python main.py --window-title "Calcolatrice" --process-name ApplicationFrameHost.exe --pid 3672 --hwnd 263154
```

## How targeting works now

- `gui_app.py` and `RecorderApp.exe` enumerate top-level windows and expose the selected `hwnd`, `pid`, `process_name` and title
- before the session starts, that reference is refreshed to reduce stale window handles
- if the selected window changes title or opens related dialogs, the shared filter still follows it primarily through `hwnd` / `pid`
- `WinEventMonitor` emits only events whose resolved root window matches the selected target
- `BusyMonitor` prefers the selected `hwnd`/`pid` instead of monitoring only the current foreground app
- recorder and runtime observer write into the same session directory and share the same session id

## Important note
The observer is additive. It is designed to run alongside the interaction recorder and does not replace it.
When `--runtime-observer-only` is used, only `runtime_timeline.jsonl` and `runtime_metadata.json` are produced for that session.
