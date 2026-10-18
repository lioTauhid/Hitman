import gzip
import hashlib
import io
import os
import posixpath
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import deb_package  # noqa: E402
from deb_package import DebSpec, build_deb, debian_arch  # noqa: E402


def read_ar(data: bytes) -> dict[str, bytes]:
    """Parse an `ar` archive the way dpkg does: 60-byte headers, 2-byte aligned members."""
    assert data.startswith(b"!<arch>\n")
    members, pos = {}, 8
    while pos < len(data):
        header = data[pos:pos + 60]
        assert header[58:60] == b"`\n"
        name, size = header[:16].decode().strip(), int(header[48:58])
        members[name] = data[pos + 60:pos + 60 + size]
        pos += 60 + size + size % 2
    return members


def read_tar(data: bytes) -> dict[str, tarfile.TarInfo]:
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data))) as tar:
        return {info.name: info for info in tar.getmembers()}


@pytest.fixture
def spec(tmp_path):
    app = tmp_path / "dist" / "Hitman"
    (app / "_internal" / "PySide6.Qt").mkdir(parents=True)
    (app / "Hitman").write_bytes(b"\x7fELF fake executable")
    (app / "Hitman").chmod(0o755)
    (app / "_internal" / "libpython3.so.1.0").write_bytes(b"library")
    (app / "_internal" / "PySide6.Qt" / "data.txt").write_text("qt")
    os.symlink("libpython3.so.1.0", app / "_internal" / "libpython3.so")
    icons = {}
    for size in (16, 256):
        icons[size] = tmp_path / f"icon-{size}.png"
        icons[size].write_bytes(b"png %d" % size)
    (tmp_path / "LICENSE").write_text("MIT License")
    return DebSpec(app_dir=app, version="1.2.3", arch="amd64", maintainer="Jane <jane@example.com>",
                   desktop_file=SCRIPTS / "hitman.desktop", icons=icons, license_file=tmp_path / "LICENSE")


@pytest.fixture
def deb(spec, tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    return build_deb(spec, tmp_path / "out")


def test_debian_arch():
    assert debian_arch("x86_64") == "amd64"
    assert debian_arch("AMD64") == "amd64"
    assert debian_arch("aarch64") == "arm64"


def test_deb_layout(deb):
    assert deb.name == "hitman_1.2.3_amd64.deb"
    members = read_ar(deb.read_bytes())
    assert list(members) == ["debian-binary", "control.tar.gz", "data.tar.gz"]
    assert members["debian-binary"] == b"2.0\n"


def test_control_fields(deb):
    control_tar = read_ar(deb.read_bytes())["control.tar.gz"]
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(control_tar))) as tar:
        control = tar.extractfile("./control").read().decode()
    fields = dict(line.split(": ", 1) for line in control.splitlines() if not line.startswith(" "))
    assert fields["Package"] == "hitman"
    assert fields["Version"] == "1.2.3"
    assert fields["Architecture"] == "amd64"
    assert fields["Maintainer"] == "Jane <jane@example.com>"
    assert "libxcb-cursor0" in fields["Depends"]
    assert int(fields["Installed-Size"]) >= 1
    # Long description lines must be indented by one space, and the file must end with a newline.
    description = control.split("Description: ", 1)[1].splitlines()
    assert all(line.startswith(" ") for line in description[1:])
    assert control.endswith("\n")


def test_data_files_modes_and_owner(deb):
    entries = read_tar(read_ar(deb.read_bytes())["data.tar.gz"])
    for path in ("./opt/hitman/Hitman", "./usr/bin/hitman", "./usr/share/applications/hitman.desktop",
                 "./usr/share/icons/hicolor/16x16/apps/hitman.png",
                 "./usr/share/icons/hicolor/256x256/apps/hitman.png",
                 "./usr/share/doc/hitman/copyright",
                 "./opt/hitman/_internal/PySide6.Qt/data.txt"):
        assert entries[path].isfile(), path
    assert entries["./opt/hitman/Hitman"].mode == 0o755
    assert entries["./usr/bin/hitman"].mode == 0o755
    assert entries["./usr/share/applications/hitman.desktop"].mode == 0o644
    link = entries["./opt/hitman/_internal/libpython3.so"]
    assert link.issym() and link.linkname == "libpython3.so.1.0"
    assert all(info.uid == 0 and info.gid == 0 and info.uname == "root" for info in entries.values())
    assert all(info.mtime == 1700000000 for info in entries.values())


def test_every_parent_directory_is_listed(deb):
    entries = read_tar(read_ar(deb.read_bytes())["data.tar.gz"])
    dirs = {name.rstrip("/") for name, info in entries.items() if info.isdir()}
    for name in entries:
        parent = posixpath.dirname(name.rstrip("/"))
        if name != ".":  # the root entry
            assert parent in dirs, name
    assert "./opt/hitman/_internal/PySide6.Qt" in dirs


def test_launcher_runs_the_installed_app(deb):
    data = read_ar(deb.read_bytes())["data.tar.gz"]
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data))) as tar:
        launcher = tar.extractfile("./usr/bin/hitman").read().decode()
    assert launcher.startswith("#!/bin/sh\n")
    assert 'exec /opt/hitman/Hitman "$@"' in launcher


def test_md5sums_match_the_files(deb):
    members = read_ar(deb.read_bytes())
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(members["control.tar.gz"]))) as tar:
        sums = tar.extractfile("./md5sums").read().decode()
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(members["data.tar.gz"]))) as tar:
        regular = {info.name[2:] for info in tar.getmembers() if info.isfile()}
        for line in sums.splitlines():
            digest, path = line.split("  ", 1)
            assert hashlib.md5(tar.extractfile(f"./{path}").read()).hexdigest() == digest
            regular.discard(path)
    assert not regular  # every regular file has a checksum


def test_build_is_reproducible(spec, tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    first = build_deb(spec, tmp_path / "a").read_bytes()
    second = build_deb(spec, tmp_path / "b").read_bytes()
    assert first == second


def test_requires_a_built_app(spec, tmp_path):
    (spec.app_dir / "Hitman").unlink()
    with pytest.raises(FileNotFoundError):
        build_deb(spec, tmp_path / "out")


@pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb is not installed")
def test_dpkg_accepts_the_package(deb):
    info = subprocess.run(["dpkg-deb", "--info", str(deb)], capture_output=True, text=True, check=True)
    assert "Package: hitman" in info.stdout
    contents = subprocess.run(["dpkg-deb", "--contents", str(deb)], capture_output=True, text=True, check=True)
    assert "./opt/hitman/Hitman" in contents.stdout


@pytest.mark.skipif(shutil.which("ar") is None, reason="ar is not installed")
def test_system_ar_reads_the_package(deb):
    listing = subprocess.run(["ar", "t", str(deb)], capture_output=True, text=True, check=True)
    assert listing.stdout.split() == ["debian-binary", "control.tar.gz", "data.tar.gz"]


def test_desktop_entry_matches_the_package():
    entry = dict(line.split("=", 1) for line in (SCRIPTS / "hitman.desktop").read_text().splitlines()
                 if "=" in line)
    assert entry["Exec"] == deb_package.PACKAGE  # the /usr/bin launcher
    assert entry["Icon"] == deb_package.PACKAGE  # the hicolor icons
    assert entry["Type"] == "Application"


def test_installer_script_matches_the_app():
    iss = (SCRIPTS / "hitman.iss").read_text()
    assert 'AppUserModelID: "Hitman.Hitman"' in iss  # the id hitman.app sets on Windows
    assert r"{app}\Hitman.exe" in iss
