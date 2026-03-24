# Windows Test Recorder MVP

MVP in Python per Windows che registra le interazioni utente su una finestra target selezionata e salva log JSONL già utili per:

- ricostruire i passaggi del test
- analizzare il comportamento dell'utente
- trasformare i log in step più semantici in una fase successiva
- preparare una futura fase di replay automatico

## Stato attuale

- la GUI (`gui_app.py` / `RecorderApp.exe`) elenca le finestre top-level reali aperte e salva per ciascuna `hwnd`, `pid`, `process_name` e `title`
- quando premi `Start`, il target viene riallineato una volta prima di partire, così se la finestra è stata ricreata o aggiornata viene passato al recorder/runtime observer il riferimento più corretto disponibile
- il matching non si basa più solo sul titolo: viene usata un'identità composta da `hwnd`, `pid`, `process_name` e titolo, con fallback coerenti
- il recorder salva solo gli eventi che appartengono davvero all'app/finestra selezionata
- il runtime observer salva solo eventi di sistema/processo che corrispondono al target selezionato
- i click mouse vengono arricchiti con `ui_target`, cioè il controllo realmente colpito con nome/id/tipo/testo/bounds e contesto griglia quando disponibile
- i controlli editabili producono eventi semantici `input_commit` con `previous_value` e `final_value` consolidato quando il focus cambia o viene premuto `Enter`
- gli eventi significativi del runtime observer includono lo stesso layer `ui_target`, così focus, change e value change usano la stessa semantica del recorder raw
- il payload può essere arricchito in modo additivo con `window_context`, `control_context`, `state_before`, `state_after`, `dialog`, `triggered_by`, `ui_checkpoint` e `provenance`
- salva di default visual checkpoints con screenshot della finestra target e crop del controllo, pensati come fallback di verità visiva per applicazioni legacy VB6 / Win32

## Limitazioni attuali

- il matching è molto più robusto, ma alcuni applicativi molto custom o protetti possono comunque esporre metadati incompleti a Win32/UI Automation
- non intercetta in modo perfetto ogni applicativo custom/non-UIA
- i tasti vengono loggati a livello di pressione/rilascio; la ricostruzione del testo digitato è solo basilare

## Cosa produce

Per ogni sessione crea una cartella dentro `output/` con:

- `events.jsonl`: stream degli eventi raw arricchiti
- `session.json`: metadati della sessione
- `summary.json`: piccolo riepilogo finale
- `runtime_timeline.jsonl`: timeline eventi del runtime observer
- `runtime_metadata.json`: metadati del runtime observer
- `visual_artifacts.jsonl`: manifest opzionale dei visual checkpoints generati
- `artifacts/screenshots/`: screenshot finestra top-level
- `artifacts/crops/`: crop del controllo coinvolto quando i bounds sono affidabili

Ogni evento contiene, quando disponibile:

- timestamp UTC
- tipo evento
- coordinate mouse
- finestra attiva
- processo attivo
- controllo UI sotto il mouse o con focus
- payload normalizzato `ui_target` con `control_name`, `control_id`, `automation_id`, `control_type`, `label`, `text`, `bounds`, `window_title`, `process_name`, `hwnd`
- contesto opzionale `window_context` e `control_context` con identità più stabile del controllo, parent hierarchy, mapping label->control e contesto griglia/combo quando disponibile
- stato semantico del controllo coinvolto (`target_state`)
- eventi `input_commit` per i campi editabili con valore finale leggibile
- stato dopo l'azione per click e tasti (`post_target_state`, `post_focused_state`)
- differenze tra stato prima/dopo (`target_state_changes`, `focused_state_changes`)
- snapshot opzionali `state_before` / `state_after` con `value`, `enabled`, `visible`, `focused`, `selected_index`, `selected_text`, `checked`, `read_only`
- contesto dialog opzionale (`dialog`, `triggered_by`) su popup/modali rilevati dal runtime observer
- snapshot strutturale leggero `ui_checkpoint` sui checkpoint chiave
- metadati `provenance` con `source`, `confidence` e `inference_method` per distinguere dati certi da inferenze
- stato modificatori tastiera
- semplice aggregazione del testo digitato
- payload additivo `visual_checkpoint` con path relativi, bounds, hash e stato della cattura

## Requisiti

- Windows 10/11
- Python 3.11+ consigliato
- esecuzione preferibilmente con privilegi simili a quelli dell'app da tracciare

## Installazione

Apri PowerShell nella cartella del progetto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Avvio

Esempio: registra solo quando la finestra attiva contiene `Notepad`

```powershell
python main.py --window-title "Notepad"
```

Oppure usa regex:

```powershell
python main.py --window-title-regex ".*Calculator.*"
```

Puoi anche cambiare cartella di output:

```powershell
python main.py --window-title "Notepad" --output-dir output
```

Per un target più preciso puoi passare anche processo, PID e handle:

```powershell
python main.py --window-title "Notepad" --process-name notepad.exe --pid 1234 --hwnd 987654
```

Il fallback visuale è attivo di default sui principali eventi:

