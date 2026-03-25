# UI Action Recorder & Semantic Analyzer

Un framework avanzato in Python per la registrazione, l'analisi e l'arricchimento semantico delle interazioni utente con applicazioni desktop Windows. È progettato specificamente per monitorare flussi di lavoro complessi, estrarre dati strutturati (JSON/JSONL) e catturare screenshot contestuali, con un supporto specializzato per applicazioni legacy (es. Visual Basic 6).

## Caratteristiche Principali

* **Tracciamento Input a Basso Livello:** Registra click del mouse, scroll e sequenze di tasti ignorando typo e correzioni.
* **Monitoraggio Eventi di Sistema (WinEvents):** Intercetta cambi di focus, apertura di finestre di dialogo, menu e cambi di stato.
* **Supporto Legacy Avanzato (VB6):** Utilizza ispezioni passive tramite Win32 e MSAA (Microsoft Active Accessibility) per estrarre in modo sicuro nomi e valori da controlli ostici (es. `ThunderRT6`) senza interferire con l'UI.
* **OCR On-Demand:** Integra il riconoscimento ottico dei caratteri (Tesseract) sui ritagli visivi per estrarre dati da controlli non ispezionabili (es. griglie `MSFlexGrid`).
* **Monitoraggio Clipboard:** Cattura dinamicamente il contenuto degli appunti (Copia/Incolla) per non perdere le informazioni semantiche trasferite dall'utente.
* **Risoluzione UI Intelligente:** Identifica i controlli interagiti estraendo gerarchia, testo, ID e pattern di automazione tramite UIAutomation e MSAA.
* **Cattura Visiva (Screenshot & Crop):** Salva screenshot dell'intera finestra e ritagli (crop) precisi dell'elemento interagito.
* **Arricchimento Semantico:** Analizza gli eventi grezzi per generare descrizioni in linguaggio naturale delle azioni svolte.

## Requisiti di Sistema

* **Sistema Operativo:** Windows 10/11 (richiesto per le API Win32, UIAutomation e MSAA).
* **Python:** 3.9 o superiore.
* **Tesseract OCR:** Richiesto per l'estrazione visiva. Deve essere installato nel sistema (es. tramite UB Mannheim installer per Windows).

## Installazione

1.  Clona il repository.
2.  Crea un ambiente virtuale (consigliato):
    ```bash
    python -m venv venv
    venv\Scripts\activate
    ```
3.  Installa le dipendenze:
    ```bash
    pip install pynput pywinauto pywin32 psutil pydantic
    pip install pytesseract Pillow comtypes
    ```

## Lanciare la compilazione
```bash
python -m PyInstaller runtime_observer.spec --clean
```

## Utilizzo Rapido

Per avviare l'osservatore runtime per una specifica applicazione:

```bash
python -m recorder.runtime_cli --output-dir ./logs --window-regex ".*Nome Applicazione.*"