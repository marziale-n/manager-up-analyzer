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

## Limitazioni attuali

- il matching è molto più robusto, ma alcuni applicativi molto custom o protetti possono comunque esporre metadati incompleti a Win32/UI Automation
- non salva screenshot
- non implementa fallback visuale
- non intercetta in modo perfetto ogni applicativo custom/non-UIA
- i tasti vengono loggati a livello di pressione/rilascio; la ricostruzione del testo digitato è solo basilare

## Cosa produce

Per ogni sessione crea una cartella dentro `output/` con:

- `events.jsonl`: stream degli eventi raw arricchiti
- `session.json`: metadati della sessione
- `summary.json`: piccolo riepilogo finale
- `runtime_timeline.jsonl`: timeline eventi del runtime observer
- `runtime_metadata.json`: metadati del runtime observer

Ogni evento contiene, quando disponibile:

- timestamp UTC
- tipo evento
- coordinate mouse
- finestra attiva
- processo attivo
- controllo UI sotto il mouse o con focus
- payload normalizzato `ui_target` con `control_name`, `control_id`, `automation_id`, `control_type`, `label`, `text`, `bounds`, `window_title`, `process_name`, `hwnd`
- stato semantico del controllo coinvolto (`target_state`)
- eventi `input_commit` per i campi editabili con valore finale leggibile
- stato dopo l'azione per click e tasti (`post_target_state`, `post_focused_state`)
- differenze tra stato prima/dopo (`target_state_changes`, `focused_state_changes`)
- stato modificatori tastiera
- semplice aggregazione del testo digitato

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
    "commit_reason": "focus_lost"
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
- La generazione degli eventi `input_commit` è separata in `recorder/semantic_events.py`, così la cattura raw e la semantica restano disaccoppiate.
- Il runtime observer arricchisce gli eventi di sistema con `element`, `control_state`, `previous_control_state` e `control_state_changes`, così i `value_change` e `state_change` sono più leggibili.
- La raccolta estesa dello stato dei controlli e dei diff prima/dopo è disponibile solo in modalità esplicita `--enable-state-capture`. Di default è disattivata perché su alcune applicazioni legacy può provocare effetti collaterali indesiderati.

## Prossimi step consigliati

1. normalizzazione da raw event a step semantici
2. screenshot opzionali sugli eventi importanti
3. replay basato su selector UIA
4. confronto sessioni tra due applicativi
