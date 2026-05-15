from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Iterable, Optional

from .commands import shell_words
from .config import AppConfig
from .displays import DisplayCatalog
from .media import display_name
from .models import Chunk
from .state import atomic_json_write, read_json


class MpvController:
    def __init__(self, config: AppConfig):
        self.config = config
        self.displays = DisplayCatalog()

    @property
    def socket_path(self) -> Path:
        return self.config.runtime.socket

    def session_socket_path(self, session_id: str = "main") -> Path:
        if session_id == "main":
            return self.config.runtime.socket
        return self.config.runtime.directory / f"mpv-{_safe_session_id(session_id)}.sock"

    def session_pid_path(self, session_id: str = "main") -> Path:
        if session_id == "main":
            return self.config.runtime.pid
        return self.config.runtime.directory / f"mpv-{_safe_session_id(session_id)}.pid"

    def session_state_path(self, session_id: str = "main") -> Path:
        if session_id == "main":
            return self.config.runtime.mpv_state
        return self.config.runtime.directory / f"mpv-{_safe_session_id(session_id)}-state.json"

    def session_events_path(self, session_id: str = "main") -> Path:
        if session_id == "main":
            return self.config.runtime.mpv_events
        return self.config.runtime.directory / f"mpv-{_safe_session_id(session_id)}-events.json"

    def active_session_ids(self) -> list[str]:
        ids = []
        if self.is_running("main"):
            ids.append("main")
        for path in sorted(self.config.runtime.directory.glob("mpv-*.pid")):
            stem = path.stem
            if not stem.startswith("mpv-"):
                continue
            session_id = stem.removeprefix("mpv-")
            if self.is_running(session_id):
                ids.append(session_id)
        return ids

    def is_running(self, session_id: str = "main") -> bool:
        socket_path = self.session_socket_path(session_id)
        if not socket_path.exists():
            return False
        pid = self._read_pid(session_id)
        if pid is None:
            return True
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def request(self, command: dict, timeout: float = 0.8, session_id: str = "main") -> Optional[dict]:
        socket_path = self.session_socket_path(session_id)
        if not socket_path.exists():
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(socket_path))
                sock.sendall(json.dumps(command).encode("utf-8") + b"\n")
                response = sock.recv(65536).decode("utf-8")
        except (OSError, TimeoutError):
            return None
        try:
            return json.loads(response) if response else None
        except json.JSONDecodeError:
            return None

    def get_properties(self, props: Iterable[str], session_id: str = "main") -> dict:
        props = list(props)
        socket_path = self.session_socket_path(session_id)
        if not props or not socket_path.exists():
            return {}
        result: dict = {}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.7)
                sock.connect(str(socket_path))
                for prop in props:
                    payload = json.dumps({"command": ["get_property", prop]}).encode("utf-8") + b"\n"
                    sock.sendall(payload)
                reader = sock.makefile("r", encoding="utf-8")
                for prop in props:
                    line = reader.readline()
                    if not line:
                        break
                    try:
                        response = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if response.get("error") == "success":
                        result[prop] = response.get("data")
        except (OSError, TimeoutError):
            return result
        return result

    def get_property(self, prop: str, session_id: str = "main") -> object:
        return self.get_properties([prop], session_id=session_id).get(prop)

    def write_overlay_state(
        self,
        paths: Iterable[str],
        renames: dict,
        chunks: dict,
        volume: int,
        session_id: str = "main",
    ) -> None:
        names = {}
        for path in paths:
            basename = Path(path).name
            name = display_name(path, renames)
            if name != basename:
                names[basename] = name
        atomic_json_write(
            self.session_state_path(session_id),
            {"names": names, "chunks": dict(chunks), "volume": volume},
        )

    def read_event(self, session_id: str = "main") -> dict:
        path = self.session_events_path(session_id)
        event = read_json(path)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        if event:
            event["session_id"] = session_id
        return event

    def read_events(self) -> list[dict]:
        return [event for session_id in self.active_session_ids() if (event := self.read_event(session_id))]

    def play_file(
        self,
        filepath: str,
        *,
        paths: Iterable[str],
        renames: dict,
        chunks: dict,
        volume: int,
        muted: bool,
        screen: str,
        loop_mode: str,
        chunk: Chunk | None = None,
        extra_args: str = "",
        session_id: str = "main",
    ) -> bool:
        self.quit(session_id)
        self.write_overlay_state(paths, renames, chunks, volume, session_id)
        command = self._base_command(filepath, volume, muted, screen, session_id)
        if chunk and len(chunk) == 2:
            command.extend([f"--start={chunk[0]}", f"--end={chunk[1]}"])
        command.extend(_loop_args(loop_mode, single=True))
        command.extend(shell_words(extra_args))
        return self._spawn(command, session_id)

    def play_playlist(
        self,
        playlist: list[str],
        start: int,
        *,
        paths: Iterable[str],
        renames: dict,
        chunks: dict,
        volume: int,
        muted: bool,
        screen: str,
        loop_mode: str,
        chunk_for_index,
        extra_args: str = "",
        session_id: str = "main",
    ) -> bool:
        if not playlist:
            return False
        self.quit(session_id)
        self.write_overlay_state(paths, renames, chunks, volume, session_id)
        order = list(range(start, len(playlist))) + list(range(0, start))
        first_index = order[0]
        first = playlist[first_index]
        command = self._base_command(first, volume, muted, screen, session_id)
        first_chunk = chunk_for_index(first_index, first)
        if first_chunk and len(first_chunk) == 2:
            command.extend([f"--start={first_chunk[0]}", f"--end={first_chunk[1]}"])
        command.extend(_loop_args(loop_mode, single=False))
        command.extend(shell_words(extra_args))
        if not self._spawn(command, session_id):
            return False
        if len(order) > 1:
            time.sleep(0.25)
            for index in order[1:]:
                path = playlist[index]
                if Path(path).exists():
                    self.request({"command": ["loadfile", path, "append-play"]}, session_id=session_id)
        return True

    def quit(self, session_id: str = "main") -> None:
        socket_path = self.session_socket_path(session_id)
        pid_path = self.session_pid_path(session_id)
        if socket_path.exists():
            self.request({"command": ["quit"]}, timeout=0.3, session_id=session_id)
            time.sleep(0.15)
        pid = self._read_pid(session_id)
        if pid is not None:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        for path in (pid_path, socket_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def quit_all(self) -> None:
        for session_id in self.active_session_ids():
            self.quit(session_id)

    def detect_screen(self, preference: str) -> str:
        return self.displays.resolve(preference)

    def _base_command(self, filepath: str, volume: int, muted: bool, screen: str, session_id: str) -> list[str]:
        command = [
            "mpv",
            filepath,
            f"--input-ipc-server={self.session_socket_path(session_id)}",
            f"--script={self.config.lua_script}",
            "--input-conf=/dev/null",
            "--no-terminal",
            f"--volume={volume}",
            f"--mute={'yes' if muted else 'no'}",
            "--fs",
        ]
        if screen not in {"", "default"}:
            command.extend([f"--screen={screen}", f"--fs-screen={screen}"])
        return command

    def _spawn(self, command: list[str], session_id: str) -> bool:
        self.config.ensure_dirs()
        env = os.environ.copy()
        env["VPLAY_MPV_STATE"] = str(self.session_state_path(session_id))
        env["VPLAY_MPV_EVENTS"] = str(self.session_events_path(session_id))
        try:
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            self.session_pid_path(session_id).write_text(str(proc.pid))
        except OSError:
            return False
        for _ in range(20):
            if self.session_socket_path(session_id).exists():
                return True
            time.sleep(0.1)
        return self.session_socket_path(session_id).exists()

    def _read_pid(self, session_id: str = "main") -> Optional[int]:
        try:
            return int(self.session_pid_path(session_id).read_text().strip())
        except (OSError, ValueError):
            return None


def _loop_args(mode: str, *, single: bool) -> list[str]:
    if mode == "all" and not single:
        return ["--loop-playlist=inf"]
    if mode in {"one", "all"} and single:
        return ["--loop-file=inf"]
    if mode == "one":
        return ["--loop-file=inf"]
    if mode.isdigit() and not single:
        return [f"--loop-playlist={int(mode) + 1}"]
    return []


def _safe_session_id(session_id: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in session_id) or "main"
