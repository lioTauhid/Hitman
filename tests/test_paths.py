import sys
from pathlib import Path

from hitman import paths


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HITMAN_HOME", str(tmp_path / "data"))
    assert paths.data_dir() == tmp_path / "data"
    assert paths.database_path() == tmp_path / "data" / "hitman.db"


def test_platform_default_and_legacy(tmp_path, monkeypatch):
    monkeypatch.delenv("HITMAN_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(paths, "LEGACY_DIR", tmp_path / ".hitman")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    expected = {
        "darwin": tmp_path / "Library" / "Application Support" / "Hitman",
        "win32": tmp_path / "AppData" / "Roaming" / "Hitman",
    }.get(sys.platform, tmp_path / "xdg" / "hitman")
    assert paths.data_dir() == expected

    legacy = tmp_path / ".hitman"
    legacy.mkdir()
    (legacy / "hitman.db").touch()
    assert paths.data_dir() == legacy  # existing data from earlier versions keeps being used


def test_display_path_uses_forward_slashes(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.display_path(tmp_path / "a" / "b.json") == "~/a/b.json"
