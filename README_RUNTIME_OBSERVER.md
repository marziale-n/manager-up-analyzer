# Runtime Observer Manager

Il `RuntimeObserverManager` è il componente orchestratore che unisce l'ispezione degli eventi di sistema (WinEvents), il monitoraggio dello stato del processo, l'acquisizione della clipboard e la cattura visiva, generando una timeline dettagliata dell'esecuzione di un'applicazione.

## Architettura a Livello di Esecuzione

L'Observer avvia molteplici thread daemon, ciascuno dedicato a una specifica forma di monitoraggio, convogliando i risultati in un unico sink (file JSONL).

### Componenti Principali

1.  **Orchestratore (`RuntimeObserverManager`)**
    * Gestisce il ciclo di vita (start/stop) dei monitor.
    * Filtra gli eventi in base alle espressioni regolari del titolo della finestra (`WindowFilter`).
    * Esegue la pipeline di arricchimento (Visivo -> OCR -> Semantico) in modo sequenziale per garantire coerenza temporale.
    
2.  **Monitor Attivi**
    * **WinEventMonitor:** Ascolta eventi passivi come `EVENT_OBJECT_FOCUS` o `EVENT_SYSTEM_DIALOGSTART` tramite hook globali (`SetWinEventHook`). Implementa logiche non-bloccanti per evitare di interferire con l'UI thread delle app target.
    * **BusyMonitor:** Campiona l'utilizzo della CPU del processo target.
    * **ClipboardMonitor:** Interroga passivamente la sequenza degli appunti per loggare trasferimenti dati contestuali.

### Gestione delle Applicazioni Legacy (VB6)

Il `RuntimeObserverManager` è ottimizzato per analizzare applicazioni "scatola nera" (es. gestionali in Visual Basic 6) implementando meccanismi difensivi:
* **Ispezione MSAA in Thread Separati:** L'estrazione dello stato tramite Active Accessibility viene racchiusa in contesti `CoInitialize` / `CoUninitialize` per evitare il blocco (freeze) dell'applicazione monitorata.
* **Estrazione OCR On-Demand:** Se un focus o un click avviene su elementi opachi (es. griglie di dati), l'Observer innesca il `SemanticEnricher` che esegue `pytesseract` sul ritaglio (`crop_path`) generato dal `VisualCaptureManager`, estraendo il dato puramente a livello visivo.

### Ciclo di Vita di un Evento

1.  Un utente clicca su un'area dell'app target (es. una griglia) o esegue un `Ctrl+V`.
2.  Il monitor pertinente (Input, WinEvent o Clipboard) cattura l'evento.
3.  L'evento viene inviato tramite la funzione `emit()`.
4.  L'Observer valuta se l'evento richiede uno snapshot visivo (`VisualCaptureManager.should_capture_runtime`).
5.  Se sì, scatta uno screenshot e ritaglia il controllo (`crop_path`).
6.  Il payload viene passato al `SemanticEnricher`. Se l'UI target non contiene testo (limite tecnico di VB6/UIA), l'enricher lancia l'OCR sul crop visivo.