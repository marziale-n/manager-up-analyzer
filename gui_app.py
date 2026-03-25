import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# Import corretti dal tuo framework originale
from recorder.controller import RecorderController
from recorder.window_selector import WindowInfo, list_open_windows, refresh_window_reference

class TextHandler(logging.Handler):
    """Gestore custom per reindirizzare i log standard di Python nella console testuale della GUI."""
    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state=tk.NORMAL)
            self.text_widget.insert(tk.END, msg + "\n")
            self.text_widget.see(tk.END)
            self.text_widget.configure(state=tk.DISABLED)
        self.text_widget.after(0, append)


class RecorderApp:
    ALL_WINDOWS_OPTION = "Tutte le applicazioni in esecuzione"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("UI Action Recorder Pro")
        self.root.geometry("850x700")
        self.root.minsize(750, 650)
        
        # Inizializza il tuo controller ufficiale
        self.controller = RecorderController()

        # ==========================================
        # 1. CONFIGURAZIONE STILE UI (UI/UX Design)
        # ==========================================
        self.style = ttk.Style(self.root)
        if 'clam' in self.style.theme_names():
            self.style.theme_use('clam')

        self.BG_MAIN = "#F3F4F6"        
        self.BG_CARD = "#FFFFFF"        
        self.TEXT_MAIN = "#1F2937"      
        self.TEXT_MUTED = "#6B7280"     
        self.ACCENT = "#3B82F6"         
        self.BTN_START = "#10B981"      
        self.BTN_START_HOVER = "#059669"
        self.BTN_STOP = "#EF4444"       
        self.BTN_STOP_HOVER = "#DC2626"
        self.BTN_NEUTRAL = "#E5E7EB"    

        self.FONT_MAIN = ("Segoe UI", 10)
        self.FONT_BOLD = ("Segoe UI", 10, "bold")
        self.FONT_CONSOLE = ("Consolas", 9)

        self.root.configure(bg=self.BG_MAIN)
        self.style.configure(".", background=self.BG_MAIN, foreground=self.TEXT_MAIN, font=self.FONT_MAIN)
        self.style.configure("Card.TFrame", background=self.BG_CARD)
        self.style.configure("TNotebook", background=self.BG_MAIN, borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=[15, 5], background="#D1D5DB", borderwidth=0)
        self.style.map("TNotebook.Tab", background=[("selected", self.BG_CARD)], foreground=[("selected", self.ACCENT)], font=[("selected", self.FONT_BOLD)])
        self.style.configure("Card.TLabelframe", background=self.BG_CARD, borderwidth=1, bordercolor="#E5E7EB")
        self.style.configure("Card.TLabelframe.Label", background=self.BG_CARD, foreground=self.ACCENT, font=self.FONT_BOLD)
        self.style.configure("TLabel", background=self.BG_CARD, foreground=self.TEXT_MAIN)
        self.style.configure("Muted.TLabel", foreground=self.TEXT_MUTED, font=("Segoe UI", 9))
        self.style.configure("TCheckbutton", background=self.BG_CARD)
        self.style.configure("TButton", padding=6, relief="flat", background=self.BTN_NEUTRAL)
        self.style.map("TButton", background=[("active", "#D1D5DB")])
        self.style.configure("Start.TButton", background=self.BTN_START, foreground="white", font=self.FONT_BOLD)
        self.style.map("Start.TButton", background=[("active", self.BTN_START_HOVER)])
        self.style.configure("Stop.TButton", background=self.BTN_STOP, foreground="white", font=self.FONT_BOLD)
        self.style.map("Stop.TButton", background=[("active", self.BTN_STOP_HOVER)])

        # ==========================================
        # 2. VARIABILI DI STATO E LOGICA
        # ==========================================
        self.selected_window_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(Path.cwd() / "output"))
        
        # Variabili originali del tuo controller
        self.runtime_only_var = tk.BooleanVar(value=False)
        self.disable_visual_checkpoints_var = tk.BooleanVar(value=False)
        self.disable_state_capture_var = tk.BooleanVar(value=False)
        self.disable_logging_var = tk.BooleanVar(value=False)  # Messo a False di default per vedere i log
        
        self.windows: list[WindowInfo] = []

        # Header visivo
        header_frame = tk.Frame(self.root, bg=self.BG_MAIN, pady=10)
        header_frame.pack(fill=tk.X, padx=20)
        tk.Label(header_frame, text="AI UI Action Recorder Pro", font=("Segoe UI", 16, "bold"), bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(side=tk.LEFT)
        self.lbl_status = tk.Label(header_frame, text="⬤ Pronta", font=("Segoe UI", 10, "bold"), bg=self.BG_MAIN, fg=self.TEXT_MUTED)
        self.lbl_status.pack(side=tk.RIGHT, pady=5)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        self.tab_settings = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.tab_settings, text="  Impostazioni  ")
        self.tab_logs = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.tab_logs, text="  Log Eventi  ")

        self.setup_settings_tab()
        self.setup_logs_tab()
        self._refresh_windows()

    def setup_settings_tab(self):
        container = ttk.Frame(self.tab_settings, style="Card.TFrame", padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        # --- Destinazione ---
        out_frame = ttk.LabelFrame(container, text=" Destinazione ", style="Card.TLabelframe", padding=15)
        out_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(out_frame, text="Cartella Output:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        entry_dir = ttk.Entry(out_frame, textvariable=self.output_dir_var)
        entry_dir.grid(row=0, column=1, sticky=tk.EW, padx=(10, 10), pady=(0, 5))
        ttk.Button(out_frame, text="Sfoglia...", command=self._choose_output_dir).grid(row=0, column=2, pady=(0, 5))
        out_frame.columnconfigure(1, weight=1)

        # --- Finestra Target ---
        target_frame = ttk.LabelFrame(container, text=" Selezione Finestra ", style="Card.TLabelframe", padding=15)
        target_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.window_combo = ttk.Combobox(target_frame, textvariable=self.selected_window_var, state="readonly")
        self.window_combo.grid(row=0, column=0, sticky=tk.EW, padx=(0, 10), pady=(0, 5))
        
        ttk.Button(target_frame, text="🔄 Aggiorna Lista", command=self._refresh_windows).grid(row=0, column=1, pady=(0, 5))
        target_frame.columnconfigure(0, weight=1)

        # --- Opzioni Core ---
        adv_frame = ttk.LabelFrame(container, text=" Configurazione Core ", style="Card.TLabelframe", padding=15)
        adv_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Checkbutton(adv_frame, text="Solo Runtime Observer (disabilita cattura input utente)", variable=self.runtime_only_var).pack(anchor=tk.W, pady=(0, 5))
        ttk.Checkbutton(adv_frame, text="Disabilita Checkpoint Visivi (Niente screenshot o crop)", variable=self.disable_visual_checkpoints_var).pack(anchor=tk.W, pady=(0, 5))
        ttk.Checkbutton(adv_frame, text="Disabilita Cattura Stato (Migliora performance su app legacy)", variable=self.disable_state_capture_var).pack(anchor=tk.W, pady=(0, 5))
        ttk.Checkbutton(adv_frame, text="Disabilita Logging Standard", variable=self.disable_logging_var).pack(anchor=tk.W)

        # --- Bottoni Azione ---
        action_frame = tk.Frame(container, bg=self.BG_CARD)
        action_frame.pack(fill=tk.X, pady=10)
        self.btn_start = ttk.Button(action_frame, text="▶ AVVIA REGISTRAZIONE", style="Start.TButton", command=self._start)
        self.btn_start.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=5)
        self.btn_stop = ttk.Button(action_frame, text="⏹ FERMA E SALVA", style="Stop.TButton", command=self._stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0), ipady=5)

    def setup_logs_tab(self):
        container = ttk.Frame(self.tab_logs, style="Card.TFrame", padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(container, wrap=tk.WORD, state=tk.DISABLED, bg="#1E1E1E", fg="#D4D4D4", font=self.FONT_CONSOLE, relief="flat", padx=10, pady=10)
        scrollbar = ttk.Scrollbar(container, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Setup del logging hook
        log_handler = TextHandler(self.log_text)
        log_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S'))
        # Aggiungiamo il nostro handler al logger root di python
        logging.getLogger().addHandler(log_handler)
        logging.getLogger().setLevel(logging.INFO)

    def log_gui_message(self, message: str):
        """Metodo per log personalizzati dell'interfaccia"""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[GUI] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _refresh_windows(self):
        previous_selection = self.selected_window_var.get().strip()

        try:
            self.windows = list_open_windows()
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile caricare le finestre:\n{e}")
            return

        values = [self.ALL_WINDOWS_OPTION, *[item.display_name for item in self.windows]]
        self.window_combo["values"] = values

        if previous_selection in values:
            self.selected_window_var.set(previous_selection)
            self.window_combo.current(values.index(previous_selection))
            return

        self.window_combo.current(0)
        self.selected_window_var.set(self.ALL_WINDOWS_OPTION)

    def _choose_output_dir(self):
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if selected:
            self.output_dir_var.set(str(Path(selected).resolve()))

    def _get_selected_window(self) -> WindowInfo | None:
        selected_display = self.selected_window_var.get().strip()
        if not selected_display or selected_display == self.ALL_WINDOWS_OPTION:
            return None

        for item in self.windows:
            if item.display_name == selected_display:
                return item
        return None

    def _start(self):
        if self.controller.is_running:
            return

        selected_window = self._get_selected_window()
        output_dir = str(Path(self.output_dir_var.get().strip()).resolve())

        # Costruisce la configurazione ESATTAMENTE come richiede il tuo controller originale
        config = {
            "output_dir": output_dir,
            "runtime_observer_only": self.runtime_only_var.get(),
            "disable_visual_checkpoints": self.disable_visual_checkpoints_var.get(),
            "disable_state_capture": self.disable_state_capture_var.get(),
            "disable_logging": self.disable_logging_var.get(),
        }

        if selected_window is not None:
            refreshed_window = refresh_window_reference(selected_window)
            if refreshed_window is None:
                messagebox.showerror("Errore", "L'applicazione selezionata non è più disponibile. Aggiorna la lista.")
                return

            selected_window = refreshed_window
            config.update({
                "window_title": selected_window.title,
                "process_name": selected_window.process_name,
                "pid": selected_window.pid,
                "hwnd": selected_window.hwnd,
            })

        try:
            # Avvio il controller ufficiale!
            self.controller.start(config)
        except Exception as e:
            messagebox.showerror("Errore di Avvio", str(e))
            return

        if selected_window is None:
            status_text = "Registrazione: TUTTE le applicazioni"
        else:
            status_text = f"Registrazione: {selected_window.process_name}"

        self.lbl_status.config(text=f"⬤ {status_text}", fg=self.BTN_START)
        self.log_gui_message("=== REGISTRAZIONE AVVIATA ===")
        
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        
        # Sposta automaticamente il focus sulla console
        self.notebook.select(self.tab_logs)

    def _stop(self):
        try:
            # Ferma il controller ufficiale e recupera la cartella
            session_dir = self.controller.stop()
        except Exception as e:
            messagebox.showerror("Errore di Arresto", str(e))
            return

        self.lbl_status.config(text="⬤ Pronta", fg=self.TEXT_MUTED)
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

        self.log_gui_message("=== REGISTRAZIONE FERMATA ===")
        if session_dir:
            self.log_gui_message(f"Dati salvati in: {session_dir}")

        msg = "Registrazione completata con successo!"
        if session_dir:
            msg += f"\n\nSessione salvata in:\n{session_dir}"

        messagebox.showinfo("Fatto", msg)

if __name__ == "__main__":
    root = tk.Tk()
    app = RecorderApp(root)
    # Assicura che la chiusura della X fermi anche i thread in background
    root.protocol("WM_DELETE_WINDOW", lambda: (app._stop() if app.controller.is_running else None, root.destroy()))
    root.mainloop()