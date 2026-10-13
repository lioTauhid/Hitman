"""Formatting helpers for sizes, bodies and slugs."""

from __future__ import annotations

import json
import re
from xml.dom import minidom
from xml.parsers.expat import ExpatError

PRETTY_LIMIT = 2 * 1024 * 1024  # don't reformat bodies larger than this


def human_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


def detect_format(content_type: str, body: bytes) -> str:
    """Classify a response body as JSON, XML, HTML, Text, Binary or Empty."""
    if not body:
        return "Empty"
    ctype = content_type.lower()
    if "json" in ctype:
        return "JSON"
    if "html" in ctype:
        return "HTML"
    if "xml" in ctype:
        return "XML"
    if ctype.startswith("text/") or "javascript" in ctype:
        return "Text"
    head = body[:2048]
    if b"\x00" in head:
        return "Binary"
    stripped = head.lstrip()
    if stripped[:1] in (b"{", b"["):
        try:
            json.loads(body)
            return "JSON"
        except ValueError:
            pass
    if stripped[:1] == b"<":
        return "HTML" if b"<html" in stripped[:512].lower() else "XML"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return "Binary"
    return "Text"


def pretty_body(text: str, fmt: str) -> str:
    if len(text) > PRETTY_LIMIT:
        return text
    if fmt == "JSON":
        try:
            return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except ValueError:
            return text
    if fmt == "XML":
        try:
            pretty = minidom.parseString(text.encode("utf-8")).toprettyxml(indent="  ")
            return "\n".join(line for line in pretty.splitlines() if line.strip())
        except (ExpatError, ValueError):
            return text
    return text


def beautify_json(text: str) -> str:
    """Re-indent JSON. Raises ValueError when the text is not valid JSON."""
    return json.dumps(json.loads(text), indent=2, ensure_ascii=False)


def extension_for(fmt: str) -> str:
    return {"JSON": "json", "XML": "xml", "HTML": "html", "Text": "txt"}.get(fmt, "bin")
