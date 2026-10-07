"""Interaction controller interface. The reasoning layer never imports a
platform controller directly, so a Linux/macOS controller can be added
without touching the intelligence engine."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class WindowInfo:
    title: str
    class_name: str
    process: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom


class ComputerController(ABC):
    @abstractmethod
    def click(self, x: int, y: int) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def select_all(self) -> None: ...

    @abstractmethod
    def press_key(self, key: str) -> None: ...

    @abstractmethod
    def scroll(self, x: int, y: int, clicks: int) -> None:
        """Positive clicks scroll up, negative scroll down, with the pointer at (x, y)."""

    @abstractmethod
    def foreground_window(self) -> WindowInfo | None: ...

    def activate_window(self, title_substring: str) -> bool:
        """Bring the allowed application window to the foreground by title."""
        return False

    def release_all(self) -> None:
        """Release any held keys/buttons (used by emergency stop)."""
