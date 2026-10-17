"""Small OS integrations that Qt doesn't expose, done with ctypes so no extra packages are needed.

Every function is safe to call on any platform: it does nothing (or returns None) where it doesn't apply
or when the native call fails.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import platform
import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


# ------------------------------------------------------------------ macOS

class _CGRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double),
                ("width", ctypes.c_double), ("height", ctypes.c_double)]


_objc = None


def _objc_lib():
    global _objc
    if _objc is None:
        path = ctypes.util.find_library("objc")
        if not path:
            raise OSError("libobjc not found")
        _objc = ctypes.cdll.LoadLibrary(path)
        _objc.sel_registerName.restype = ctypes.c_void_p
        _objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return _objc


def _send(receiver: int, selector: str, restype=ctypes.c_void_p, argtypes: tuple = (), *args):
    """objc_msgSend with an explicit prototype (required on Apple silicon)."""
    lib = _objc_lib()
    # Methods returning large structs use objc_msgSend_stret on Intel; Apple silicon has no stret variant.
    use_stret = restype is _CGRect and not _is_arm64()
    entry = "objc_msgSend_stret" if use_stret else "objc_msgSend"
    prototype = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
    return prototype((entry, lib))(receiver, lib.sel_registerName(selector.encode()), *args)


def _is_arm64() -> bool:
    return platform.machine() in ("arm64", "aarch64")


def _ns_window(widget: QWidget) -> int | None:
    # winId() is an NSView* only under the Cocoa platform plugin (not e.g. "offscreen").
    if not IS_MAC or QGuiApplication.platformName() != "cocoa":
        return None
    view = int(widget.winId())
    window = _send(view, "window") if view else None
    return window or None


def hide_native_title(widget: QWidget) -> None:
    """Stop macOS from drawing the window title over our own title bar."""
    try:
        window = _ns_window(widget)
        if window:
            _send(window, "setTitleVisibility:", None, (ctypes.c_long,), 1)  # NSWindowTitleHidden
    except (OSError, AttributeError, ValueError):
        pass


def traffic_lights_right_edge(widget: QWidget) -> int | None:
    """Right edge, in points, of the macOS close/minimize/zoom buttons."""
    try:
        window = _ns_window(widget)
        if not window:
            return None
        zoom = _send(window, "standardWindowButton:", ctypes.c_void_p, (ctypes.c_long,), 2)  # NSWindowZoomButton
        if not zoom:
            return None
        frame = _send(zoom, "frame", _CGRect)
        return round(frame.x + frame.width)
    except (OSError, AttributeError, ValueError):
        return None


# ---------------------------------------------------------------- Windows

def set_windows_app_id(app_id: str) -> None:
    """Group the app under its own taskbar icon instead of python.exe's."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except (OSError, AttributeError):
        pass
