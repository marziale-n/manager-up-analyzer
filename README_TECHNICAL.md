# Technical Notes

## Moduli introdotti

- `recorder/ui_resolver.py`: normalizza il controllo UI corrente in un payload `ui_target` stabile e tollerante ai metadati mancanti
- `recorder/semantic_events.py`: traccia il ciclo di vita dei campi editabili e genera `input_commit`
- `recorder/visual_capture.py`: gestisce screenshot finestra, crop controllo, manifest e payload `visual_checkpoint`

## Flusso aggiornato

1. `recorder/recorder.py` continua a catturare eventi raw da mouse e tastiera.
2. Il contesto Win32/UIA viene risolto da `UIContextResolver`.
3. `UIElementResolver` costruisce `ui_target` per click, focus e handle runtime.
4. `VisualCaptureManager` può agganciarsi in modo opzionale a raw recorder, `input_commit` e runtime observer per produrre checkpoint visuali `after`.
5. `SemanticEventBuilder` osserva i passaggi di focus e i tasti per emettere `input_commit` con il valore finale.
6. I campi legacy restano invariati; i nuovi campi vengono aggiunti in modo non distruttivo.

## Compatibilità

- `window`, `target_element`, `target_state`, `target_name`, `target_type` restano presenti
- i nuovi campi principali sono `window_title`, `process_name`, `hwnd`, `ui_target`
- per default, `visual_checkpoint` viene aggiunto al payload degli eventi rilevanti senza cambiare gli schemi storici
- `input_commit` è un nuovo `event_type`, quindi non altera la struttura degli eventi esistenti
- il manifest `visual_artifacts.jsonl` è opzionale e contiene solo riferimenti additivi agli artifact salvati

## Limiti residui

- `click_count` rimane `null` perché `pynput` non espone il conteggio dei click
- il contesto griglia/tabella è best effort e dipende dai pattern UIA esposti dall'applicazione
- alcune app legacy o protette possono restituire label/testo incompleti; in quel caso i campi vengono mantenuti a `null`
- la cattura immagini usa `PIL.ImageGrab` sui bounds della finestra top-level; se i bounds non sono disponibili o la grab fallisce, il recorder non si interrompe e marca il checkpoint come fallito
- il comportamento può essere disattivato da GUI con `Disable visual checkpoints` o da CLI con `--disable-visual-checkpoints`
