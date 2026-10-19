"""Keyboard shortcuts: one list shared by the main window and the Settings dialog."""

from __future__ import annotations

import sys

# (action id, label, key sequence in Qt notation; "Ctrl" maps to Cmd on macOS)
SHORTCUTS = [
    ("send", "Send request", "Ctrl+Return"),
    ("new", "New request", "Ctrl+N"),
    ("save", "Save request", "Ctrl+S"),
    ("close", "Close tab", "Ctrl+W"),
    ("search", "Search requests", "Ctrl+K"),
    ("find", "Search in response", "Ctrl+F"),
    ("import", "Import", "Ctrl+O"),
    ("sidebar", "Toggle sidebar", "Ctrl+B"),
    ("code", "Generate code", "Ctrl+Alt+C"),
    ("settings", "Settings", "Ctrl+,"),
    ("next_tab", "Next tab", "Ctrl+Tab"),
    ("prev_tab", "Previous tab", "Ctrl+Shift+Tab"),
    ("shortcuts", "Keyboard shortcuts", "Ctrl+/"),
]

_MAC_KEYS = {"Ctrl": "⌘", "Meta": "⌃", "Alt": "⌥", "Shift": "⇧", "Return": "Enter"}
_PC_KEYS = {"Return": "Enter"}


def qt_sequence(sequence: str) -> str:
    """On macOS Qt's "Ctrl" is Cmd; tab cycling uses the physical Control key (Qt's "Meta"), like browsers."""
    if sys.platform == "darwin" and sequence.endswith("+Tab"):
        return sequence.replace("Ctrl", "Meta")
    return sequence


def display_keys(sequence: str) -> list[str]:
    """Split a sequence into key caps for display, using platform names."""
    mapping = _MAC_KEYS if sys.platform == "darwin" else _PC_KEYS
    return [mapping.get(k, k) for k in qt_sequence(sequence).split("+")]


def sequence_for(action: str) -> str:
    return next(sequence for name, _label, sequence in SHORTCUTS if name == action)


def display_text(sequence: str) -> str:
    joiner = "" if sys.platform == "darwin" else "+"
    return joiner.join(display_keys(sequence))
