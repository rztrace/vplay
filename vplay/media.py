from __future__ import annotations

import json
import os
import re
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Dict, Iterable, List, Optional

from .config import VIDEO_EXTENSIONS


def format_filename(basename: str) -> str:
    name = Path(basename).stem
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    name = name.replace("-", " ").replace("_", " ")
    name = " ".join(name.split())
    return name[:1].upper() + name[1:].lower() if name else basename


def display_name(filepath: str | Path, renames: Dict[str, str]) -> str:
    basename = Path(filepath).name
    return renames.get(basename, format_filename(basename))


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "0:00"
    total = max(0, int(float(seconds)))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def progress_bar(pos: float, total: float, width: int = 24) -> str:
    if total <= 0:
        return "-" * width
    ratio = max(0.0, min(1.0, pos / total))
    filled = int(ratio * width)
    return "=" * filled + "-" * (width - filled)


def scan_videos(directory: Path, extensions: Iterable[str] = VIDEO_EXTENSIONS) -> List[str]:
    try:
        allowed = {ext.lower() for ext in extensions}
        found = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                suffix = Path(entry.name).suffix.lower()
                if suffix in allowed:
                    found.append(entry.path)
        return sorted(found, key=lambda p: Path(p).name.lower())
    except OSError:
        return []


@dataclass(frozen=True)
class FileSignature:
    size: int
    mtime_ns: int


class MetadataCache:
    """Small stat/ffprobe cache keyed by path plus file signature."""

    def __init__(self, max_workers: int = 2):
        self._cache: Dict[str, tuple[FileSignature, dict]] = {}
        self._inflight: Dict[str, Future[dict]] = {}
        self._lock = Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vplay-meta")

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def get(self, filepath: str, deep: bool = True) -> dict:
        signature, meta = self._base_metadata(filepath)
        if signature is None:
            return meta
        with self._lock:
            cached = self._cache.get(filepath)
            if cached and cached[0] == signature and (not deep or cached[1].get("_deep")):
                return dict(cached[1])
        if deep:
            meta.update(_ffprobe_metadata(filepath))
            meta["_deep"] = True
        with self._lock:
            self._cache[filepath] = (signature, dict(meta))
        return meta

    def submit(self, filepath: str) -> Future[dict]:
        with self._lock:
            existing = self._inflight.get(filepath)
            if existing and not existing.done():
                return existing
            future = self._pool.submit(self.get, filepath, True)
            self._inflight[filepath] = future
            future.add_done_callback(lambda _future: self._forget(filepath))
            return future

    def prefetch(self, paths: Iterable[str], limit: int = 12) -> None:
        for path in list(paths)[:limit]:
            self.submit(path)

    def _forget(self, filepath: str) -> None:
        with self._lock:
            self._inflight.pop(filepath, None)

    @staticmethod
    def _base_metadata(filepath: str) -> tuple[Optional[FileSignature], dict]:
        path = Path(filepath)
        meta = {"file": path.name}
        try:
            st = path.stat()
        except OSError:
            meta.update({"size": "?", "added": "?"})
            return None, meta
        size_mb = st.st_size / (1024 * 1024)
        meta["size"] = f"{size_mb / 1024:.1f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"
        created = getattr(st, "st_birthtime", st.st_mtime)
        meta["added"] = time.strftime("%b %d, %Y", time.localtime(created))
        return FileSignature(st.st_size, st.st_mtime_ns), meta


def _ffprobe_metadata(filepath: str) -> dict:
    meta: dict = {}
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                filepath,
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return meta
    if result.returncode != 0 or not result.stdout:
        return meta
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return meta

    fmt = data.get("format") or {}
    duration = _float_or_none(fmt.get("duration"))
    meta["format_name"] = fmt.get("format_long_name") or fmt.get("format_name") or ""
    bitrate = _int_or_none(fmt.get("bit_rate"))
    if bitrate:
        meta["bitrate"] = f"{bitrate // 1000} kbps"
    tags = fmt.get("tags") or {}
    for key in ("title", "artist", "comment", "encoder", "creation_time"):
        if key in tags:
            meta[f"tag_{key}"] = str(tags[key])

    video = None
    audio = None
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video" and video is None:
            video = stream
        elif stream.get("codec_type") == "audio" and audio is None:
            audio = stream

    if video:
        width = video.get("width", "?")
        height = video.get("height", "?")
        meta["resolution"] = f"{width}x{height}"
        meta["vcodec"] = video.get("codec_name", "?")
        meta["vprofile"] = video.get("profile", "")
        meta["pix_fmt"] = video.get("pix_fmt", "")
        fps = _format_fps(video.get("r_frame_rate", ""))
        if fps:
            meta["fps"] = fps
        duration = duration or _float_or_none(video.get("duration"))

    if audio:
        meta["acodec"] = audio.get("codec_name", "?")
        meta["asample_rate"] = str(audio.get("sample_rate", ""))
        meta["achannels"] = str(audio.get("channels", ""))
        audio_bitrate = _int_or_none(audio.get("bit_rate"))
        if audio_bitrate:
            meta["abitrate"] = f"{audio_bitrate // 1000}k"

    if duration:
        meta["duration_secs"] = duration
        meta["duration"] = format_duration(duration)
    return meta


def _float_or_none(value: object) -> Optional[float]:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _format_fps(raw: object) -> str:
    text = str(raw or "")
    if "/" not in text:
        return text
    numerator, denominator = text.split("/", 1)
    try:
        den = int(denominator)
        if den == 0:
            return text
        return f"{int(numerator) / den:.0f}"
    except ValueError:
        return text

