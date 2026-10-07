"""Safety controls (spec section 19). Every mouse/keyboard action passes
through SafetyGuard.before_action()."""
from __future__ import annotations

import threading

from ..config import EMERGENCY_STOP_HOTKEY
from .base import ComputerController

# Windows security / credential / UAC surfaces the benchmark must never touch.
SECURITY_PROCESSES = {"consent.exe", "credentialuibroker.exe", "lockapp.exe",
                      "logonui.exe", "securityhealthsystray.exe", "sechealthui.exe"}
SECURITY_CLASSES = {"credential dialog xaml host", "$$$secure ui$$$"}
SECURITY_TITLE_WORDS = ("user account control", "windows security", "smartscreen")


class ResumedAfterSafetyPause(Exception):
    """Raised after a safety pause ends: the planned action is stale and the
    caller must re-observe the screen before acting."""


class SafetyViolation(RuntimeError):
    reason = "safety"


class EmergencyStop(SafetyViolation):
    reason = "emergency_stop"


class FocusLost(SafetyViolation):
    reason = "focus_lost"


class SecurityDialog(SafetyViolation):
    reason = "security_dialog"


class ActionLimitReached(SafetyViolation):
    reason = "max_consecutive_actions"


class OutsideTargetWindow(SafetyViolation):
    reason = "outside_target_window"


class SafetyGuard:
    def __init__(self, controller: ComputerController, target_window_title: str,
                 max_consecutive_actions: int, pause_on_focus_loss: bool):
        self.controller = controller
        self.target_window_title = target_window_title.strip().lower()
        self.max_consecutive_actions = max_consecutive_actions
        self.pause_on_focus_loss = pause_on_focus_loss
        self.stop_event = threading.Event()
        self.consecutive_actions = 0
        self._listener = None
        self.on_emergency_stop = None  # callback set by the orchestrator/UI

    # ---- emergency stop ---------------------------------------------------
    def start_hotkey(self) -> bool:
        try:
            from pynput import keyboard
        except Exception:
            return False
        self._listener = keyboard.GlobalHotKeys({EMERGENCY_STOP_HOTKEY: self.emergency_stop})
        self._listener.daemon = True
        self._listener.start()
        return True

    def stop_hotkey(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    def emergency_stop(self) -> None:
        self.stop_event.set()
        try:
            self.controller.release_all()
        except Exception:
            pass
        if self.on_emergency_stop:
            self.on_emergency_stop()

    # ---- per-action checks -------------------------------------------------
    def reset_action_count(self) -> None:
        self.consecutive_actions = 0

    def before_action(self, point: tuple[int, int] | None = None) -> None:
        if self.stop_event.is_set():
            raise EmergencyStop("Emergency stop is active.")
        if self.consecutive_actions >= self.max_consecutive_actions:
            raise ActionLimitReached(
                f"{self.consecutive_actions} consecutive actions without reaching a new question.")
        window = self.controller.foreground_window()
        if window is not None:
            if self._is_security_surface(window):
                raise SecurityDialog(f"OS security dialog in foreground: '{window.title}'.")
            if self.target_window_title and self.target_window_title not in window.title.lower():
                if self.pause_on_focus_loss:
                    raise FocusLost(f"Target application lost focus (foreground: '{window.title}').")
                raise OutsideTargetWindow(f"Foreground window '{window.title}' is not the allowed application.")
            if point and self.target_window_title:
                left, top, right, bottom = window.rect
                if not (left <= point[0] < right and top <= point[1] < bottom):
                    raise OutsideTargetWindow(f"Point {point} is outside the allowed window.")
        self.consecutive_actions += 1

    @staticmethod
    def _is_security_surface(window) -> bool:
        if window.process in SECURITY_PROCESSES:
            return True
        if window.class_name.lower() in SECURITY_CLASSES:
            return True
        title = window.title.lower()
        return any(word in title for word in SECURITY_TITLE_WORDS)
