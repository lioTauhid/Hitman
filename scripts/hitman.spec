# PyInstaller spec for Hitman. Run it through scripts/build.py (or `make build`), which renders the icon first.
# -*- mode: python -*-

import re
import sys
from pathlib import Path

from PyInstaller.depend import bindepend

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is provided by PyInstaller)
ICON = ROOT / "build" / "icon.png"
sys.path.insert(0, str(ROOT))
from hitman import __version__  # noqa: E402

# Python bindings Hitman never imports.
UNUSED_BINDINGS = ["QtNetwork", "QtQml", "QtQuick", "QtPdf", "QtOpenGL", "QtVirtualKeyboard",
                   "QtWebEngineCore", "QtWebEngineWidgets", "QtMultimedia"]

# Qt plugins Hitman doesn't need: the PDF image format, the on-screen virtual keyboard and TUIO network touch
# input. Between them they pull in Qt PDF, QML, Quick, OpenGL and Network (about 25 MB).
UNUSED_PLUGINS = re.compile(r"^(lib)?(qpdf|qtvirtualkeyboardplugin|qtuiotouchplugin)\.", re.IGNORECASE)

# Qt shared libraries on each OS: QtCore (macOS framework), Qt6Core.dll (Windows), libQt6Core.so.6 (Linux).
QT_LIBRARY = re.compile(r"^(lib)?Qt6?[A-Z]\w*(\.dll|\.so[.\d]*)?$")


def qt_key(name: str) -> str:
    """Normalize a Qt library file name across platforms: libQt6Pdf.so.6 / Qt6Pdf.dll / QtPdf -> QtPdf."""
    name = re.sub(r"^lib", "", name)
    return re.sub(r"^Qt6", "Qt", name).split(".")[0]


def is_qt_library(dest: str) -> bool:
    path = Path(dest)
    return "plugins" not in path.parts and bool(QT_LIBRARY.match(path.name))


def prune_qt(binaries, datas):
    """Drop unused plugins, then every Qt library that nothing left in the app still links against."""
    binaries = [b for b in binaries if not UNUSED_PLUGINS.match(Path(b[0]).name)]
    libraries = {qt_key(Path(b[0]).name): b for b in binaries if is_qt_library(b[0])}
    needed, queue = set(), [b for b in binaries if not is_qt_library(b[0])]
    while queue:
        entry = queue.pop()
        for referenced, _resolved in bindepend.get_imports(entry[1]):
            key = qt_key(Path(referenced).name)
            if key in libraries and key not in needed:
                needed.add(key)
                queue.append(libraries[key])
    unused = set(libraries) - needed
    print(f"Hitman: leaving out unused Qt libraries: {', '.join(sorted(unused)) or 'none'}")

    def refers_to_unused(entry) -> bool:
        # Covers the libraries themselves, macOS framework resources, and symlinks whose *target* is one
        # of them (PyInstaller adds top-level symlinks to every framework on macOS).
        dest, target = entry[0], str(entry[1] or "")
        if is_qt_library(dest) and qt_key(Path(dest).name) in unused:
            return True
        return any(f"{key}.framework" in dest or f"{key}.framework" in target for key in unused)

    return ([b for b in binaries if not refers_to_unused(b)],
            [d for d in datas if not refers_to_unused(d)])


a = Analysis(
    [str(ROOT / "hitman" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "hitman" / "assets" / "fonts"), "hitman/assets/fonts")],
    excludes=[f"PySide6.{name}" for name in UNUSED_BINDINGS] + ["tkinter", "unittest", "pydoc"],
)
a.binaries, a.datas = prune_qt(a.binaries, a.datas)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Hitman",
    console=False,
    icon=[str(ICON)],
)
coll = COLLECT(exe, a.binaries, a.datas, name="Hitman")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Hitman.app",
        icon=str(ICON),
        bundle_identifier="app.hitman.desktop",
        info_plist={
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,  # follow the system light/dark appearance
        },
    )
