# Technical Notes

## Moduli introdotti

- `recorder/ui_resolver.py`: normalizza il controllo UI corrente in un payload `ui_target` stabile e tollerante ai metadati mancanti
- `recorder/semantic_events.py`: traccia il ciclo di vita dei campi editabili e genera `input_commit`
- `recorder/visual_capture.py`: gestisce screenshot finestra, crop controllo, manifest e payload `visual_checkpoint`
- `recorder/semantic_enrichment.py`: layer additivo condiviso tra recorder e runtime observer per identità controllo, stato before/after, dialog, UI snapshot e provenance

## Flusso aggiornato

1. `recorder/recorder.py` continua a catturare eventi raw da mouse e tastiera.
2. Il contesto Win32/UIA viene risolto da `UIContextResolver`.
3. `UIElementResolver` costruisce `ui_target` per click, focus e handle runtime.
4. `VisualCaptureManager` può agganciarsi in modo opzionale a raw recorder, `input_commit` e runtime observer per produrre checkpoint visuali `after`.
5. `SemanticEventBuilder` osserva i passaggi di focus e i tasti per emettere `input_commit` con il valore finale.
6. `SemanticEnricher` riusa `ui_target`, stato runtime e snapshot live per costruire `window_context`, `control_context`, `state_before`, `state_after`, `dialog`, `ui_checkpoint` e `provenance`.
7. I campi legacy restano invariati; i nuovi campi vengono aggiunti in modo non distruttivo.

## Compatibilità

- `window`, `target_element`, `target_state`, `target_name`, `target_type` restano presenti
- i nuovi campi principali restano `window_title`, `process_name`, `hwnd`, `ui_target`, ma ora possono essere affiancati da `window_context`, `control_context`, `state_before`, `state_after`, `dialog`, `triggered_by`, `ui_checkpoint`, `provenance`
- per default, `visual_checkpoint` viene aggiunto al payload degli eventi rilevanti senza cambiare gli schemi storici
- `input_commit` è un nuovo `event_type`, quindi non altera la struttura degli eventi esistenti
- il manifest `visual_artifacts.jsonl` è opzionale e contiene solo riferimenti additivi agli artifact salvati
- `session.json` e `runtime_metadata.json` espongono una sezione `semantic_enrichment` con i flag attivi per la sessione

## Limiti residui

- `click_count` rimane `null` perché `pynput` non espone il conteggio dei click
- il contesto griglia/tabella è best effort e dipende dai pattern UIA esposti dall'applicazione
- alcune app legacy o protette possono restituire label/testo incompleti; in quel caso i campi vengono mantenuti a `null`
- `form_name` in senso VB6 designer/code name non è generalmente disponibile via Win32/UIA: il campo viene popolato solo quando inferibile con affidabilità ragionevole
- `dialog_message`, `clicked_button`, `row_key` e `validation_state` restano opzionali e dipendono dai metadati realmente esposti dall'applicazione
- la cattura immagini usa `PIL.ImageGrab` sui bounds della finestra top-level; se i bounds non sono disponibili o la grab fallisce, il recorder non si interrompe e marca il checkpoint come fallito
- il comportamento può essere disattivato da GUI con `Disable visual checkpoints` o da CLI con `--disable-visual-checkpoints`
