from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import DEFAULT_THEME, AppConfig
from .models import AppState


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def atomic_json_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class StateStore:
    def __init__(self, config: AppConfig):
        self.config = config

    def load(self) -> AppState:
        default_video_dir = str(self.config.default_video_dir).replace(str(Path.home()), "~")
        data = read_json(self.config.state_file)
        return AppState.from_dict(data, default_video_dir)

    def save(self, state: AppState) -> None:
        atomic_json_write(self.config.state_file, state.to_dict())

    def load_theme(self, default: str = DEFAULT_THEME) -> str:
        try:
            theme = self.config.theme_file.read_text().strip()
            return theme or default
        except OSError:
            return default

    def save_theme(self, theme: str) -> None:
        self.config.theme_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.theme_file.write_text(theme)
