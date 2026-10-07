"""Control Dashboard (spec section 9)."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..config import (DEFAULT_MIN_DWELL_SECONDS, DWELL_PRESETS, EMERGENCY_STOP_LABEL, MAX_DWELL_SECONDS,
                      MIN_DWELL_SECONDS, RECOVERY_FAILURE_POLICIES, RunConfig, format_seconds, parse_duration)
from ..reasoning.registry import AVAILABLE_MODELS, create_model

CUSTOM = "Custom"
POLL_MS = 250

LIVE_FIELDS = [
    ("question", "Question:"),
    ("state", "Current State:"),
    ("question_elapsed", "Elapsed Question:"),
    ("minimum_time", "Minimum Time:"),
    ("confidence", "AI Confidence:"),
    ("answered", "Questions Answered:"),
    ("skipped", "Skipped:"),
    ("navigation_errors", "Navigation Errors:"),
    ("recovery_attempts", "Recovery Attempts:"),
    ("overall_accuracy", "Overall Accuracy:"),
    ("total_run_time", "Total Run Time:"),
]


class Dashboard:
    def __init__(self, controller_factory):
        self.controller_factory = controller_factory
        self.orchestrator = None
        self._last_status = "IDLE"
        self.root = tk.Tk()
        self.root.title("AI Computer-Use Intelligence Benchmark")
        self.root.minsize(760, 560)
        self.root.bind_all("<Control-Shift-F12>", lambda _e: self.emergency_stop())
        self._build()
        self._refresh_buttons("IDLE")
        self.root.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Live.TLabel", font=("Consolas", 12))
        style.configure("LiveValue.TLabel", font=("Consolas", 12, "bold"))

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        self.header = ttk.Label(outer, text="AI BENCHMARK — IDLE", style="Header.TLabel")
        self.header.pack(anchor="w")

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True, pady=(8, 0))

        live = ttk.LabelFrame(body, text="Live", padding=10)
        live.pack(side="left", fill="both", expand=True)
        self.live_vars = {}
        for row, (key, title) in enumerate(LIVE_FIELDS):
            ttk.Label(live, text=title, style="Live.TLabel").grid(row=row, column=0, sticky="w", pady=1)
            var = tk.StringVar(value="--")
            ttk.Label(live, textvariable=var, style="LiveValue.TLabel").grid(row=row, column=1, sticky="w", padx=(12, 0))
            self.live_vars[key] = var
        self.message_var = tk.StringVar(value="")
        ttk.Label(live, textvariable=self.message_var, wraplength=330).grid(
            row=len(LIVE_FIELDS), column=0, columnspan=2, sticky="w", pady=(10, 0))

        settings = ttk.LabelFrame(body, text="Settings", padding=10)
        settings.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.inputs = []
        self.v_name = tk.StringVar(value="CASE-STUDY-001")
        self.v_model = tk.StringVar(value=AVAILABLE_MODELS[0])
        preset_labels = [label for label, _ in DWELL_PRESETS] + [CUSTOM]
        default_label = next(l for l, v in DWELL_PRESETS if v == DEFAULT_MIN_DWELL_SECONDS)
        self.v_min_preset = tk.StringVar(value=default_label)
        self.v_min_custom = tk.StringVar(value="")
        self.v_max = tk.StringVar(value="10:00")
        self.v_conf = tk.IntVar(value=60)
        self.v_skip = tk.BooleanVar(value=False)
        self.v_recovery = tk.IntVar(value=3)
        self.v_policy = tk.StringVar(value="pause")
        self.v_shots = tk.BooleanVar(value=True)
        self.v_events = tk.BooleanVar(value=True)
        self.v_locked = tk.BooleanVar(value=True)
        self.v_window = tk.StringVar(value="")
        self.v_focus = tk.BooleanVar(value=True)
        self.v_max_actions = tk.IntVar(value=60)

        rows = [
            ("Test / run name", ttk.Entry(settings, textvariable=self.v_name, width=26)),
            ("AI model", ttk.Combobox(settings, textvariable=self.v_model, values=AVAILABLE_MODELS,
                                      state="readonly", width=24)),
            ("Minimum time / question", self._min_time_widget(settings, preset_labels)),
            ("Maximum question time", ttk.Entry(settings, textvariable=self.v_max, width=10)),
            ("Confidence threshold (%)", ttk.Spinbox(settings, from_=0, to=100, textvariable=self.v_conf, width=6)),
            ("Allow skipping", ttk.Checkbutton(settings, variable=self.v_skip)),
            ("Maximum recovery attempts", ttk.Spinbox(settings, from_=1, to=10, textvariable=self.v_recovery, width=6)),
            ("On recovery failure", ttk.Combobox(settings, textvariable=self.v_policy,
                                                 values=list(RECOVERY_FAILURE_POLICIES), state="readonly", width=12)),
            ("Screenshot logging", ttk.Checkbutton(settings, variable=self.v_shots)),
            ("Detailed event logging", ttk.Checkbutton(settings, variable=self.v_events)),
            ("Benchmark Mode (locked)", ttk.Checkbutton(settings, variable=self.v_locked)),
            ("Allowed application window", ttk.Entry(settings, textvariable=self.v_window, width=26)),
            ("Pause when target loses focus", ttk.Checkbutton(settings, variable=self.v_focus)),
            ("Max consecutive actions", ttk.Spinbox(settings, from_=5, to=500, textvariable=self.v_max_actions, width=6)),
        ]
        for r, (label, widget) in enumerate(rows):
            ttk.Label(settings, text=label).grid(row=r, column=0, sticky="w", pady=2)
            widget.grid(row=r, column=1, sticky="w", padx=(10, 0), pady=2)
            self.inputs.append(widget)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 0))
        self.b_start = ttk.Button(buttons, text="START", command=self.start)
        self.b_pause = ttk.Button(buttons, text="PAUSE", command=self.pause)
        self.b_resume = ttk.Button(buttons, text="RESUME", command=self.resume)
        self.b_stop = ttk.Button(buttons, text="STOP", command=self.stop)
        for b in (self.b_start, self.b_pause, self.b_resume, self.b_stop):
            b.pack(side="left", padx=(0, 8))
        self.b_emergency = tk.Button(buttons, text=f"EMERGENCY STOP  ({EMERGENCY_STOP_LABEL})",
                                     bg="#c62828", fg="white", activebackground="#8e0000",
                                     activeforeground="white", font=("Segoe UI", 11, "bold"),
                                     command=self.emergency_stop)
        self.b_emergency.pack(side="right")

    def _min_time_widget(self, parent, preset_labels):
        frame = ttk.Frame(parent)
        combo = ttk.Combobox(frame, textvariable=self.v_min_preset, values=preset_labels, state="readonly", width=8)
        combo.pack(side="left")
        self.min_custom_entry = ttk.Entry(frame, textvariable=self.v_min_custom, width=7)
        self.min_custom_entry.pack(side="left", padx=(6, 0))
        self._custom_widgets = [combo, self.min_custom_entry]
        return frame

    # ------------------------------------------------------------------ config
    def _config(self) -> RunConfig:
        preset = self.v_min_preset.get()
        if preset == CUSTOM:
            minimum = parse_duration(self.v_min_custom.get() or "0")
        else:
            minimum = dict(DWELL_PRESETS)[preset]
        if not MIN_DWELL_SECONDS <= minimum <= MAX_DWELL_SECONDS:
            raise ValueError(f"Minimum time must be between {format_seconds(MIN_DWELL_SECONDS)} "
                             f"and {format_seconds(MAX_DWELL_SECONDS)}.")
        config = RunConfig(
            run_name=self.v_name.get().strip(),
            model_id=self.v_model.get(),
            min_question_seconds=minimum,
            max_question_seconds=parse_duration(self.v_max.get()),
            confidence_threshold=int(self.v_conf.get()),
            allow_skipping=bool(self.v_skip.get()),
            max_recovery_attempts=int(self.v_recovery.get()),
            recovery_failure_policy=self.v_policy.get(),
            screenshot_logging=bool(self.v_shots.get()),
            detailed_event_logging=bool(self.v_events.get()),
            benchmark_mode=bool(self.v_locked.get()),
            target_window_title=self.v_window.get().strip(),
            pause_on_focus_loss=bool(self.v_focus.get()),
            max_consecutive_actions=int(self.v_max_actions.get()),
            output_dir=os.path.abspath("runs"),
        )
        config.validate()
        return config

    # ------------------------------------------------------------------ controls
    def start(self) -> None:
        from ..orchestrator import Orchestrator
        try:
            config = self._config()
            model = create_model(config.model_id)
            controller = self.controller_factory()
            self.orchestrator = Orchestrator(config, model, controller)
        except Exception as exc:
            messagebox.showerror("Cannot start", str(exc))
            return
        self._set_inputs_enabled(False)   # configuration is frozen for the run
        self._last_status = "IDLE"
        self.orchestrator.start()
        # Get the dashboard off the screen the AI is looking at.
        self.root.after(500, self.root.iconify)

    def pause(self) -> None:
        if self.orchestrator:
            self.orchestrator.pause("operator")

    def resume(self) -> None:
        if self.orchestrator:
            self.orchestrator.resume()

    def stop(self) -> None:
        if self.orchestrator:
            self.orchestrator.stop()

    def emergency_stop(self) -> None:
        if self.orchestrator:
            self.orchestrator.emergency_stop()
        self.root.deiconify()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        state = "!disabled" if enabled else "disabled"
        for widget in self.inputs + self._custom_widgets:
            try:
                widget.state([state])
            except (tk.TclError, AttributeError):
                pass

    def _refresh_buttons(self, status: str) -> None:
        running = status in ("RUNNING", "PAUSED")
        self.b_start.state(["disabled" if running else "!disabled"])
        self.b_pause.state(["!disabled" if status == "RUNNING" else "disabled"])
        self.b_resume.state(["!disabled" if status == "PAUSED" else "disabled"])
        self.b_stop.state(["!disabled" if running else "disabled"])

    # ------------------------------------------------------------------ live view
    def _poll(self) -> None:
        if self.orchestrator:
            snap = self.orchestrator.snapshot()
            status = snap.get("run_status", "IDLE")
            self.header.configure(text=f"AI BENCHMARK — {status}")
            number, total = snap.get("question_number"), snap.get("total_questions")
            self.live_vars["question"].set(f"{number if number is not None else '--'} / {total or '--'}")
            conf = snap.get("confidence")
            for key in ("state", "question_elapsed", "minimum_time", "answered", "skipped",
                        "navigation_errors", "recovery_attempts", "overall_accuracy", "total_run_time"):
                self.live_vars[key].set(str(snap.get(key, "--")))
            self.live_vars["confidence"].set(f"{conf}%" if conf is not None else "--")
            self.message_var.set(snap.get("message", ""))
            self._refresh_buttons(status)
            if status != self._last_status:
                # Surface the dashboard when the run needs a human or has ended.
                if status not in ("RUNNING", "IDLE"):
                    self.root.deiconify()
                if status not in ("RUNNING", "PAUSED", "IDLE"):
                    self._set_inputs_enabled(True)
                self._last_status = status
        self.root.after(POLL_MS, self._poll)

    def run(self) -> None:
        self.root.mainloop()
