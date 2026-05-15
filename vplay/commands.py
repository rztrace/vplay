from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ParsedCommand:
    verb: str
    key: str = ""
    value: str = ""


def parse_command(raw: str) -> ParsedCommand:
    text = raw.strip().lstrip(":").strip()
    if not text:
        return ParsedCommand("empty")
    if text in {"w", "q", "fish"}:
        return ParsedCommand(text)
    if text.endswith("?"):
        return ParsedCommand("help", text[:-1])
    if text == "status":
        return ParsedCommand("status", "all")
    if text.startswith("status "):
        return ParsedCommand("status", text[7:].strip() or "all")
    if text.startswith("unset "):
        return ParsedCommand("unset", text[6:].strip())
    if text.startswith("set "):
        rest = text[4:].strip()
        if "=" not in rest:
            return ParsedCommand("bad", "set", "expected key=value")
        key, value = rest.split("=", 1)
        return ParsedCommand("set", key.strip(), value.strip())
    return ParsedCommand("unknown", value=text)


def parse_timestamp(value: str) -> Optional[float]:
    try:
        parts = value.split(":")
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None


def shell_words(value: str) -> list[str]:
    if not value:
        return []
    return shlex.split(value)

