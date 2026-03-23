import threading
from threading import Event
from recorder.runtime_cli import main as runtime_main


class RecorderController:
    def __init__(self):
        self._thread = None
        self._stop_event = Event()
        self._running = False
        self.last_session_dir = None

    def start(self, config: dict):
        if self._running:
            raise RuntimeError("Recorder already running")

        self._stop_event.clear()
        self.last_session_dir = None

        def target():
            try:
                self.last_session_dir = runtime_main(
                    window_title=config.get("window_title"),
                    output_dir=config.get("output_dir"),
                    runtime_observer_only=config.get("runtime_observer_only", False),
                    stop_event=self._stop_event,
                    process_name=config.get("process_name"),
                    pid=config.get("pid"),
                    hwnd=config.get("hwnd"),
                )
            finally:
                self._running = False

        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()
        self._running = True

    def stop(self):
        if not self._running:
            return self.last_session_dir

        self._stop_event.set()
        self._thread.join(timeout=10)
        self._running = False
        return self.last_session_dir

    @property
    def is_running(self):
        return self._running