```powershell
python main.py --window-title "Notepad"
```

Se vuoi disabilitarlo da CLI:

```powershell
python main.py --window-title "Notepad" --disable-visual-checkpoints
```

Puoi anche disattivare selettivamente gli arricchimenti semantici più costosi o più inferenziali:

```powershell
python main.py --window-title "Notepad" --disable-enrich-ui-snapshots --disable-enrich-dialogs
```

Per eseguire solo il runtime observer:

```powershell
python main.py --runtime-observer-only --window-title "Notepad"
```

## Avvio da GUI / eseguibile

Puoi usare:

- `python main_gui.py`
- `python gui_app.py`
- `dist/RecorderApp.exe`

Se usi l'eseguibile, ricordati di rigenerarlo dopo ogni modifica al codice sorgente.

Flusso attuale della GUI:

1. la combo mostra le finestre top-level aperte con `process_name`, `pid`, `hwnd` e titolo
2. quando scegli una finestra e premi `Start`, il riferimento viene rinfrescato
3. parte una sessione condivisa con la stessa cartella output per recorder e runtime observer
4. `Stop` dalla GUI ferma correttamente entrambe le componenti anche senza premere `ESC`

## Stop registrazione

Puoi fermare la registrazione in due modi:

- `ESC` per terminare il recorder da tastiera
- `Stop` dalla GUI per fermare recorder e runtime observer
- in modalità `--runtime-observer-only`, usa `Stop` dalla GUI oppure `Ctrl+C` da CLI

## Esempio evento

```json
{
  "event_id": "...",
  "session_id": "...",
  "timestamp_utc": "2026-03-20T14:00:00.000000+00:00",
  "event_type": "mouse_click",
  "payload": {
    "x": 512,
    "y": 401,
    "button": "Button.left",
    "pressed": true,
    "window": {
      "title": "Untitled - Notepad",
      "class_name": "Notepad",
      "handle": 123456,
      "pid": 9876,
      "process_name": "notepad.exe",
      "process_path": "C:\\Windows\\System32\\notepad.exe"
    },
    "target_element": {
      "name": "Text Editor",
      "automation_id": "15",
      "control_type": "Edit",
      "class_name": "RichEditD2DPT"
    }
  }
}
```

## Esempi estesi

Click arricchito:

```json
{
  "event_type": "mouse_click",
  "payload": {
    "x": 542,
    "y": 312,
    "button": "Button.left",
    "pressed": false,
    "click_count": null,
    "window_title": "Dettaglio articolo",
    "process_name": "A00504.exe",
    "hwnd": 460600,
    "ui_target": {
      "control_name": "OK",
      "control_id": "1012",
      "automation_id": "btnOk",
      "control_type": "Button",
      "label": "OK",
      "text": "OK",
      "bounds": [500, 290, 580, 330]
    },
    "window_context": {
      "caption": "Dettaglio articolo",
      "form_name": null,
      "form_class": "ThunderRT6FormDC",
      "hwnd": 460600
    },
    "control_context": {
      "name": "OK",
      "type": "Button",
      "hwnd": 812120,
      "control_id": "1012",
      "label_text": "OK",
      "bounds": {
        "x": 500,
        "y": 290,
        "w": 80,
        "h": 40
      }
    },
    "state_after": {
      "value": "OK",
      "focused": true
    },
    "provenance": {
      "source": ["event"],
      "confidence": "high",
      "inference_method": "event_enrichment"
    }
  }
}
```

Commit del valore finale:

```json
{
  "event_type": "input_commit",
  "payload": {
    "window_title": "Dettaglio articolo",
    "process_name": "A00504.exe",
    "hwnd": 460600,
    "ui_target": {
      "control_name": null,
      "control_id": "1048",
      "automation_id": "txtDescrizione",
      "control_type": "Edit",
      "label": "Descrizione"
    },
    "previous_value": "",
    "final_value": "prova descrizione",
    "commit_reason": "focus_lost",
    "control_context": {
      "type": "Edit",
      "hwnd": 984312,
      "control_id": "1048",
      "label_text": "Descrizione"
    },
    "state_before": {
      "value": ""
    },
    "state_after": {
      "value": "prova descrizione",
      "read_only": false
    }
  }
}
```

Dialog correlato all'azione utente:

```json
{
  "event_type": "dialog_start",
  "payload": {
    "window_title": "Partitari di Magazzino",
    "hwnd": 461024,
    "dialog": {
      "type": "error",
      "title": "Partitari di Magazzino",
      "message": "Incongruenza tra il valore del campo Data Iniziale e il valore del campo Data Finale",
      "buttons": ["OK"],
      "clicked_button": null,
      "dialog_hwnd": 461024,
      "opened_at": "2026-03-23T21:11:44.100Z"
    },
    "triggered_by": {
      "event_type": "mouse_click",
      "control_name": "cmdAvvio",
      "control_type": "Button"
    }
  }
}
```

Evento arricchito con visual checkpoint:

