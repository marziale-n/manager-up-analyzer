# Technical Notes

## Moduli introdotti

- `recorder/ui_resolver.py`: normalizza il controllo UI corrente in un payload `ui_target` stabile e tollerante ai metadati mancanti
- `recorder/semantic_events.py`: traccia il ciclo di vita dei campi editabili e genera `input_commit`

## Flusso aggiornato

1. `recorder/recorder.py` continua a catturare eventi raw da mouse e tastiera.
2. Il contesto Win32/UIA viene risolto da `UIContextResolver`.
3. `UIElementResolver` costruisce `ui_target` per click, focus e handle runtime.
4. `SemanticEventBuilder` osserva i passaggi di focus e i tasti per emettere `input_commit` con il valore finale.
5. I campi legacy restano invariati; i nuovi campi vengono aggiunti in modo non distruttivo.

## Compatibilità

- `window`, `target_element`, `target_state`, `target_name`, `target_type` restano presenti
- i nuovi campi principali sono `window_title`, `process_name`, `hwnd`, `ui_target`
- `input_commit` è un nuovo `event_type`, quindi non altera la struttura degli eventi esistenti

## Limiti residui

- `click_count` rimane `null` perché `pynput` non espone il conteggio dei click
- il contesto griglia/tabella è best effort e dipende dai pattern UIA esposti dall'applicazione
- alcune app legacy o protette possono restituire label/testo incompleti; in quel caso i campi vengono mantenuti a `null`
