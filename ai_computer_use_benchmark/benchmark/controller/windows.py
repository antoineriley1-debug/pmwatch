"""Windows implementation of the interaction controller."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from .base import ComputerController, WindowInfo

ALLOWED_KEYS = {"enter", "escape", "tab", "space", "pagedown", "pageup", "home", "end",
                "up", "down", "left", "right", "backspace"}


def enable_dpi_awareness() -> None:
    """Make screenshots and mouse coordinates use the same physical pixels."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class WindowsController(ComputerController):
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("WindowsController requires Windows.")
        enable_dpi_awareness()
        import pyautogui
        pyautogui.FAILSAFE = True   # slamming the mouse into a corner also aborts
        pyautogui.PAUSE = 0.05
        self._gui = pyautogui
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

    def click(self, x: int, y: int) -> None:
        self._gui.moveTo(x, y, duration=0.25)
        self._gui.click(x, y)

    def type_text(self, text: str) -> None:
        if text.isascii():
            self._gui.write(text, interval=0.03)
        else:
            self._paste(text)

    def _paste(self, text: str) -> None:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        self._gui.hotkey("ctrl", "v")
        root.destroy()

    def select_all(self) -> None:
        self._gui.hotkey("ctrl", "a")

    def press_key(self, key: str) -> None:
        if key not in ALLOWED_KEYS:
            raise ValueError(f"Key '{key}' is not permitted.")
        self._gui.press(key)

    def scroll(self, x: int, y: int, clicks: int) -> None:
        self._gui.moveTo(x, y, duration=0.15)
        self._gui.scroll(clicks * 120, x=x, y=y)

    def release_all(self) -> None:
        for key in ("ctrl", "shift", "alt", "win"):
            try:
                self._gui.keyUp(key)
            except Exception:
                pass
        try:
            self._gui.mouseUp()
        except Exception:
            pass

    def activate_window(self, title_substring: str) -> bool:
        needle = title_substring.strip().lower()
        if not needle:
            return False
        found = []
        EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _):
            if self._user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(512)
                self._user32.GetWindowTextW(hwnd, buf, 512)
                if needle in buf.value.lower():
                    found.append(hwnd)
                    return False
            return True

        self._user32.EnumWindows(EnumProc(visit), 0)
        if not found:
            return False
        SW_RESTORE = 9
        self._user32.ShowWindow(found[0], SW_RESTORE)
        return bool(self._user32.SetForegroundWindow(found[0]))

    def foreground_window(self) -> WindowInfo | None:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None
        title = ctypes.create_unicode_buffer(512)
        self._user32.GetWindowTextW(hwnd, title, 512)
        cls = ctypes.create_unicode_buffer(256)
        self._user32.GetClassNameW(hwnd, cls, 256)
        rect = wintypes.RECT()
        self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return WindowInfo(title=title.value, class_name=cls.value,
                          process=self._process_name(pid.value),
                          rect=(rect.left, rect.top, rect.right, rect.bottom))

    def _process_name(self, pid: int) -> str:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if self._kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1].lower()
            return ""
        finally:
            self._kernel32.CloseHandle(handle)