```json
{
  "event_type": "mouse_click",
  "timestamp_utc": "2026-03-23T13:48:20.120000+00:00",
  "payload": {
    "x": 542,
    "y": 312,
    "button": "Button.left",
    "pressed": false,
    "window_title": "Visualizzazione e Stampa Partitari di Magazzino (A00504.01)",
    "process_name": "A00504.exe",
    "hwnd": 460600,
    "ui_target": {
      "control_name": "OK",
      "control_id": "1012",
      "control_type": "Button",
      "label": "OK",
      "text": "OK",
      "bounds": [500, 290, 580, 330]
    },
    "visual_checkpoint": {
      "enabled": true,
      "event_sequence": 123,
      "window_image_path": "artifacts/screenshots/000123_mouse_click_window.png",
      "control_image_path": "artifacts/crops/000123_mouse_click_control.png",
      "capture_scope": "window+control",
      "capture_stage": "after",
      "window_bounds": [420, 180, 980, 640],
      "control_bounds": [500, 290, 580, 330],
      "capture_success": true,
      "capture_error": null,
      "window_image_width": 560,
      "window_image_height": 460,
      "window_image_sha256": "f07d6c2f2b2d5a4ed7f7f8692aa4f2f3be7858d6d4b7f217c8f8e1c0e55b998d",
      "control_image_width": 80,
      "control_image_height": 40,
      "control_image_sha256": "7107b6d4bd1f0b8d35e5f5f99eb9bd0b0cfd7d2c8d5bf65a9ce14d458be2db21",
      "window_title": "Visualizzazione e Stampa Partitari di Magazzino (A00504.01)",
      "process_name": "A00504.exe",
      "hwnd": 460600,
      "control_identity_key": "1012"
    }
  }
}
```

## Note operative

- Se l'app target gira come amministratore, conviene eseguire anche questo recorder come amministratore.
- Per alcuni applicativi molto custom, `target_element` può essere parziale o assente.
- Il filtro non è più solo sulla finestra attiva: per gli eventi mouse/tastiera vengono confrontati finestra, top-level del controllo e metadati di processo dell'elemento.
- Questo è utile soprattutto per app hostate o multi-processo come UWP / `ApplicationFrameHost`, dove il controllo UI e la finestra top-level possono avere processi diversi.
- Per i controlli Win32 classici il recorder prova a leggere anche lo stato nativo del controllo: testo degli `Edit`, selezione e indice delle `ComboBox`/`ListBox`, stato di `CheckBox`/`RadioButton`, `control_id`, stile Win32 e testi preview.
- Il layer `ui_target` è costruito in `recorder/ui_resolver.py` e non sostituisce i campi storici (`window`, `target_element`, `target_state`): li affianca per mantenere retrocompatibilità.
- Il nuovo layer semantico è additivo: `window_context`, `control_context`, `state_before`, `state_after`, `dialog`, `ui_checkpoint` e `provenance` possono essere assenti o `null` quando i dati non sono disponibili.
- `control_context.label` e `provenance` espongono `source`, `confidence` e `inference_method` per distinguere ciò che arriva direttamente da runtime/evento da ciò che è inferito.
- La generazione degli eventi `input_commit` è separata in `recorder/semantic_events.py`, così la cattura raw e la semantica restano disaccoppiate.
- Il runtime observer arricchisce gli eventi di sistema con `element`, `control_state`, `previous_control_state` e `control_state_changes`, così i `value_change` e `state_change` sono più leggibili.
- I flag di arricchimento semantico disponibili da CLI sono: `--disable-enrich-control-identity`, `--disable-enrich-control-state`, `--disable-enrich-label-mapping`, `--disable-enrich-dialogs`, `--disable-enrich-grid-context`, `--disable-enrich-ui-snapshots`, `--disable-confidence-metadata`, `--ui-snapshot-max-controls`.
- La raccolta estesa dello stato dei controlli e dei diff prima/dopo è disponibile solo in modalità esplicita `--enable-state-capture`. Di default è disattivata perché su alcune applicazioni legacy può provocare effetti collaterali indesiderati.
- I visual checkpoints sono attivi di default. Catturano una sola immagine `after` per evento rilevante: click mouse rilasciato, `input_commit`, apertura dialog/finestra e runtime `value_change` / `state_change` significativi.
- Da GUI puoi disabilitarli con la checkbox `Disable visual checkpoints`; da CLI puoi usare `--disable-visual-checkpoints`.
- Se i bounds del controllo non sono affidabili viene salvata solo la finestra; se fallisce anche la cattura finestra il recorder continua e il payload riporta `capture_success=false`.
- In questa fase non vengono eseguiti OCR o analisi AI delle immagini: il layer serve solo a catturare, salvare e collegare l’evidenza visiva ai log.
- Impatto atteso: lieve overhead sui soli eventi chiave. Evitata volutamente la cattura su ogni `key_down` per non introdurre rumore o fragilità.

## Prossimi step consigliati

1. normalizzazione da raw event a step semantici
2. screenshot opzionali sugli eventi importanti
3. replay basato su selector UIA
4. confronto sessioni tra due applicativi
