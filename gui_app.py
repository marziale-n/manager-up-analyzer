import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from recorder.controller import RecorderController
from recorder.window_selector import WindowInfo, list_open_windows, refresh_window_reference


class RecorderApp:
    ALL_WINDOWS_OPTION = "All running applications"

    def __init__(self, root):
        self.root = root
        self.root.title("AI Recorder")
        self.root.geometry("820x420")

        self.controller = RecorderController()

        self.selected_window_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(Path.cwd() / "output"))
        self.runtime_only_var = tk.BooleanVar(value=False)
        self.disable_visual_checkpoints_var = tk.BooleanVar(value=False)
        self.disable_state_capture_var = tk.BooleanVar(value=False)
        self.disable_logging = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Idle")

        self.windows: list[WindowInfo] = []

        self._build_ui()
        self._refresh_windows()

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        # Window selector
        ttk.Label(frame, text="Running application (optional)").grid(row=0, column=0, sticky="w")

        selector_frame = ttk.Frame(frame)
        selector_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 12))

        self.window_combo = ttk.Combobox(
            selector_frame,
            textvariable=self.selected_window_var,
            state="readonly",
            width=85
        )
        self.window_combo.pack(side="left", fill="x", expand=True)

        ttk.Button(
            selector_frame,
            text="Refresh",
            command=self._refresh_windows
        ).pack(side="left", padx=(8, 0))

        # Output dir
        ttk.Label(frame, text="Output directory").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.output_dir_var, width=70)\
            .grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        ttk.Button(frame, text="Browse", command=self._choose_output_dir)\
            .grid(row=3, column=2, padx=(8, 0), sticky="ew")

        # Mode
        ttk.Checkbutton(
            frame,
            text="Runtime observer only",
            variable=self.runtime_only_var
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Checkbutton(
            frame,
            text="Disable visual checkpoints",
            variable=self.disable_visual_checkpoints_var
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(0, 16))

        ttk.Checkbutton(
            frame,
            text="Disable state capture",
            variable=self.disable_state_capture_var
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 16))

        ttk.Checkbutton(
            frame,
            text="Disable logging",
            variable=self.disable_logging
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 16))

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=8, column=0, columnspan=3, sticky="w")

        self.start_btn = ttk.Button(btn_frame, text="Start", command=self._start)
        self.start_btn.pack(side="left")

        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)

        # Status
        ttk.Label(frame, text="Status").grid(row=9, column=0, sticky="w", pady=(20, 0))
        ttk.Label(frame, textvariable=self.status_var).grid(row=10, column=0, sticky="w")

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def _refresh_windows(self):
        previous_selection = self.selected_window_var.get().strip()

        try:
            self.windows = list_open_windows()
        except Exception as e:
            messagebox.showerror("Error", f"Unable to load running windows:\n{e}")
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

        config = {
            "output_dir": output_dir,
            "runtime_observer_only": self.runtime_only_var.get(),
            "disable_visual_checkpoints": self.disable_visual_checkpoints_var.get(),
            "disable_state_capture": self.disable_state_capture_var.get(),
            "disable_logging": self.disable_logging.get(),
        }

        if selected_window is not None:
            refreshed_window = refresh_window_reference(selected_window)
            if refreshed_window is None:
                messagebox.showerror(
                    "Error",
                    "The selected application is no longer available. Refresh the list and select it again.",
                )
                return

            selected_window = refreshed_window
            config.update(
                {
                    "window_title": selected_window.title,
                    "process_name": selected_window.process_name,
                    "pid": selected_window.pid,
                    "hwnd": selected_window.hwnd,
                }
            )

        try:
            self.controller.start(config)
        except Exception as e:
            messagebox.showerror("Start error", str(e))
            return

        if selected_window is None:
            self.status_var.set("Recording: all running applications")
        else:
            self.status_var.set(
                f"Recording: {selected_window.process_name} — {selected_window.title}"
            )
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

    def _stop(self):
        try:
            session_dir = self.controller.stop()
        except Exception as e:
            messagebox.showerror("Stop error", str(e))
            return

        self.status_var.set("Stopped")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

        msg = "Recording completed!"
        if session_dir:
            msg += f"\n\nSession saved in:\n{session_dir}"

        messagebox.showinfo("Done", msg)


if __name__ == "__main__":
    root = tk.Tk()
    app = RecorderApp(root)
    root.mainloop()
