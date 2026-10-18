"""Build a Debian package (.deb) for Hitman with only the Python standard library.

A .deb is an `ar` archive holding three members: `debian-binary`, `control.tar.gz` (package metadata)
and `data.tar.gz` (the files to install). Building it directly means no dpkg tools are required, so the
package can be produced on any Linux distribution (or in CI).

Installed layout:
  /opt/hitman/                          the PyInstaller app folder
  /usr/bin/hitman                       launcher
  /usr/share/applications/hitman.desktop
  /usr/share/icons/hicolor/<N>x<N>/apps/hitman.png
  /usr/share/doc/hitman/copyright
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import stat
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = "hitman"
INSTALL_DIR = f"opt/{PACKAGE}"

# Runtime libraries the bundled Qt needs from the system (X11/Wayland, OpenGL, fonts, D-Bus).
DEPENDS = [
    "libxcb-cursor0", "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1", "libxcb-randr0",
    "libxcb-render-util0", "libxcb-shape0", "libxcb-xinerama0", "libxcb-xkb1", "libxkbcommon-x11-0",
    "libegl1", "libgl1", "libfontconfig1", "libdbus-1-3",
]

LAUNCHER = f"""#!/bin/sh
exec /{INSTALL_DIR}/Hitman "$@"
"""

DESCRIPTION = """Lightweight desktop API client
 Hitman is a fast, lightweight desktop app for testing HTTP APIs, with
 collections, environments, history, file uploads and code generation.
 No account is needed and everything is stored locally."""


@dataclass
class DebSpec:
    app_dir: Path                 # the built app folder (contains the `Hitman` executable)
    version: str
    arch: str                     # Debian architecture: amd64, arm64, ...
    maintainer: str
    desktop_file: Path
    icons: dict[int, Path]        # size in px -> PNG
    license_file: Path
    homepage: str = "https://github.com/lioTauhid/Hitman"
    depends: list[str] = field(default_factory=lambda: list(DEPENDS))


def debian_arch(machine: str) -> str:
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine.lower(),
                                                                                       machine.lower())


def file_name(spec: DebSpec) -> str:
    return f"{PACKAGE}_{spec.version}_{spec.arch}.deb"


# ------------------------------------------------------------------ data

class _Tar:
    """A tar archive with root-owned entries, written in memory."""

    def __init__(self, mtime: int):
        self.buffer = io.BytesIO()
        self.tar = tarfile.open(fileobj=self.buffer, mode="w", format=tarfile.GNU_FORMAT)
        self.mtime = mtime
        self.dirs: set[str] = set()

    def _info(self, name: str, kind: bytes, mode: int, size: int = 0) -> tarfile.TarInfo:
        info = tarfile.TarInfo(f"./{name}" if name else "./")
        info.type, info.mode, info.size, info.mtime = kind, mode, size, self.mtime
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        return info

    def directory(self, name: str) -> None:
        """Add a directory entry, and its parents first (dpkg expects every directory to be listed)."""
        name = name.strip("/")
        if name == ".":
            name = ""
        if name in self.dirs:
            return
        if name:
            self.directory(str(Path(name).parent))
        self.dirs.add(name)
        self.tar.addfile(self._info(f"{name}/" if name else "", tarfile.DIRTYPE, 0o755))

    def file(self, name: str, data: bytes, executable: bool = False) -> None:
        self.directory(str(Path(name).parent))
        self.tar.addfile(self._info(name, tarfile.REGTYPE, 0o755 if executable else 0o644, len(data)),
                         io.BytesIO(data))

    def symlink(self, name: str, target: str) -> None:
        self.directory(str(Path(name).parent))
        info = self._info(name, tarfile.SYMTYPE, 0o777)
        info.linkname = target
        self.tar.addfile(info)

    def gzipped(self) -> bytes:
        self.tar.close()
        return gzip.compress(self.buffer.getvalue(), mtime=self.mtime)


def _data_tar(spec: DebSpec, mtime: int) -> tuple[bytes, dict[str, str], int]:
    """Return (data.tar.gz, md5 sums by path, installed size in KiB)."""
    tar = _Tar(mtime)
    sums: dict[str, str] = {}
    total = 0

    def add(name: str, data: bytes, executable: bool = False) -> None:
        nonlocal total
        tar.file(name, data, executable)
        sums[name] = hashlib.md5(data).hexdigest()
        total += len(data)

    tar.directory("")
    for path in sorted(spec.app_dir.rglob("*")):
        name = f"{INSTALL_DIR}/{path.relative_to(spec.app_dir).as_posix()}"
        if path.is_symlink():
            tar.symlink(name, os.readlink(path))
        elif path.is_dir():
            tar.directory(name)
        else:
            add(name, path.read_bytes(), executable=bool(path.stat().st_mode & stat.S_IXUSR))
    add("usr/bin/hitman", LAUNCHER.encode(), executable=True)
    add("usr/share/applications/hitman.desktop", spec.desktop_file.read_bytes())
    for size, png in sorted(spec.icons.items()):
        add(f"usr/share/icons/hicolor/{size}x{size}/apps/hitman.png", png.read_bytes())
    add(f"usr/share/doc/{PACKAGE}/copyright", spec.license_file.read_bytes())
    return tar.gzipped(), sums, (total + 1023) // 1024


def control_text(spec: DebSpec, installed_kib: int) -> str:
    fields = [
        ("Package", PACKAGE),
        ("Version", spec.version),
        ("Architecture", spec.arch),
        ("Maintainer", spec.maintainer),
        ("Installed-Size", str(installed_kib)),
        ("Depends", ", ".join(spec.depends)),
        ("Section", "devel"),
        ("Priority", "optional"),
        ("Homepage", spec.homepage),
        ("Description", DESCRIPTION),
    ]
    return "".join(f"{key}: {value}\n" for key, value in fields)


def _control_tar(spec: DebSpec, sums: dict[str, str], installed_kib: int, mtime: int) -> bytes:
    tar = _Tar(mtime)
    tar.directory("")
    tar.file("control", control_text(spec, installed_kib).encode())
    tar.file("md5sums", "".join(f"{digest}  {path}\n" for path, digest in sums.items()).encode())
    return tar.gzipped()


# -------------------------------------------------------------------- ar

def _ar(members: list[tuple[str, bytes]], mtime: int) -> bytes:
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    for name, data in members:
        header = f"{name:<16}{mtime:<12}{0:<6}{0:<6}{0o100644:<8o}{len(data):<10}`\n"
        out.write(header.encode("ascii"))
        out.write(data)
        if len(data) % 2:
            out.write(b"\n")  # members are 2-byte aligned
    return out.getvalue()


def build_deb(spec: DebSpec, out_dir: Path) -> Path:
    if not (spec.app_dir / "Hitman").is_file():
        raise FileNotFoundError(f"{spec.app_dir / 'Hitman'} not found; build the app first")
    mtime = int(os.environ.get("SOURCE_DATE_EPOCH", time.time()))
    data, sums, installed_kib = _data_tar(spec, mtime)
    control = _control_tar(spec, sums, installed_kib, mtime)
    package = out_dir / file_name(spec)
    out_dir.mkdir(parents=True, exist_ok=True)
    package.write_bytes(_ar([("debian-binary", b"2.0\n"), ("control.tar.gz", control),
                             ("data.tar.gz", data)], mtime))
    return package
