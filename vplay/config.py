from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".m4v", ".mkv", ".webm", ".mov"})
DEFAULT_THEME = "amber"

THEMES: Dict[str, Dict[str, str]] = {
    "amber": {"name": "Amber", "bg": "#1a1500", "fg": "#fbbf24", "dim": "#9a6500", "border": "#cc9900", "hl": "#2a2500", "accent": "#fbbf24"},
    "matrix": {"name": "Matrix", "bg": "#001100", "fg": "#00ff00", "dim": "#007700", "border": "#00cc00", "hl": "#002200", "accent": "#ffaa00"},
    "ocean": {"name": "Ocean", "bg": "#001122", "fg": "#00d4ff", "dim": "#006688", "border": "#00aacc", "hl": "#002244", "accent": "#ff6b35"},
    "forest": {"name": "Forest", "bg": "#0a1a0a", "fg": "#4ade80", "dim": "#226633", "border": "#33aa55", "hl": "#1a2a1a", "accent": "#fbbf24"},
    "mono": {"name": "Mono", "bg": "#080808", "fg": "#ffffff", "dim": "#666666", "border": "#aaaaaa", "hl": "#1a1a1a", "accent": "#ffff00"},
}


def expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


@dataclass(frozen=True)
class RuntimePaths:
    directory: Path
    socket: Path
    pid: Path
    mpv_state: Path
    mpv_events: Path


@dataclass(frozen=True)
class AppConfig:
    config_dir: Path
    state_file: Path
    theme_file: Path
    legacy_state_file: Path
    default_video_dir: Path
    lua_script: Path
    runtime: RuntimePaths

    @classmethod
    def load(cls) -> "AppConfig":
        config_dir = expand_path(os.environ.get("VPLAY_CONFIG_DIR", "~/.config/vplay"))
        runtime_root = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
        uid = os.getuid() if hasattr(os, "getuid") else "user"
        runtime_dir = runtime_root / f"vplay-{uid}"
        package_dir = Path(__file__).resolve().parent
        return cls(
            config_dir=config_dir,
            state_file=config_dir / "state.json",
            theme_file=config_dir / "theme.txt",
            legacy_state_file=Path.home() / ".config" / "fish" / "vplay_state.json",
            default_video_dir=expand_path(os.environ.get("VPLAY_VIDEO_DIR", "~/movs")),
            lua_script=package_dir / "mpv" / "vplay.lua",
            runtime=RuntimePaths(
                directory=runtime_dir,
                socket=runtime_dir / "mpv.sock",
                pid=runtime_dir / "mpv.pid",
                mpv_state=runtime_dir / "mpv-state.json",
                mpv_events=runtime_dir / "mpv-events.json",
            ),
        )

    def ensure_dirs(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.runtime.directory.mkdir(parents=True, exist_ok=True)
