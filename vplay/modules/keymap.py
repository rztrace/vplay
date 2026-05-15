from __future__ import annotations

from dataclasses import dataclass

from .base import ModuleSpec


GLOBAL_KEYS = {
    "space",
    "shift+space",
    "tab",
    "q",
    "?",
    "/",
    "escape",
    "l",
    "y",
    "z",
    "m",
    ";",
    "+",
    "-",
}

LOCAL_KEYS = {
    "library": {"a", "r", "u", "d", "s"},
    "playlist": {"x", "J", "K", "c", "s", "u"},
}

NORMAL_MODE_CANDIDATES = ("o", "i", "p", "n", "b", "v", "g", "t", "e", "w")


@dataclass(frozen=True)
class AssignedKey:
    module_id: str
    key: str | None
    reason: str = ""


def assign_module_keys(modules: list[ModuleSpec]) -> dict[str, AssignedKey]:
    used = set(GLOBAL_KEYS)
    assigned: dict[str, AssignedKey] = {}
    for spec in modules:
        candidates = tuple(spec.key_preferences) + tuple(k for k in NORMAL_MODE_CANDIDATES if k not in spec.key_preferences)
        key = next((candidate for candidate in candidates if candidate not in used), None)
        if key:
            used.add(key)
            assigned[spec.id] = AssignedKey(spec.id, key)
        else:
            assigned[spec.id] = AssignedKey(spec.id, None, "no available normal-mode key")
    return assigned
