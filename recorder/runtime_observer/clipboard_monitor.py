from __future__ import annotations

import ctypes
import threading
import time
from typing import Any, Callable

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Costante per il formato testo Unicode degli appunti
CF_UNICODETEXT = 13

class ClipboardMonitor:
    def __init__(
        self, 
        emit: Callable[[dict[str, Any]], None], 
        poll_interval_seconds: float = 0.5
    ) -> None:
        self.emit = emit
        self.poll_interval_seconds = poll_interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="clipboard-monitor")
        self._last_sequence = 0

    def start(self) -> None:
        # Registra la sequenza iniziale per non loggare la clipboard al momento dell'avvio
        self._last_sequence = user32.GetClipboardSequenceNumber()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def _get_clipboard_text(self) -> str | None:
        text = None
        try:
            # Apre la clipboard associandola al task corrente (0)
            if user32.OpenClipboard(0):
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if handle:
                    locked = kernel32.GlobalLock(handle)
                    if locked:
                        text = ctypes.c_wchar_p(locked).value
                        kernel32.GlobalUnlock(handle)
                user32.CloseClipboard()
        except Exception:
            pass
        return text

    def _run(self) -> None:
        while not self._stop.is_set():
            # GetClipboardSequenceNumber incrementa ogni volta che il contenuto cambia
            current_sequence = user32.GetClipboardSequenceNumber()
            
            if current_sequence != self._last_sequence and current_sequence != 0:
                self._last_sequence = current_sequence
                text = self._get_clipboard_text()
                
                # Emettiamo l'evento solo se c'è del testo utile (ignoriamo se copiano file/immagini)
                if text and text.strip():
                    self.emit({
                        "category": "system",
                        "event_type": "clipboard_changed",
                        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time()%1)*1000):03d}Z",
                        "clipboard_content": text,
                        "clipboard_length": len(text)
                    })
                    
            time.sleep(self.poll_interval_seconds)