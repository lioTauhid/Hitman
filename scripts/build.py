"""Build Hitman for the current OS with PyInstaller, then package it for release.

    python scripts/build.py              (make build)    app + portable archive
    python scripts/build.py --package    (make package)  ...plus the installer for this OS

Output in dist/:
  macOS    Hitman.app         Hitman-<version>-macos-<arch>.zip  (portable; this is the release file)
  Windows  Hitman/Hitman.exe  Hitman-<version>-windows-x64.zip   + Hitman-<version>-windows-x64-setup.exe
  Linux    Hitman/Hitman      Hitman-<version>-linux-x64.tar.gz  + hitman_<version>_amd64.deb

Run it on each OS you want to ship for; PyInstaller does not cross-compile. The Windows installer needs
Inno Setup 6.3+ (https://jrsoftware.org/isdl.php); the .deb needs no extra tools.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from deb_package import DebSpec, build_deb, debian_arch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
LINUX_ICON_SIZES = (16, 32, 48, 64, 128, 256, 512)


def version() -> str:
    sys.path.insert(0, str(ROOT))
    from hitman import __version__
    return __version__


def release_name() -> str:
    system = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"Hitman-{version()}-{system}-{arch}"


def render_icons(folder: Path, sizes: tuple[int, ...]) -> dict[int, Path]:
    """Draw the app icon (the same one the app uses) as PNGs of the given sizes."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from PySide6.QtGui import QGuiApplication

    from hitman.app import app_icon

    app = QGuiApplication.instance() or QGuiApplication([])  # Qt needs an app to render pixmaps
    folder.mkdir(parents=True, exist_ok=True)
    icon, paths = app_icon(), {}
    for size in sizes:
        paths[size] = folder / f"hitman-{size}.png"
        icon.pixmap(size, size).save(str(paths[size]))
    app.processEvents()
    return paths


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


# --------------------------------------------------------------- packages

def portable_archive(icon: Path) -> Path:
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


def find_iscc() -> str | None:
    """Locate Inno Setup's command-line compiler."""
    found = shutil.which("iscc")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def windows_installer(icon: Path) -> Path:
    """Build Hitman-<version>-windows-x64-setup.exe with Inno Setup (scripts/hitman.iss)."""
    iscc = find_iscc()
    if iscc is None:
        sys.exit("Inno Setup was not found. Install it (https://jrsoftware.org/isdl.php, or "
                 "`winget install JRSoftware.InnoSetup`), then run `make package` again.")
    from PIL import Image

    ico = BUILD / "hitman.ico"
    Image.open(icon).save(ico, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    name = f"{release_name()}-setup"
    subprocess.run([
        iscc, "/Q",
        f"/DAppVersion={version()}",
        f"/DSourceDir={DIST / 'Hitman'}",
        f"/DOutputDir={DIST}",
        f"/DOutputName={name}",
        f"/DIconFile={ico}",
        str(SCRIPTS / "hitman.iss"),
    ], check=True)
    return DIST / f"{name}.exe"


def maintainer() -> str:
    """Package maintainer: HITMAN_MAINTAINER, else the git user, else the project page."""
    if os.environ.get("HITMAN_MAINTAINER"):
        return os.environ["HITMAN_MAINTAINER"]

    def git(key: str) -> str:
        result = subprocess.run(["git", "config", key], capture_output=True, text=True, cwd=ROOT)
        return result.stdout.strip()

    name, email = git("user.name"), git("user.email")
    return f"{name} <{email}>" if name and email else "Hitman <https://github.com/lioTauhid/Hitman>"


def linux_deb() -> Path:
    """Build hitman_<version>_<arch>.deb (scripts/deb_package.py)."""
    spec = DebSpec(
        app_dir=DIST / "Hitman",
        version=version(),
        arch=debian_arch(platform.machine()),
        maintainer=maintainer(),
        desktop_file=SCRIPTS / "hitman.desktop",
        icons=render_icons(BUILD / "icons", LINUX_ICON_SIZES),
        license_file=ROOT / "LICENSE",
    )
    return build_deb(spec, DIST)


# ------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description="Build Hitman for this OS.")
    parser.add_argument("--package", action="store_true",
                        help="also build the installer for this OS (Windows .exe, Linux .deb)")
    args = parser.parse_args()
    try:
        import PyInstaller.__main__
    except ImportError:
        sys.exit("PyInstaller is missing. Install the build tools first: pip install -e \".[build]\"")

    icon = render_icons(BUILD, (512,))[512]
    # The spec (scripts/hitman.spec) holds the app definition, including which Qt parts to leave out.
    PyInstaller.__main__.run([
        str(SCRIPTS / "hitman.spec"),
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
    ])
    verify(DIST / ("Hitman.app" if sys.platform == "darwin" else "Hitman"))
    outputs = [portable_archive(icon)]
    if args.package:
        if sys.platform == "win32":
            outputs.append(windows_installer(icon))
        elif sys.platform.startswith("linux"):
            outputs.append(linux_deb())
        # macOS ships the portable .zip of Hitman.app.

    print(f"\nBuilt into {DIST}:")
    for path in outputs:
        print(f"  {path.name}  ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
