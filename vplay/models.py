from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional


Chunk = List[float]


@dataclass
class Settings:
    video_dir: str = "~/movs"
    video_dir_mode: str = "fixed"
    volume: int = 10
    muted: bool = False
    screen: str = "auto-external"
    custom_args: Dict[str, str] = field(default_factory=dict)
    module_layout: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None, default_video_dir: str) -> "Settings":
        data = data or {}
        return cls(
            video_dir=str(data.get("video_dir") or default_video_dir),
            video_dir_mode=_video_dir_mode(data.get("video_dir_mode", "fixed")),
            volume=max(0, min(200, int(data.get("volume", 10)))),
            muted=_bool(data.get("muted", False)),
            screen=str(data.get("screen", "auto-external")),
            custom_args=dict(data.get("custom_args") or {}),
            module_layout=dict(data.get("module_layout") or {}),
        )

    def to_dict(self) -> dict:
        return {
            "video_dir": self.video_dir,
            "video_dir_mode": self.video_dir_mode,
            "volume": self.volume,
            "muted": self.muted,
            "screen": self.screen,
            "custom_args": dict(self.custom_args),
            "module_layout": dict(self.module_layout),
        }


@dataclass
class AppState:
    playlist: List[str] = field(default_factory=list)
    renames: Dict[str, str] = field(default_factory=dict)
    file_chunks: Dict[str, Chunk] = field(default_factory=dict)
    playlist_chunks: Dict[str, Chunk] = field(default_factory=dict)
    screen_options: Dict[str, dict] = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)

    @classmethod
    def from_dict(cls, data: dict | None, default_video_dir: str) -> "AppState":
        data = data or {}
        return cls(
            playlist=[str(p) for p in data.get("playlist", [])],
            renames=dict(data.get("renames") or {}),
            file_chunks=_chunks(data.get("file_chunks")),
            playlist_chunks=_chunks(data.get("playlist_chunks")),
            screen_options=dict(data.get("screen_options") or {}),
            settings=Settings.from_dict(data.get("settings"), default_video_dir),
        )

    def to_dict(self) -> dict:
        return {
            "playlist": list(self.playlist),
            "renames": dict(self.renames),
            "file_chunks": dict(self.file_chunks),
            "playlist_chunks": dict(self.playlist_chunks),
            "screen_options": dict(self.screen_options),
            "settings": self.settings.to_dict(),
        }


@dataclass
class ScreenPlaybackOptions:
    screen: str = "auto-external"
    volume: Optional[int] = None
    muted: Optional[bool] = None
    play_next: bool = False
    loop_mode: str = "off"

    @classmethod
    def from_dict(cls, data: dict | None, *, default_play_next: bool = False) -> "ScreenPlaybackOptions":
        data = data or {}
        volume = data.get("volume")
        muted = data.get("muted")
        return cls(
            screen=str(data.get("screen", "auto-external")),
            volume=max(0, min(200, int(volume))) if volume is not None else None,
            muted=_bool(muted) if muted is not None else None,
            play_next=_bool(data.get("play_next", default_play_next)),
            loop_mode=_loop_mode(data.get("loop_mode", "off")),
        )

    def to_dict(self) -> dict:
        return {
            "screen": self.screen,
            "volume": self.volume,
            "muted": self.muted,
            "play_next": self.play_next,
            "loop_mode": self.loop_mode,
        }


@dataclass
class DownloadEntry:
    id: int
    url: str
    filename: str
    output_template: str
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    status: str = "queued"
    done: bool = False
    cancelled: bool = False
    proc: Optional[subprocess.Popen[str]] = field(default=None, repr=False, compare=False)


def _chunks(raw: object) -> Dict[str, Chunk]:
    if not isinstance(raw, dict):
        return {}
    result: Dict[str, Chunk] = {}
    for key, value in raw.items():
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                start = float(value[0])
                end = float(value[1])
            except (TypeError, ValueError):
                continue
            result[str(key)] = [min(start, end), max(start, end)]
    return result


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _loop_mode(value: object) -> str:
    text = str(value)
    return text if text in {"off", "one", "all"} else "off"


def _video_dir_mode(value: object) -> str:
    text = str(value)
    return text if text in {"fixed", "cwd"} else "fixed"
