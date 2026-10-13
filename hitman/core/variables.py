"""{{variable}} resolution.

Scope precedence, lowest to highest: collection variables, globals, active environment.
"""

from __future__ import annotations

import random
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping

from hitman.core.models import Variable

VAR_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

DYNAMIC: dict[str, Callable[[], str]] = {
    "$guid": lambda: str(uuid.uuid4()),
    "$timestamp": lambda: str(int(time.time())),
    "$isoTimestamp": lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "$randomInt": lambda: str(random.randint(0, 1000)),
}


def build_scope(*layers: Iterable[Variable]) -> dict[str, str]:
    """Merge variable layers; later layers win. Disabled and unnamed variables are skipped."""
    scope: dict[str, str] = {}
    for layer in layers:
        for var in layer:
            if var.enabled and var.key:
                scope[var.key] = var.value
    return scope


def is_known(name: str, scope: Mapping[str, str]) -> bool:
    name = name.strip()
    if name.startswith("$"):
        return name in DYNAMIC
    return scope.get(name, "") != ""


def resolve(text: str, scope: Mapping[str, str]) -> str:
    """Replace known {{name}} references. Unknown ones are left untouched."""
    if not text or "{{" not in text:
        return text or ""

    def repl(match: re.Match) -> str:
        name = match.group(1).strip()
        if name in DYNAMIC:
            return DYNAMIC[name]()
        value = scope.get(name, "")
        return value if value != "" else match.group(0)

    return VAR_RE.sub(repl, text)


def reference(name: str) -> str:
    return "{{" + name + "}}"
