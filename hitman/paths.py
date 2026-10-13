"""Filesystem locations used by the app."""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
FONTS_DIR = PACKAGE_DIR / "assets" / "fonts"


def data_dir() -> Path:
    """Folder holding the database. Override with the HITMAN_HOME env var."""
    override = os.environ.get("HITMAN_HOME")
    path = Path(override).expanduser() if override else Path.home() / ".hitman"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "hitman.db"


def display_path(path: Path | str) -> str:
    """Shorten a path under the home folder to ~/... for display."""
    path = Path(path)
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)
