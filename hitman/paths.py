"""Filesystem locations used by the app."""

import os
import sys
from pathlib import Path

from hitman import APP_NAME

PACKAGE_DIR = Path(__file__).resolve().parent
FONTS_DIR = PACKAGE_DIR / "assets" / "fonts"

LEGACY_DIR = Path.home() / ".hitman"


def platform_data_dir() -> Path:
    """The conventional per-user data folder on each OS."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_NAME.lower()


def data_dir() -> Path:
    """Folder holding the database.

    Order: the HITMAN_HOME env var, an existing ~/.hitman (from earlier versions), then the OS default.
    """
    override = os.environ.get("HITMAN_HOME")
    if override:
        path = Path(override).expanduser()
    elif (LEGACY_DIR / "hitman.db").exists():
        path = LEGACY_DIR
    else:
        path = platform_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "hitman.db"


def display_path(path: Path | str) -> str:
    """Shorten a path under the home folder to ~/... for display."""
    path = Path(path)
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)
