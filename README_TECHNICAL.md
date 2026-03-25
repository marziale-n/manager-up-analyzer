# Architettura Tecnica: UI Action Recorder

Questo documento descrive in dettaglio l'architettura tecnica, i moduli principali e le strutture dati del framework di registrazione UI.

## Architettura di Riferimento

Il sistema è basato su un'architettura a sensori (monitor) multipli che convogliano eventi grezzi in una pipeline di arricchimento spaziale e semantico, per poi persisterli su disco.

### 1. Sensori e Monitor (Input)
* **`InputRecorder` (`recorder.py`):** Utilizza `pynput` per l'hook globale di mouse e tastiera. Raggruppa le sequenze di tasti in input logici.
* **`WinEventMonitor` (`win_event_monitor.py`):** Utilizza le API Win32 (`SetWinEventHook`) per ascoltare in background gli eventi di Windows (focus, dialog, menu).
* **`BusyMonitor` (`busy_monitor.py`):** Monitora il consumo di CPU dell'applicazione target per identificare i periodi di elaborazione (idle/busy) successivi a un input.
* **`ClipboardMonitor` (`clipboard_monitor.py`):** Monitoraggio passivo tramite l'API `GetClipboardSequenceNumber` per intercettare trasferimenti di dati (Copia/Incolla) senza bloccare il thread di UI.

### 2. Risoluzione del Contesto (Estrazione Dati)
* **`UIContextResolver` (`context.py`):** Il motore principale che interroga il sistema operativo per ottenere informazioni sull'elemento UI a specifiche coordinate o handle. Combina `pywinauto` (UIA/Win32) per l'estrazione dello stato.
* **`msaa_resolver.py`:** Modulo di fallback che utilizza `comtypes` e `oleacc.dll` (MSAA). Fondamentale per le applicazioni legacy (VB6) dove UIA fallisce; estrae `accName` e `accValue` inizializzando correttamente l'ambiente COM (`CoInitialize`).
* **`UIElementResolver` (`ui_resolver.py`):** Formatta i dati grezzi estratti in una struttura standardizzata (`ui_target`), integrando le informazioni UIA con i fallback MSAA.

### 3. Pipeline Visiva e Semantica
* **`VisualCaptureManager` (`visual_capture.py`):** Responsabile dello scatto di screenshot dell'intero schermo o della finestra target, e del ritaglio (crop) esatto delle coordinate di un controllo.
* **`SemanticEnricher` (`semantic_enrichment.py`):** Aggiunge contesto agli eventi. Include l'**OCR On-Demand** (tramite `pytesseract`) che legge il testo direttamente dal crop visivo se l'estrazione dati Win32/MSAA restituisce valori vuoti (es. per le griglie dati come `MSFlexGrid`).

## Struttura del Payload JSONL

Ogni riga del file `events.jsonl` o `runtime_timeline.jsonl` è un oggetto JSON che descrive un singolo evento. I campi si sono arricchiti con le nuove logiche:

```json
{
  "category": "input | system | process",
  "event_type": "mouse_click | text_input | object_focus | clipboard_changed",
  "timestamp_utc": "2023-10-27T10:00:00.123Z",
  "window": { ... },
  "ui_target": {
    "hwnd": 123456,
    "class_name": "ThunderRT6TextBox",
    "text": "Mario Rossi",
    "control_id": 1001,
    "extraction_method": "native_msaa",
    "msaa_name": "Nome Cliente:",
    "msaa_value": "Mario Rossi"
  },
  "control_state": {
    "value": "Mario Rossi",
    "ocr_value": "Mario Rossi",
    "extraction_method": "visual_ocr"
  },
  "clipboard_content": "Mario Rossi",
  "ocr_extracted_text": "Mario Rossi",
  "visual_checkpoint": {
    "screenshot_path": "...",
    "crop_path": "..."
  }
}
```