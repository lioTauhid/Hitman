"""Build a standalone Hitman app with PyInstaller, plus a release archive.

    python scripts/build.py        (or: make build)

Output in dist/:
  macOS    Hitman.app        and Hitman-<version>-macos-<arch>.zip
  Windows  Hitman/Hitman.exe and Hitman-<version>-windows-<arch>.zip
  Linux    Hitman/Hitman     and Hitman-<version>-linux-<arch>.tar.gz

Run it on each OS you want to ship for; PyInstaller does not cross-compile.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"


def version() -> str:
    sys.path.insert(0, str(ROOT))
    from hitman import __version__
    return __version__


def release_name() -> str:
    system = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"Hitman-{version()}-{system}-{arch}"


def render_icon(path: Path) -> None:
    """Draw the app icon (the same one the app uses) to a PNG; PyInstaller converts it per OS."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from PySide6.QtGui import QGuiApplication

    from hitman.app import app_icon

    app = QGuiApplication.instance() or QGuiApplication([])  # Qt needs an app to render pixmaps
    path.parent.mkdir(parents=True, exist_ok=True)
    app_icon().pixmap(512, 512).save(str(path))
    app.processEvents()


def verify(app_path: Path) -> None:
    """Fail the build on dangling symlinks or (macOS) an invalid code signature.

    A broken signature makes macOS report a downloaded app as "damaged", so never ship one.
    """
    dangling = [p for p in app_path.rglob("*") if p.is_symlink() and not p.exists()]
    if dangling:
        sys.exit("Build check failed, dangling symlinks:\n  " + "\n  ".join(str(p) for p in dangling[:20]))
    if sys.platform == "darwin":
        result = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app_path)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(f"Build check failed, invalid code signature:\n{result.stderr}")
    print(f"Build check passed: {app_path.name}")


def package(icon: Path) -> Path:
    """Zip (or tar) the built app with a release-ready name."""
    name = release_name()
    if sys.platform == "darwin":
        archive = DIST / f"{name}.zip"
        archive.unlink(missing_ok=True)
        # ditto keeps the symlinks and code signature inside the .app bundle intact.
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(DIST / "Hitman.app"), str(archive)], check=True)
        return archive
    shutil.copy(icon, DIST / "Hitman" / "hitman.png")  # for desktop shortcuts
    fmt = "zip" if sys.platform == "win32" else "gztar"
    return Path(shutil.make_archive(str(DIST / name), fmt, root_dir=DIST, base_dir="Hitman"))


def main() -> None:
    try:
        import PyInstaller.__main__
    except ImportError:
        sys.exit("PyInstaller is missing. Install the build tools first: pip install -e \".[build]\"")

    icon = BUILD / "icon.png"
    render_icon(icon)
    # The spec (scripts/hitman.spec) holds the app definition, including which Qt parts to leave out.
    PyInstaller.__main__.run([
        str(ROOT / "scripts" / "hitman.spec"),
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
    ])
    verify(DIST / ("Hitman.app" if sys.platform == "darwin" else "Hitman"))
    archive = package(icon)
    print(f"\nBuilt into {DIST}\nRelease archive: {archive.name} ({archive.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
