from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional

from .commands import shell_words
from .models import DownloadEntry


UpdateCallback = Callable[[DownloadEntry], None]
DoneCallback = Callable[[DownloadEntry, bool], None]


class DownloadManager:
    def __init__(self, video_dir_getter: Callable[[], Path], on_update: UpdateCallback, on_done: DoneCallback):
        self._video_dir_getter = video_dir_getter
        self._on_update = on_update
        self._on_done = on_done
        self._entries: List[DownloadEntry] = []
        self._next_id = 1
        self._lock = threading.Lock()

    @property
    def entries(self) -> List[DownloadEntry]:
        with self._lock:
            return list(self._entries)

    def active(self) -> List[DownloadEntry]:
        return [entry for entry in self.entries if not entry.done]

    def start(self, url: str, filename: str = "", custom_args: str = "") -> DownloadEntry:
        output_template = self._output_template(filename)
        with self._lock:
            entry = DownloadEntry(
                id=self._next_id,
                url=url,
                filename=filename or url.rsplit("/", 1)[-1][:60] or f"download-{self._next_id}",
                output_template=output_template,
            )
            self._next_id += 1
            self._entries.append(entry)
        thread = threading.Thread(target=self._run, args=(entry, custom_args), daemon=True, name=f"vplay-dl-{entry.id}")
        thread.start()
        return entry

    def cancel(self, entry_id: int) -> bool:
        for entry in self.entries:
            if entry.id != entry_id or entry.done:
                continue
            entry.cancelled = True
            entry.status = "cancelled"
            if entry.proc:
                try:
                    entry.proc.kill()
                except OSError:
                    pass
            entry.done = True
            self._on_update(entry)
            return True
        return False

    def _run(self, entry: DownloadEntry, custom_args: str) -> None:
        command = [
            "yt-dlp",
            "-o",
            entry.output_template,
            "--no-part",
            "--newline",
            "--progress",
            "--downloader",
            "native",
            *shell_words(custom_args),
            entry.url,
        ]
        ok = False
        try:
            entry.status = "starting"
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            entry.proc = proc
            self._on_update(entry)
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                if entry.cancelled:
                    proc.kill()
                    break
                self._parse_progress(entry, raw_line.strip())
                self._on_update(entry)
            rc = proc.wait()
            ok = rc == 0 and not entry.cancelled
            entry.done = True
            entry.proc = None
            entry.percent = 100.0 if ok else entry.percent
            entry.status = "complete" if ok else ("cancelled" if entry.cancelled else "failed")
        except OSError as exc:
            entry.done = True
            entry.status = f"error: {exc}"
        finally:
            self._on_update(entry)
            self._on_done(entry, ok)

    def _output_template(self, filename: str) -> str:
        directory = self._video_dir_getter()
        if filename:
            safe = sanitize_filename(filename) or "download"
            return str(directory / f"{safe}.%(ext)s")
        return str(directory / "%(title)s.%(ext)s")

    @staticmethod
    def _parse_progress(entry: DownloadEntry, line: str) -> None:
        if not line:
            return
        entry.status = line[:100]
        percent = re.search(r"(\d+(?:\.\d+)?)%", line)
        if percent:
            try:
                entry.percent = float(percent.group(1))
            except ValueError:
                pass
        speed = re.search(r"at\s+([\d.]+\S+/s)", line)
        if speed:
            entry.speed = speed.group(1)
        eta = re.search(r"ETA\s+(\S+)", line)
        if eta:
            entry.eta = eta.group(1)


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^\w\s.-]", "", value).strip()
    return re.sub(r"\s+", " ", cleaned)


def resolve_title(url: str, custom_args: str = "", timeout: int = 12) -> tuple[str, Optional[str]]:
    command = ["yt-dlp", "--print", "title", "--no-download", *shell_words(custom_args), url]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", "timeout resolving title"
    except OSError as exc:
        return "", str(exc)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().splitlines()[0][:100], None
    stderr = (result.stderr or "").strip()
    return "", stderr[:160] or "yt-dlp could not resolve a title"

