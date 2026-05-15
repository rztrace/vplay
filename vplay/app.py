from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

try:
    from textual import events
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.timer import Timer
    from textual.widgets import Input, Label, ListItem, ListView, Static
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Textual is required. Install with: python -m pip install textual") from exc

from . import __build__, __release__, __version__
from .commands import parse_command, parse_timestamp
from .config import DEFAULT_THEME, THEMES, AppConfig, expand_path
from .downloads import DownloadManager, resolve_title
from .media import MetadataCache, display_name, format_duration, progress_bar, scan_videos
from .models import AppState, Chunk, DownloadEntry, ScreenPlaybackOptions
from .modules.base import HookPoint, ModuleSlot
from .modules.layout import ModuleLayout
from .modules.registry import ModuleRegistry
from .mpv import MpvController
from .state import StateStore
from .updates import UpdateManager
from .ui.screens import (
    AboutScreen,
    ConfirmScreen,
    DownloadQueueScreen,
    DirectoryPickerScreen,
    FolderSetupScreen,
    HelpScreen,
    MemoryAction,
    ModuleEditorScreen,
    ScreenPickerScreen,
    SettingsScreen,
    SettingsAction,
    TextInputScreen,
    ThemePickerScreen,
    UpdateScreen,
    UserMemoryScreen,
)


VOLUME_UP_KEYS = {
    "+",
    "=",
    "plus",
    "plus_sign",
    "add",
    "equal",
    "equals",
    "equal_sign",
    "equals_sign",
    "shift+equal",
    "shift+=",
    "kp_plus",
    "kp_add",
    "numpad_plus",
    "numpad_add",
}
VOLUME_DOWN_KEYS = {
    "-",
    "minus",
    "minus_sign",
    "hyphen",
    "hyphen_minus",
    "subtract",
    "kp_minus",
    "kp_subtract",
    "numpad_minus",
    "numpad_subtract",
}
FOOTER_KEY_COLOR = "#ffffff"
FOOTER_SEPARATOR = " | "


class VideoPlayerApp(App):
    ENABLE_COMMAND_PALETTE = False
    TITLE = "vplay"
    BINDINGS = []

    DEFAULT_CSS = """
    Screen { background: $background; }
    #status-bar { height: 1; dock: top; padding: 0 1; background: $panel; color: $text; }
    #main { height: 1fr; }
    #slot-left { width: 1fr; border-right: solid $primary; }
    #right-stack { width: 1fr; }
    #slot-right_top { height: 1fr; }
    #slot-right_bottom { height: 12; border-top: solid $primary; }
    .module-container { width: 1fr; height: 1fr; }
    .module-title { height: 1; padding: 0 1; background: $panel; color: $accent; text-style: bold; }
    .module-static { height: 1fr; padding: 0 1; background: $background; color: $text; }
    #lib-list, #pl-list { height: 1fr; background: $background; }
    #info-panel { height: 1fr; padding: 0 1; background: $background; }
    ListItem { height: 1; background: $background; }
    ListItem.--highlight { background: $surface; }
    ListItem.screen-options { height: 4; background: $background; }
    ListItem.playlist-screen-options { height: 3; background: $background; }
    .screen-options-label { height: auto; color: $text; }
    #search-input { dock: bottom; height: 1; display: none; background: $panel; color: $text; border: tall $primary; }
    #cmd-input { dock: bottom; height: 1; display: none; background: $background; color: $text; border: none; padding: 0; }
    #footer-bar { height: 1; dock: bottom; padding: 0 1; background: $panel; color: $text; }
    """

    def __init__(self):
        self.config = AppConfig.load()
        self.config.ensure_dirs()
        self.store = StateStore(self.config)
        self._theme_name = self.store.load_theme()
        super().__init__()
        self.state: AppState = self.store.load()
        self.registry = ModuleRegistry.discover()
        self.module_layout = ModuleLayout.from_dict(self.state.settings.module_layout, self.registry)
        self.module_hooks = self.registry.active_hooks(self.module_layout)
        self.video_dir = self._resolve_video_dir()
        self._folder_prompt_open = False
        self.all_files: List[str] = []
        self.filtered_files: List[str] = []
        self.current_file: Optional[str] = None
        self.filter_text = ""
        self.loop_mode = "off"
        self.loop_pending = False
        self.loop_timer: Optional[Timer] = None
        self.command_mode = False
        self.playlist_dirty = False
        self.last_pos = 0.0
        self.last_duration = 0.0
        self.last_paused = False
        self.screen_expanded: set[str] = set()
        self.session_state: dict[str, dict] = {}
        self.metadata = MetadataCache()
        self.metadata_requested: set[str] = set()
        self.mpv = MpvController(self.config)
        self.updates = UpdateManager(Path(__file__).resolve().parents[1], self.config.install_method)
        self.downloads = DownloadManager(self._video_dir, self._download_update, self._download_done)
        self.progress_timer: Optional[Timer] = None
        self.sync_timer: Optional[Timer] = None

    def get_css_variables(self) -> dict:
        values = super().get_css_variables()
        theme = self._theme()
        values.update(
            {
                "background": theme["bg"],
                "surface": theme["hl"],
                "foreground": theme["fg"],
                "text": theme["fg"],
                "text-muted": theme["dim"],
                "primary": theme["border"],
                "accent": theme["accent"],
                "panel": theme["hl"],
                "error": "#ff5555",
                "border": theme["border"],
                "border-blurred": theme["dim"],
                "secondary": theme["dim"],
                "scrollbar": theme["dim"],
                "scrollbar-active": theme["border"],
                "scrollbar-background": theme["bg"],
                "scrollbar-background-active": theme["bg"],
                "scrollbar-background-hover": theme["bg"],
                "scrollbar-corner-color": theme["bg"],
                "scrollbar-hover": theme["border"],
            }
        )
        return values

    def compose(self) -> ComposeResult:
        yield Static("", id="status-bar")
        with Horizontal(id="main"):
            yield from self._compose_slot("left")
            with Vertical(id="right-stack"):
                yield from self._compose_slot("right_top")
                yield from self._compose_slot("right_bottom")
        yield Input(placeholder=" type to filter", id="search-input")
        yield Input(placeholder=":", id="cmd-input")
        yield Static("", id="footer-bar")

    def _compose_slot(self, slot: ModuleSlot) -> ComposeResult:
        module_ids = self.module_layout.visible_in_slot(slot)
        split = self.module_layout.splits.get(slot, "vertical")
        with Vertical(id=f"slot-{slot}", classes="layout-slot"):
            if not module_ids:
                yield Static("", classes="module-static")
            elif len(module_ids) == 1:
                yield from self._compose_module(module_ids[0])
            else:
                splitter = Horizontal if split == "horizontal" else Vertical
                with splitter(id=f"split-{slot}", classes="module-split"):
                    for module_id in module_ids:
                        yield from self._compose_module(module_id)

    def _compose_module(self, module_id: str) -> ComposeResult:
        spec = self.registry.specs[module_id]
        safe_id = module_id.replace("_", "-")
        with Vertical(id=f"module-{safe_id}", classes="module-container"):
            yield Static(f" {spec.title}", id=f"{safe_id}-title", classes="module-title")
            if spec.renderer == "library":
                yield ListView(id="lib-list")
            elif spec.renderer == "playlist":
                yield ListView(id="pl-list")
            elif spec.renderer == "info":
                yield Static("", id="info-panel")
            else:
                content = spec.content or "\n".join(spec.capabilities) or "No content configured."
                yield Static(content, id=f"{safe_id}-content", classes="module-static")

    def on_mount(self) -> None:
        self.state.playlist = [path for path in self.state.playlist if Path(path).exists()]
        self._load_library()
        self.filtered_files = list(self.all_files)
        self.metadata.prefetch(self.filtered_files)
        self._refresh_all()
        self.query_one("#lib-list", ListView).focus()
        self.progress_timer = self.set_interval(0.5, self._sync_progress)
        self.sync_timer = self.set_interval(2.0, self._sync_full)
        if not self.video_dir.exists():
            self.call_after_refresh(self._open_missing_video_dir)

    def on_unmount(self) -> None:
        self.metadata.close()

    def _theme(self) -> dict:
        return THEMES.get(self._theme_name, THEMES[DEFAULT_THEME])

    def _video_dir(self) -> Path:
        return self.video_dir

    def _resolve_video_dir(self) -> Path:
        if self.state.settings.video_dir_mode == "cwd":
            return Path.cwd().resolve()
        return expand_path(self.state.settings.video_dir)

    @property
    def playlist(self) -> List[str]:
        return self.state.playlist

    @property
    def renames(self) -> Dict[str, str]:
        return self.state.renames

    @property
    def file_chunks(self) -> Dict[str, Chunk]:
        return self.state.file_chunks

    @property
    def playlist_chunks(self) -> Dict[str, Chunk]:
        return self.state.playlist_chunks

    def _load_library(self) -> None:
        self.all_files = scan_videos(self.video_dir)

    def _apply_filter(self) -> None:
        if not self.filter_text:
            self.filtered_files = list(self.all_files)
        else:
            query = self.filter_text.lower()
            self.filtered_files = [path for path in self.all_files if query in display_name(path, self.renames).lower()]
        self._refresh_library()
        self.metadata.prefetch(self.filtered_files)

    def _refresh_all(self) -> None:
        self._refresh_library()
        self._refresh_playlist()
        self._update_status()
        self._update_footer()
        self._update_info()

    def _refresh_library(self) -> None:
        view = self.query_one("#lib-list", ListView)
        saved = view.index or 0
        view.clear()
        theme = self._theme()
        for index, path in enumerate(self.filtered_files):
            name = display_name(path, self.renames)
            basename = Path(path).name
            active_session = self._session_for_path(path)
            is_current = active_session is not None or (self.current_file and self._files_match(path, self.current_file))
            chunk = " [chunk]" if basename in self.file_chunks else ""
            session_tag = f" [{active_session}]" if active_session else ""
            prefix = "> " if is_current else "  "
            style = f"bold {theme['fg']}" if is_current else theme["fg"]
            label = Label(f"[{style}]{prefix}{name}[/{style}][{theme['accent']}]{chunk}{session_tag}[/{theme['accent']}]")
            label.file_path = path
            label.library_index = index
            item = ListItem(label)
            item.file_path = path
            item.library_index = index
            view.append(item)
            key = self._screen_key("library", index, path)
            if self._screens_enabled() and key in self.screen_expanded:
                view.append(self._screen_options_item("library", key, path, index, theme))
        if view.children:
            view.index = min(saved, len(view.children) - 1)

    def _refresh_playlist(self) -> None:
        try:
            view = self.query_one("#pl-list", ListView)
        except Exception:
            return
        saved = view.index or 0
        view.clear()
        theme = self._theme()
        if not self.playlist:
            view.append(ListItem(Label(f"  [{theme['dim']}]Press a on a file to add it here[/{theme['dim']}]")))
        for index, path in enumerate(self.playlist):
            name = display_name(path, self.renames)
            active_session = self._session_for_path(path)
            is_current = active_session is not None or (self.current_file and self._files_match(path, self.current_file))
            chunk = " [chunk]" if self._chunk_for_playlist_index(index, path) else ""
            session_tag = f" [{active_session}]" if active_session else ""
            prefix = ">" if is_current else " "
            style = f"bold {theme['fg']}" if is_current else theme["fg"]
            text = f"[bold {theme['accent']}]{index + 1:>2}[/bold {theme['accent']}] {prefix} [{style}]{name}[/{style}][{theme['accent']}]{chunk}{session_tag}[/{theme['accent']}]"
            label = Label(text)
            label.file_path = path
            label.playlist_index = index
            item = ListItem(label)
            item.file_path = path
            item.playlist_index = index
            view.append(item)
            key = self._screen_key("playlist", index, path)
            if self._screens_enabled() and key in self.screen_expanded:
                view.append(self._screen_options_item("playlist", key, path, index, theme))
        if self._screens_enabled():
            view.append(self._playlist_screen_options_item(theme))
        if view.children:
            view.index = min(saved, len(view.children) - 1)

    def _screen_options_item(self, source: str, key: str, path: str, index: int, theme: dict) -> ListItem:
        label = Label(self._screen_options_text(source, key, path), classes="screen-options-label")
        label.screen_options_key = key
        label.file_path = path
        if source == "playlist":
            label.playlist_index = index
        else:
            label.library_index = index
        item = ListItem(label, classes="screen-options")
        item.screen_options_key = key
        item.file_path = path
        if source == "playlist":
            item.playlist_index = index
        else:
            item.library_index = index
        return item

    def _playlist_screen_options_item(self, theme: dict) -> ListItem:
        key = "playlist:global"
        label = Label(self._playlist_screen_options_text(key), classes="screen-options-label")
        label.screen_options_key = key
        label.playlist_global = True
        item = ListItem(label, classes="playlist-screen-options")
        item.screen_options_key = key
        item.playlist_global = True
        return item

    def _screen_options_text(self, source: str, key: str, path: str) -> str:
        theme = self._theme()
        opts = self._screen_options(key, source)
        runtime = self._runtime_for_key(key) or self._runtime_for_path(path)
        state = self._runtime_text(runtime)
        progress = self._runtime_progress(runtime)
        screen = self.mpv.displays.describe(opts.screen)
        volume = self._effective_volume(opts)
        muted = self._effective_muted(opts)
        next_text = "next:on" if opts.play_next else "single"
        mute_text = " muted" if muted else ""
        return "\n".join(
            [
                f"    [{theme['accent']}]screen[/{theme['accent']}] {screen}",
                f"    [{theme['accent']}]>)))[/{theme['accent']}] {_volume_slider(volume, 10)} {volume:>3}%{mute_text}   [{theme['accent']}]mode[/{theme['accent']}] {next_text} loop:{opts.loop_mode}",
                f"    [{theme['accent']}]{state}[/{theme['accent']}] {progress}",
                f"    [{theme['dim']}]p play/pause  x/Esc stop  S screen  n next  l loop  +/- vol  m mute  left/right seek[/{theme['dim']}]",
            ]
        )

    def _playlist_screen_options_text(self, key: str) -> str:
        theme = self._theme()
        opts = self._screen_options(key, "playlist", default_play_next=True)
        runtime = self._runtime_for_key(key)
        screen = self.mpv.displays.describe(opts.screen)
        volume = self._effective_volume(opts)
        muted = " muted" if self._effective_muted(opts) else ""
        state = self._runtime_text(runtime)
        return "\n".join(
            [
                f"  [{theme['accent']}]Playlist screen controls[/{theme['accent']}]  {screen}  {_volume_slider(volume, 10)} {volume:>3}%{muted}",
                f"  [{theme['accent']}]{state}[/{theme['accent']}]  next:{'on' if opts.play_next else 'off'} loop:{opts.loop_mode}",
                f"  [{theme['dim']}]Enter/p play playlist  x/Esc stop  S screen  n next  l loop  +/- vol  m mute[/{theme['dim']}]",
            ]
        )

    def _update_status(self) -> None:
        theme = self._theme()
        path_text = str(self.video_dir).replace(str(Path.home()), "~")
        count_text = f"{len(self.filtered_files)} files"
        if self.filter_text:
            count_text = f"{len(self.filtered_files)}/{len(self.all_files)} files - {self.filter_text}"
        loop = f" loop:{self.loop_mode}" if self.loop_mode != "off" else ""
        active_count = len([state for state in self.session_state.values() if state.get("running")])
        if active_count > 1:
            left = f"[bold {theme['accent']}]>{active_count}[/bold {theme['accent']}] [bold {theme['fg']}]active sessions[/bold {theme['fg']}]{loop}"
        elif self.current_file:
            left = f"[bold {theme['accent']}]>[/bold {theme['accent']}] [bold {theme['fg']}]{display_name(self.current_file, self.renames)}[/bold {theme['fg']}]{loop}"
        else:
            left = f"[{theme['dim']}]idle{loop}[/{theme['dim']}]"
        self.query_one("#status-bar", Static).update(f" {left}  [{theme['dim']}]{path_text} - {count_text}[/{theme['dim']}]")

    def _update_footer(self) -> None:
        theme = self._theme()
        pane = self._focused_pane()
        if pane == "lib":
            parts = ["Space Play", "a Add", "r Rename", "s Chunk", "y DL", "l Loop", "; Settings", "? Help", "q Quit"]
        else:
            parts = ["Space Play/Pause", "x Remove", "J/K Move", "s Chunk", "c Clear", "y DL", "l Loop", "; Settings", "? Help"]
        if self._screens_enabled():
            parts.insert(1, "S-Space/v Screens")
        footer = "  ".join(_footer_key_action(part, theme) for part in parts)
        right_items = self._footer_status_items(theme)
        if right_items:
            footer += f"  [{theme['dim']}]{FOOTER_SEPARATOR}[/{theme['dim']}]  " + "  ".join(right_items)
        self.query_one("#footer-bar", Static).update(" " + footer)

    def _footer_status_items(self, theme: dict) -> list[str]:
        items: list[str] = []
        active = self.downloads.active()
        if active:
            average = sum(entry.percent for entry in active) / len(active)
            items.append(f"{_footer_key('z')}[{theme['fg']}] DL {progress_bar(average, 100, 12)} {average:.0f}%[/{theme['fg']}]")
        for spec in self.module_hooks.for_point(HookPoint.MODULE_FOOTER):
            if spec.content:
                items.append(f"[{theme['fg']}]{spec.content}[/{theme['fg']}]")
        volume = self.state.settings.volume
        slider = _volume_slider(volume)
        mute_label = "Unmute" if self.state.settings.muted else "Mute"
        muted = f" [{theme['dim']}]muted[/{theme['dim']}]" if self.state.settings.muted else ""
        items.append(
            f"{_footer_key('>)))')}[{theme['fg']}] {slider} {volume:>3}%[/{theme['fg']}]{muted}  "
            f"{_footer_key('m')}[{theme['fg']}] {mute_label}[/{theme['fg']}]"
        )
        return items

    def _update_info(self) -> None:
        theme = self._theme()
        try:
            panel = self.query_one("#info-panel", Static)
        except Exception:
            return
        focused = self._focused_path()
        path = focused or (self.current_file if self.current_file and self.mpv.is_running() else None)
        if not path or not Path(path).exists():
            panel.update(f"  [{theme['dim']}]Select a file to see info[/{theme['dim']}]")
            return

        meta = self.metadata.get(path, deep=False)
        if path not in self.metadata_requested:
            self.metadata_requested.add(path)
            future = self.metadata.submit(path)
            future.add_done_callback(lambda _future: self.call_from_thread(self._update_info))

        lines = [f"  [bold {theme['fg']}]{display_name(path, self.renames)}[/bold {theme['fg']}]", f"  [{theme['dim']}]{meta.get('file', '?')}[/{theme['dim']}]"]
        details = []
        if meta.get("duration"):
            details.append(str(meta["duration"]))
        if meta.get("resolution"):
            res = str(meta["resolution"])
            if meta.get("fps"):
                res += f"@{meta['fps']}fps"
            details.append(res)
        if details:
            lines.append(f"  [{theme['fg']}]{' - '.join(details)}[/{theme['fg']}]")
        codecs = []
        if meta.get("vcodec"):
            codec = str(meta["vcodec"])
            if meta.get("acodec"):
                codec += f"/{meta['acodec']}"
            codecs.append(codec)
        if meta.get("size"):
            codecs.append(str(meta["size"]))
        if meta.get("bitrate"):
            codecs.append(str(meta["bitrate"]))
        if codecs:
            lines.append(f"  [{theme['dim']}]{' - '.join(codecs)}[/{theme['dim']}]")
        chunk = self._selected_chunk(path)
        if chunk:
            lines.append(f"  [{theme['accent']}]chunk {format_duration(chunk[0])} - {format_duration(chunk[1])}[/{theme['accent']}]")
        runtime = self._runtime_for_path(path)
        if runtime and runtime.get("duration", 0) > 0:
            pos = float(runtime.get("pos") or 0)
            duration = float(runtime.get("duration") or 0)
            icon = "pause" if runtime.get("paused") else "play"
            bar = progress_bar(pos, duration, 24)
            lines.append(f"  [{theme['accent']}]{icon} {format_duration(pos)}[/{theme['accent']}] [{theme['dim']}]{bar}[/{theme['dim']}] [{theme['dim']}]{format_duration(duration)}[/{theme['dim']}]")
        elif self.current_file and self._files_match(path, self.current_file) and self.last_duration > 0:
            icon = "pause" if self.last_paused else "play"
            bar = progress_bar(self.last_pos, self.last_duration, 24)
            lines.append(f"  [{theme['accent']}]{icon} {format_duration(self.last_pos)}[/{theme['accent']}] [{theme['dim']}]{bar}[/{theme['dim']}] [{theme['dim']}]{format_duration(self.last_duration)}[/{theme['dim']}]")
        panel.update("\n".join(lines))

    def _focused_pane(self) -> str:
        try:
            if self.query_one("#pl-list", ListView).has_focus:
                return "pl"
        except Exception:
            pass
        return "lib"

    def _switch_pane(self) -> None:
        if self._focused_pane() == "lib":
            try:
                self.query_one("#pl-list", ListView).focus()
            except Exception:
                self.query_one("#lib-list", ListView).focus()
        else:
            self.query_one("#lib-list", ListView).focus()
        self._update_footer()
        self._update_info()

    def _focused_path(self) -> Optional[str]:
        if self._focused_pane() == "pl":
            index = self._playlist_index()
            if index is not None and 0 <= index < len(self.playlist):
                return self.playlist[index]
            return None
        return self._library_path()

    def _library_path(self) -> Optional[str]:
        return _item_attr(self.query_one("#lib-list", ListView), "file_path")

    def _library_index(self) -> Optional[int]:
        value = _item_attr(self.query_one("#lib-list", ListView), "library_index")
        return int(value) if value is not None else None

    def _playlist_index(self) -> Optional[int]:
        try:
            view = self.query_one("#pl-list", ListView)
        except Exception:
            return None
        value = _item_attr(view, "playlist_index")
        return int(value) if value is not None else None

    def _selected_chunk(self, path: str) -> Optional[Chunk]:
        if self._focused_pane() == "pl":
            index = self._playlist_index()
            if index is not None:
                chunk = self._chunk_for_playlist_index(index, path)
                if chunk:
                    return chunk
        return self.file_chunks.get(Path(path).name)

    def _chunk_for_playlist_index(self, index: int, path: str) -> Optional[Chunk]:
        return self.playlist_chunks.get(str(index)) or self.file_chunks.get(Path(path).name)

    def _screens_enabled(self) -> bool:
        return self.module_layout.enabled.get("screens", False)

    def _screen_key(self, source: str, index: int, path: str) -> str:
        if source == "playlist":
            return f"playlist:{index}"
        return f"library:{Path(path).name}"

    def _focused_screen_context(self) -> tuple[str, str, Optional[str], int]:
        item = self._focused_item()
        if item and getattr(item, "playlist_global", False):
            return ("playlist_global", "playlist:global", None, 0)
        pane = self._focused_pane()
        if pane == "pl":
            index = self._playlist_index()
            if index is not None and 0 <= index < len(self.playlist):
                path = self.playlist[index]
                return ("playlist", self._screen_key("playlist", index, path), path, index)
            return ("playlist_global", "playlist:global", None, 0)
        path = self._library_path()
        index = self._library_index() or 0
        return ("library", self._screen_key("library", index, path) if path else "", path, index)

    def _focused_item(self) -> Optional[ListItem]:
        view_id = "#pl-list" if self._focused_pane() == "pl" else "#lib-list"
        try:
            return self.query_one(view_id, ListView).highlighted_child
        except Exception:
            return None

    def _toggle_screen_options_for_focus(self) -> None:
        source, key, path, _index = self._focused_screen_context()
        if not key:
            return
        if source == "playlist_global":
            self.notify("Playlist screen controls are always visible")
            return
        if key in self.screen_expanded:
            self.screen_expanded.remove(key)
        else:
            self.screen_expanded.add(key)
        self._refresh_library() if source == "library" else self._refresh_playlist()
        self._update_footer()

    def _handle_screen_control_key(self, key: str, event: events.Key) -> bool:
        source, option_key, path, index = self._focused_screen_context()
        if not option_key:
            return False
        row_expanded = source == "playlist_global" or option_key in self.screen_expanded
        if not row_expanded:
            return False
        if key in ("enter", "p"):
            self._play_or_pause_screen_target(source, option_key, path, index)
        elif key == "x":
            self._stop_screen_target(option_key)
        elif key == "escape":
            self._stop_screen_target(option_key)
        elif key in ("S", "shift+s"):
            self._cycle_screen_target(option_key, source)
        elif key == "n":
            self._toggle_screen_next(option_key, source)
        elif key == "l":
            self._cycle_screen_loop(option_key, source)
        elif key == "m":
            self._toggle_screen_mute(option_key, source)
        elif _event_matches(event, VOLUME_UP_KEYS):
            self._adjust_screen_volume(option_key, source, 5)
        elif _event_matches(event, VOLUME_DOWN_KEYS):
            self._adjust_screen_volume(option_key, source, -5)
        elif key in ("left", "h"):
            self._seek_screen_target(option_key, -5)
        elif key == "right":
            self._seek_screen_target(option_key, 5)
        else:
            return False
        event.prevent_default()
        event.stop()
        return True

    def _screen_options(self, key: str, source: str, default_play_next: bool = False) -> ScreenPlaybackOptions:
        if source in {"playlist", "playlist_global"}:
            default_play_next = True
        raw = self.state.screen_options.get(key)
        opts = ScreenPlaybackOptions.from_dict(raw, default_play_next=default_play_next)
        if not raw:
            opts.screen = self.state.settings.screen or "auto-external"
        elif not opts.screen:
            opts.screen = self.state.settings.screen or "auto-external"
        return opts

    def _save_screen_options(self, key: str, opts: ScreenPlaybackOptions) -> None:
        self.state.screen_options[key] = opts.to_dict()
        self._save_state()
        self._update_screen_option_labels()

    def _effective_volume(self, opts: ScreenPlaybackOptions) -> int:
        return self.state.settings.volume if opts.volume is None else opts.volume

    def _effective_muted(self, opts: ScreenPlaybackOptions) -> bool:
        return self.state.settings.muted if opts.muted is None else opts.muted

    def _session_id_for_options(self, opts: ScreenPlaybackOptions) -> tuple[str, str]:
        screen = self.mpv.detect_screen(opts.screen)
        return f"screen_{screen}", screen

    def _play_or_pause_screen_target(self, source: str, key: str, path: Optional[str], index: int) -> None:
        runtime = self._runtime_for_key(key)
        if runtime and self.mpv.is_running(str(runtime["session_id"])):
            self.mpv.request({"command": ["cycle", "pause"]}, session_id=str(runtime["session_id"]))
            return
        self._play_screen_target(source, key, path, index)

    def _play_screen_target(self, source: str, key: str, path: Optional[str], index: int) -> None:
        if source == "playlist_global":
            if not self.playlist:
                return
            source = "playlist"
            path = self.playlist[0]
            index = 0
        if not path:
            return
        opts = self._screen_options(key, source)
        session_id, screen = self._session_id_for_options(opts)
        volume = self._effective_volume(opts)
        muted = self._effective_muted(opts)
        sequence = self._screen_sequence(source, index, path, opts)
        chunk_lookup = self._screen_chunk_lookup(source, index)
        if opts.play_next and len(sequence) > 1:
            ok = self.mpv.play_playlist(
                sequence,
                0,
                paths=self.all_files,
                renames=self.renames,
                chunks=self.file_chunks,
                volume=volume,
                muted=muted,
                screen=screen,
                loop_mode=opts.loop_mode,
                chunk_for_index=chunk_lookup,
                extra_args=self.state.settings.custom_args.get("vp", ""),
                session_id=session_id,
            )
        else:
            ok = self.mpv.play_file(
                path,
                paths=self.all_files,
                renames=self.renames,
                chunks=self.file_chunks,
                volume=volume,
                muted=muted,
                screen=screen,
                loop_mode=opts.loop_mode,
                chunk=self._screen_chunk(source, index, path),
                extra_args=self.state.settings.custom_args.get("vp", ""),
                session_id=session_id,
            )
        if ok:
            self.current_file = path
            self.session_state[session_id] = {
                "session_id": session_id,
                "key": key,
                "source": source,
                "path": path,
                "screen": screen,
                "volume": volume,
                "muted": muted,
                "pos": 0.0,
                "duration": 0.0,
                "paused": False,
                "running": True,
            }
            self._refresh_all()
            self.notify(f"Playing {display_name(path, self.renames)} on screen {screen}")
        else:
            self.notify("Could not start mpv", severity="error")

    def _screen_sequence(self, source: str, index: int, path: str, opts: ScreenPlaybackOptions) -> list[str]:
        if not opts.play_next:
            return [path]
        if source == "playlist":
            if not self.playlist:
                return [path]
            return self.playlist[index:] + self.playlist[:index]
        if path in self.filtered_files:
            start = self.filtered_files.index(path)
            return self.filtered_files[start:] + self.filtered_files[:start]
        return [path]

    def _screen_chunk_lookup(self, source: str, start_index: int):
        def chunk_for_index(sequence_index: int, path: str) -> Optional[Chunk]:
            if source == "playlist" and path in self.playlist:
                original_index = (start_index + sequence_index) % len(self.playlist)
                return self._chunk_for_playlist_index(original_index, path)
            return self.file_chunks.get(Path(path).name)

        return chunk_for_index

    def _screen_chunk(self, source: str, index: int, path: str) -> Optional[Chunk]:
        if source == "playlist":
            return self._chunk_for_playlist_index(index, path)
        return self.file_chunks.get(Path(path).name)

    def _stop_screen_target(self, key: str) -> None:
        runtime = self._runtime_for_key(key)
        if runtime:
            session_id = str(runtime["session_id"])
            self.mpv.quit(session_id)
            self.session_state.pop(session_id, None)
        self.screen_expanded.discard(key)
        self._refresh_all()

    def _cycle_screen_target(self, key: str, source: str) -> None:
        opts = self._screen_options(key, source)
        opts.screen = self.mpv.displays.next_preference(opts.screen)
        self._save_screen_options(key, opts)
        runtime = self._runtime_for_key(key)
        if runtime:
            screen = self.mpv.detect_screen(opts.screen)
            self.mpv.request({"command": ["set_property", "screen", screen]}, session_id=str(runtime["session_id"]))
            self.mpv.request({"command": ["set_property", "fs-screen", screen]}, session_id=str(runtime["session_id"]))
            runtime["screen"] = screen

    def _toggle_screen_next(self, key: str, source: str) -> None:
        opts = self._screen_options(key, source)
        opts.play_next = not opts.play_next
        self._save_screen_options(key, opts)

    def _cycle_screen_loop(self, key: str, source: str) -> None:
        opts = self._screen_options(key, source)
        opts.loop_mode = {"off": "one", "one": "all", "all": "off"}.get(opts.loop_mode, "off")
        self._save_screen_options(key, opts)
        runtime = self._runtime_for_key(key)
        if runtime:
            self._apply_loop_to_session(str(runtime["session_id"]), opts.loop_mode, opts.play_next)

    def _toggle_screen_mute(self, key: str, source: str) -> None:
        opts = self._screen_options(key, source)
        opts.muted = not self._effective_muted(opts)
        self._save_screen_options(key, opts)
        runtime = self._runtime_for_key(key)
        if runtime:
            self.mpv.request({"command": ["set_property", "mute", "yes" if opts.muted else "no"]}, session_id=str(runtime["session_id"]))

    def _adjust_screen_volume(self, key: str, source: str, delta: int) -> None:
        opts = self._screen_options(key, source)
        opts.volume = max(0, min(200, self._effective_volume(opts) + delta))
        self._save_screen_options(key, opts)
        runtime = self._runtime_for_key(key)
        if runtime:
            self.mpv.request({"command": ["set_property", "volume", opts.volume]}, session_id=str(runtime["session_id"]))

    def _seek_screen_target(self, key: str, seconds: int) -> None:
        runtime = self._runtime_for_key(key)
        if runtime:
            self.mpv.request({"command": ["seek", seconds, "relative"]}, session_id=str(runtime["session_id"]))

    def _apply_loop_to_session(self, session_id: str, loop_mode: str, play_next: bool) -> None:
        if loop_mode == "all" and play_next:
            self.mpv.request({"command": ["set_property", "loop-playlist", "inf"]}, session_id=session_id)
            self.mpv.request({"command": ["set_property", "loop-file", "no"]}, session_id=session_id)
        elif loop_mode in {"one", "all"}:
            self.mpv.request({"command": ["set_property", "loop-file", "inf"]}, session_id=session_id)
            self.mpv.request({"command": ["set_property", "loop-playlist", "no"]}, session_id=session_id)
        else:
            self.mpv.request({"command": ["set_property", "loop-playlist", "no"]}, session_id=session_id)
            self.mpv.request({"command": ["set_property", "loop-file", "no"]}, session_id=session_id)

    def _session_for_path(self, path: str) -> Optional[str]:
        runtime = self._runtime_for_path(path)
        if not runtime:
            return None
        screen = runtime.get("screen")
        return f"S{screen}" if screen is not None else str(runtime.get("session_id", ""))

    def _runtime_for_path(self, path: str) -> Optional[dict]:
        for runtime in self.session_state.values():
            current = runtime.get("path")
            if current and self._files_match(str(current), path) and runtime.get("running"):
                return runtime
        return None

    def _runtime_for_key(self, key: str) -> Optional[dict]:
        for runtime in self.session_state.values():
            if runtime.get("key") == key and runtime.get("running"):
                return runtime
        return None

    def _runtime_text(self, runtime: Optional[dict]) -> str:
        if not runtime:
            return "idle"
        return "pause" if runtime.get("paused") else "play"

    def _runtime_progress(self, runtime: Optional[dict]) -> str:
        theme = self._theme()
        if not runtime:
            return f"[{theme['dim']}][----------] 0:00[/{theme['dim']}]"
        pos = float(runtime.get("pos") or 0)
        duration = float(runtime.get("duration") or 0)
        bar = progress_bar(pos, duration, 12) if duration > 0 else "[----------]"
        return f"[{theme['dim']}]{bar} {format_duration(pos)} / {format_duration(duration)}[/{theme['dim']}]"

    def _update_screen_option_labels(self) -> None:
        for label in self.query(".screen-options-label"):
            key = getattr(label, "screen_options_key", "")
            if not key:
                continue
            if getattr(label, "playlist_global", False):
                label.update(self._playlist_screen_options_text(key))
                continue
            path = getattr(label, "file_path", None)
            source = "playlist" if hasattr(label, "playlist_index") else "library"
            if path:
                label.update(self._screen_options_text(source, key, str(path)))

    def on_list_view_highlighted(self, _event: ListView.Highlighted) -> None:
        self._update_footer()
        self._update_info()

    def on_key(self, event: events.Key) -> None:
        if len(self.screen_stack) > 1:
            return
        key = event.key

        if self.command_mode:
            if key == "escape":
                self._exit_command_mode()
                event.prevent_default()
                event.stop()
            return

        search = self.query_one("#search-input", Input)
        if search.has_focus:
            if key == "escape":
                self._close_search(clear=True)
                event.prevent_default()
                event.stop()
            return

        if self._screens_enabled() and _is_screen_toggle_key(event):
            self._toggle_screen_options_for_focus()
            event.prevent_default()
            event.stop()
            return

        if self._screens_enabled() and self._handle_screen_control_key(key, event):
            return

        if self.loop_pending:
            if key == "l":
                self._cycle_loop_mode()
                event.prevent_default()
                return
            if key in "123456789":
                self._set_loop_count(key)
                event.prevent_default()
                return
            self._cancel_loop_pending()

        if key == "space":
            if self._focused_pane() == "lib":
                self._library_play()
            else:
                self._playlist_play_or_pause()
            event.prevent_default()
            event.stop()
            return
        if key == "tab":
            self._switch_pane()
            event.prevent_default()
            return
        if key == "q":
            self._quit()
            event.prevent_default()
            return
        if key in ("question_mark", "shift+slash"):
            self.push_screen(HelpScreen(self._theme(), __version__, __build__))
            event.prevent_default()
            return
        if key == "slash":
            self._open_search()
            event.prevent_default()
            return
        if key == "escape":
            self._enter_command_mode()
            event.prevent_default()
            return
        if key in ("semicolon", ";"):
            self._open_settings()
            event.prevent_default()
            return
        if key == "l":
            self._handle_loop_key()
            event.prevent_default()
            return
        if key == "y":
            self._start_download_flow()
            event.prevent_default()
            return
        if key == "z":
            self.push_screen(DownloadQueueScreen(lambda: self.downloads.entries, self._cancel_download, self._play_download))
            event.prevent_default()
            return
        if key == "m":
            self._toggle_mute()
            event.prevent_default()
            event.stop()
            return
        if _event_matches(event, VOLUME_UP_KEYS):
            self._adjust_volume(5)
            event.prevent_default()
            event.stop()
            return
        if _event_matches(event, VOLUME_DOWN_KEYS):
            self._adjust_volume(-5)
            event.prevent_default()
            event.stop()
            return

        if self._focused_pane() == "lib":
            self._handle_library_key(key, event)
        else:
            self._handle_playlist_key(key, event)

    def _handle_library_key(self, key: str, event: events.Key) -> None:
        if key == "a":
            self._library_add()
        elif key == "r":
            self._library_rename()
        elif key == "u":
            self._library_undo_rename()
        elif key == "d":
            self._library_delete()
        elif key == "s":
            self._library_set_chunk()
        else:
            return
        event.prevent_default()

    def _handle_playlist_key(self, key: str, event: events.Key) -> None:
        if key == "x":
            self._playlist_remove()
        elif key in ("J", "shift+j"):
            self._playlist_move(1)
        elif key in ("K", "shift+k"):
            self._playlist_move(-1)
        elif key == "c":
            self._playlist_clear()
        elif key == "s":
            self._playlist_set_chunk()
        elif key == "u":
            self._playlist_unset_chunk()
        else:
            return
        event.prevent_default()

    def _library_play(self) -> None:
        path = self._library_path()
        if path:
            if self._screens_enabled():
                index = self._library_index() or 0
                self._play_screen_target("library", self._screen_key("library", index, path), path, index)
                return
            self._play_file(path, self.file_chunks.get(Path(path).name))

    def _library_add(self) -> None:
        path = self._library_path()
        if not path:
            return
        self.playlist.append(path)
        self.playlist_dirty = True
        self._save_state()
        self._refresh_playlist()
        self.notify(f"Added {display_name(path, self.renames)}")

    def _library_rename(self) -> None:
        path = self._library_path()
        if not path:
            return
        basename = Path(path).name
        current = self.renames.get(basename, display_name(path, {}))

        def done(value: str) -> None:
            if value and value != current:
                self.renames[basename] = value
                self._save_state()
                self._refresh_all()

        self.push_screen(TextInputScreen("Rename display name", current), done)

    def _library_undo_rename(self) -> None:
        path = self._library_path()
        if not path:
            return
        basename = Path(path).name
        if basename in self.renames:
            del self.renames[basename]
            self._save_state()
            self._refresh_all()

    def _library_delete(self) -> None:
        path = self._library_path()
        if not path:
            return

        def done(ok: bool) -> None:
            if not ok:
                return
            try:
                Path(path).unlink()
            except OSError as exc:
                self.notify(f"Delete failed: {exc}", severity="error")
                return
            basename = Path(path).name
            self.renames.pop(basename, None)
            self.file_chunks.pop(basename, None)
            self.state.screen_options.pop(f"library:{basename}", None)
            self.state.playlist = [entry for entry in self.playlist if entry != path]
            self._clear_playlist_screen_options()
            self._load_library()
            self._apply_filter()
            self._save_state()
            self._refresh_all()

        self.push_screen(ConfirmScreen("Delete this file permanently?", Path(path).name), done)

    def _library_set_chunk(self) -> None:
        path = self._library_path()
        if not path:
            return
        pos = self.mpv.get_property("time-pos") if self.mpv.is_running() else None
        if not isinstance(pos, (int, float)):
            self.notify("Play a video first, then press s at start/end points", severity="warning")
            return
        basename = Path(path).name
        self._toggle_chunk(self.file_chunks, basename, float(pos))
        self._save_state()
        self._refresh_all()

    def _playlist_play_or_pause(self) -> None:
        if not self.playlist:
            return
        if self._screens_enabled():
            index = self._playlist_index()
            if index is None or index < 0 or index >= len(self.playlist):
                index = 0
            path = self.playlist[index]
            key = self._screen_key("playlist", index, path)
            self._play_or_pause_screen_target("playlist", key, path, index)
            return
        if self.mpv.is_running() and not self.playlist_dirty:
            self.mpv.request({"command": ["cycle", "pause"]})
            return
        index = self._playlist_index()
        if index is None or index < 0 or index >= len(self.playlist):
            index = 0
        self._play_playlist(index)

    def _playlist_remove(self) -> None:
        index = self._playlist_index()
        if index is None or not (0 <= index < len(self.playlist)):
            return
        removed = self.playlist.pop(index)
        self._reindex_playlist_chunks_after_remove(index)
        self._reindex_screen_options_after_remove(index)
        self.playlist_dirty = True
        self._save_state()
        self._refresh_playlist()
        self.notify(f"Removed {display_name(removed, self.renames)}")

    def _playlist_move(self, direction: int) -> None:
        index = self._playlist_index()
        if index is None:
            return
        target = index + direction
        if not (0 <= target < len(self.playlist)):
            return
        self.playlist[index], self.playlist[target] = self.playlist[target], self.playlist[index]
        left = self.playlist_chunks.pop(str(index), None)
        right = self.playlist_chunks.pop(str(target), None)
        if left:
            self.playlist_chunks[str(target)] = left
        if right:
            self.playlist_chunks[str(index)] = right
        self._swap_screen_options(index, target)
        self.playlist_dirty = True
        self._save_state()
        self._refresh_playlist()
        self.query_one("#pl-list", ListView).index = target

    def _playlist_clear(self) -> None:
        if not self.playlist:
            return

        def done(ok: bool) -> None:
            if ok:
                self.playlist.clear()
                self.playlist_chunks.clear()
                self._clear_playlist_screen_options()
                self.playlist_dirty = True
                self._save_state()
                self._refresh_playlist()

        self.push_screen(ConfirmScreen("Clear the entire playlist?"), done)

    def _playlist_set_chunk(self) -> None:
        index = self._playlist_index()
        if index is None or not (0 <= index < len(self.playlist)):
            return
        pos = self.mpv.get_property("time-pos") if self.mpv.is_running() else None
        if not isinstance(pos, (int, float)):
            self.notify("Play a video first, then press s at start/end points", severity="warning")
            return
        self._toggle_chunk(self.playlist_chunks, str(index), float(pos))
        self._save_state()
        self._refresh_all()

    def _playlist_unset_chunk(self) -> None:
        index = self._playlist_index()
        if index is None:
            return
        if str(index) in self.playlist_chunks:
            del self.playlist_chunks[str(index)]
            self._save_state()
            self._refresh_all()

    def _toggle_chunk(self, target: Dict[str, Chunk], key: str, pos: float) -> None:
        chunk = target.get(key)
        if not chunk or len(chunk) != 2 or chunk[0] != chunk[1]:
            target[key] = [pos, pos]
            self.notify(f"Chunk start {format_duration(pos)}")
            return
        start = chunk[0]
        target[key] = [min(start, pos), max(start, pos)]
        self.notify(f"Chunk {format_duration(target[key][0])} - {format_duration(target[key][1])}")

    def _reindex_playlist_chunks_after_remove(self, removed_index: int) -> None:
        updated: Dict[str, Chunk] = {}
        for key, chunk in self.playlist_chunks.items():
            index = int(key)
            if index < removed_index:
                updated[key] = chunk
            elif index > removed_index:
                updated[str(index - 1)] = chunk
        self.state.playlist_chunks = updated

    def _reindex_screen_options_after_remove(self, removed_index: int) -> None:
        updated: Dict[str, dict] = {}
        for key, value in self.state.screen_options.items():
            if not key.startswith("playlist:") or key == "playlist:global":
                updated[key] = value
                continue
            try:
                index = int(key.split(":", 1)[1])
            except ValueError:
                updated[key] = value
                continue
            if index < removed_index:
                updated[key] = value
            elif index > removed_index:
                updated[f"playlist:{index - 1}"] = value
        self.state.screen_options = updated

    def _swap_screen_options(self, left_index: int, right_index: int) -> None:
        left_key = f"playlist:{left_index}"
        right_key = f"playlist:{right_index}"
        left = self.state.screen_options.pop(left_key, None)
        right = self.state.screen_options.pop(right_key, None)
        if left is not None:
            self.state.screen_options[right_key] = left
        if right is not None:
            self.state.screen_options[left_key] = right

    def _clear_playlist_screen_options(self) -> None:
        self.state.screen_options = {
            key: value
            for key, value in self.state.screen_options.items()
            if not key.startswith("playlist:") or key == "playlist:global"
        }

    def _handle_loop_key(self) -> None:
        self.loop_pending = True
        self.notify("Loop: press l to cycle or 1-9 for count")
        if self.loop_timer:
            self.loop_timer.stop()
        self.loop_timer = self.set_timer(3.0, self._cancel_loop_pending)

    def _cycle_loop_mode(self) -> None:
        self._cancel_loop_pending()
        self.loop_mode = {"off": "all", "all": "one"}.get(self.loop_mode, "off")
        self._apply_loop_to_mpv()
        self._update_status()
        self.notify(f"Loop {self.loop_mode}")

    def _set_loop_count(self, key: str) -> None:
        self._cancel_loop_pending()
        self.loop_mode = key
        self._apply_loop_to_mpv()
        self._update_status()
        self.notify(f"Loop x{int(key) + 1}")

    def _cancel_loop_pending(self) -> None:
        self.loop_pending = False
        if self.loop_timer:
            self.loop_timer.stop()
            self.loop_timer = None

    def _apply_loop_to_mpv(self) -> None:
        sessions = self.mpv.active_session_ids()
        if not sessions:
            return
        for session_id in sessions:
            self._apply_global_loop_to_session(session_id)

    def _apply_global_loop_to_session(self, session_id: str) -> None:
        if self.loop_mode == "all":
            self.mpv.request({"command": ["set_property", "loop-playlist", "inf"]}, session_id=session_id)
            self.mpv.request({"command": ["set_property", "loop-file", "no"]}, session_id=session_id)
        elif self.loop_mode == "one":
            self.mpv.request({"command": ["set_property", "loop-file", "inf"]}, session_id=session_id)
            self.mpv.request({"command": ["set_property", "loop-playlist", "no"]}, session_id=session_id)
        elif self.loop_mode.isdigit():
            self.mpv.request({"command": ["set_property", "loop-playlist", int(self.loop_mode) + 1]}, session_id=session_id)
            self.mpv.request({"command": ["set_property", "loop-file", "no"]}, session_id=session_id)
        else:
            self.mpv.request({"command": ["set_property", "loop-playlist", "no"]}, session_id=session_id)
            self.mpv.request({"command": ["set_property", "loop-file", "no"]}, session_id=session_id)

    def _adjust_volume(self, delta: int) -> None:
        self.state.settings.volume = max(0, min(200, self.state.settings.volume + delta))
        for session_id in self.mpv.active_session_ids() or (["main"] if self.mpv.is_running() else []):
            self.mpv.request({"command": ["set_property", "volume", self.state.settings.volume]}, session_id=session_id)
        self._save_state()
        self._update_footer()

    def _toggle_mute(self) -> None:
        self.state.settings.muted = not self.state.settings.muted
        for session_id in self.mpv.active_session_ids() or (["main"] if self.mpv.is_running() else []):
            self.mpv.request({"command": ["set_property", "mute", "yes" if self.state.settings.muted else "no"]}, session_id=session_id)
        self._save_state()
        self._update_footer()

    def _open_search(self) -> None:
        search = self.query_one("#search-input", Input)
        search.value = self.filter_text
        search.styles.display = "block"
        search.focus()

    def _close_search(self, clear: bool = False) -> None:
        search = self.query_one("#search-input", Input)
        search.styles.display = "none"
        if clear:
            self.filter_text = ""
            search.value = ""
            self._apply_filter()
        self.query_one("#lib-list", ListView).focus()
        self._update_status()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self.filter_text = event.value
            self._apply_filter()
            self._update_status()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self._close_search()
        elif event.input.id == "cmd-input":
            self._execute_command(event.value)

    def _enter_command_mode(self) -> None:
        self.command_mode = True
        command = self.query_one("#cmd-input", Input)
        command.value = ""
        command.styles.display = "block"
        self.query_one("#footer-bar", Static).styles.display = "none"
        self.call_after_refresh(command.focus)

    def _exit_command_mode(self) -> None:
        self.command_mode = False
        command = self.query_one("#cmd-input", Input)
        command.value = ""
        command.styles.display = "none"
        self.query_one("#footer-bar", Static).styles.display = "block"
        self.query_one("#lib-list", ListView).focus()
        self._update_footer()

    def _execute_command(self, raw: str) -> None:
        parsed = parse_command(raw)
        try:
            if parsed.verb == "empty":
                return
            if parsed.verb == "q":
                self._quit()
                return
            if parsed.verb == "w":
                self._save_state()
                self.notify("Saved")
            elif parsed.verb == "shell":
                self._open_shell()
            elif parsed.verb == "help":
                self.notify("Commands: set, unset, status, w, q, shell")
            elif parsed.verb == "status":
                self._command_status(parsed.key)
            elif parsed.verb == "unset":
                self._command_unset(parsed.key)
            elif parsed.verb == "set":
                self._command_set(parsed.key, parsed.value)
            elif parsed.verb == "bad":
                self.notify(parsed.value, severity="warning")
            else:
                self.notify(f"Unknown command: {parsed.value}", severity="warning")
        except Exception as exc:
            self.notify(f"Command error: {exc}", severity="error")
        finally:
            if parsed.verb != "q":
                self._exit_command_mode()

    def _command_set(self, key: str, value: str) -> None:
        if key == "volume":
            self.state.settings.volume = max(0, min(200, int(value)))
            for session_id in self.mpv.active_session_ids() or (["main"] if self.mpv.is_running() else []):
                self.mpv.request({"command": ["set_property", "volume", self.state.settings.volume]}, session_id=session_id)
            self._save_state()
            self._update_footer()
        elif key == "mute":
            self.state.settings.muted = value.lower() in {"1", "true", "yes", "on"}
            for session_id in self.mpv.active_session_ids() or (["main"] if self.mpv.is_running() else []):
                self.mpv.request({"command": ["set_property", "mute", "yes" if self.state.settings.muted else "no"]}, session_id=session_id)
            self._save_state()
            self._update_footer()
        elif key == "screen":
            self.state.settings.screen = value
            self._save_state()
        elif key == "folder":
            path = expand_path(value)
            if not path.is_dir():
                self.notify(f"Not a directory: {value}", severity="error")
                return
            self.video_dir = path
            self._load_library()
            self.filtered_files = list(self.all_files)
            self._save_state()
            self._refresh_all()
        elif key in ("vp", "yt-dlp", "ffmpeg"):
            self.state.settings.custom_args[key] = value
            self._save_state()
        else:
            self.notify(f"Unknown setting: {key}", severity="warning")

    def _command_unset(self, key: str) -> None:
        if key == "all":
            self.state.settings.custom_args.clear()
        else:
            self.state.settings.custom_args.pop(key, None)
        self._save_state()

    def _command_status(self, key: str) -> None:
        values = {
            "volume": f"volume: {self.state.settings.volume}%",
            "mute": f"mute: {'on' if self.state.settings.muted else 'off'}",
            "screen": f"screen: {self.state.settings.screen}",
            "folder": f"folder: {self.video_dir}",
            "loop": f"loop: {self.loop_mode}",
            "playlist": f"playlist: {len(self.playlist)} entries",
            "library": f"library: {len(self.all_files)} files",
            "vp": f"vp: {self.state.settings.custom_args.get('vp', '(none)')}",
            "yt-dlp": f"yt-dlp: {self.state.settings.custom_args.get('yt-dlp', '(none)')}",
            "ffmpeg": f"ffmpeg: {self.state.settings.custom_args.get('ffmpeg', '(none)')}",
        }
        if key == "all":
            self.notify("\n".join(values.values()))
        else:
            self.notify(values.get(key, f"{key}: unknown"))

    def _open_shell(self) -> None:
        command = f'cd "{self.video_dir}" && clear'
        try:
            import subprocess

            subprocess.Popen(
                [
                    "/usr/bin/osascript",
                    "-e",
                    f'tell application "iTerm2" to tell current session of current window to write text "{command}"',
                ]
            )
        except OSError as exc:
            self.notify(f"Shell error: {exc}", severity="error")

    def _open_settings(self) -> None:
        def done(action: str) -> None:
            if not action:
                return
            if action == "module_settings:theme":
                self.push_screen(ThemePickerScreen(self._theme_name), self._apply_theme)
            elif action == "module_settings:screens":
                self.push_screen(ScreenPickerScreen(self.state.settings.screen, self._screen_choices()), self._apply_default_screen)
            elif action == "folder":
                self._open_folder_picker(self.video_dir)
            elif action == "folder_mode":
                self._toggle_video_folder_mode()
            elif action == "module_editor":
                self.push_screen(ModuleEditorScreen(self.registry, self.module_layout), self._apply_module_layout)
            elif action == "user_memory":
                self._open_user_memory()
            elif action == "about":
                self._open_about()

        self.push_screen(SettingsScreen(self._settings_actions()), done)

    def _settings_actions(self) -> list[SettingsAction]:
        actions: list[SettingsAction] = []
        for spec in sorted(self.registry.specs.values(), key=lambda item: item.title.lower()):
            if spec.has_settings and self.module_layout.enabled.get(spec.id, False):
                label = "Themes" if spec.id == "theme" else spec.title
                description = ". ".join(spec.capabilities) if spec.capabilities else f"Configure {label.lower()}."
                actions.append(SettingsAction(label, f"module_settings:{spec.id}", description))
        actions.extend(
            [
                SettingsAction("Video folder", "folder", "Choose where vplay scans for local media."),
                SettingsAction("Folder mode", "folder_mode", self._folder_mode_description()),
                SettingsAction("Add ons modules", "module_editor", "Activate, deactivate, move, split, or reset modules."),
                SettingsAction("User memory", "user_memory", "Edit or reset saved display names and chunks."),
                SettingsAction("About", "about", "Developer, version, and git update check."),
            ]
        )
        return actions

    def _folder_mode_description(self) -> str:
        if self.state.settings.video_dir_mode == "cwd":
            return "Currently using the terminal working folder each time vplay starts."
        return "Currently using the saved video folder. Toggle to use the terminal working folder instead."

    def _toggle_video_folder_mode(self) -> None:
        if self.state.settings.video_dir_mode == "cwd":
            self.state.settings.video_dir_mode = "fixed"
        else:
            self.state.settings.video_dir_mode = "cwd"
        self.video_dir = self._resolve_video_dir()
        self._save_state()
        self._load_library()
        self.filtered_files = list(self.all_files)
        self._refresh_all()
        if not self.video_dir.exists():
            self._open_missing_video_dir()

    def _open_missing_video_dir(self) -> None:
        if self._folder_prompt_open or self.video_dir.exists():
            return
        self._folder_prompt_open = True

        def done(action: str) -> None:
            self._folder_prompt_open = False
            if action == "create_default":
                self._create_and_use_folder(self.video_dir)
            elif action == "browse":
                self._open_folder_picker(self.video_dir.parent)
            elif action == "use_cwd":
                self.state.settings.video_dir_mode = "cwd"
                self.video_dir = Path.cwd().resolve()
                self._save_state()
                self._refresh_after_folder_change()

        self.push_screen(FolderSetupScreen(str(self.video_dir)), done)

    def _open_folder_picker(self, start: Path) -> None:
        def done(result: str) -> None:
            if result.startswith("use:"):
                self._apply_folder(result[4:])
            elif result.startswith("new:"):
                self._ask_new_folder(Path(result[4:]))

        self.push_screen(DirectoryPickerScreen(str(start)), done)

    def _ask_new_folder(self, parent: Path) -> None:
        def done(name: str) -> None:
            if not name:
                self._open_folder_picker(parent)
                return
            target = expand_path(name) if name.startswith(("~", "/")) else parent / name
            self._create_and_use_folder(target)

        self.push_screen(TextInputScreen("New folder", "", placeholder="Videos"), done)

    def _create_and_use_folder(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.notify(f"Could not create folder: {exc}", severity="error")
            self._open_folder_picker(path.parent)
            return
        self._apply_folder(str(path))

    def _refresh_after_folder_change(self) -> None:
        self._load_library()
        self.filtered_files = list(self.all_files)
        self.metadata.prefetch(self.filtered_files)
        self._refresh_all()

    def _open_user_memory(self) -> None:
        def done(action: str) -> None:
            if not action:
                return
            if action == "reset_all:renames":
                self.renames.clear()
                self._save_state()
                self._refresh_all()
                self._open_user_memory()
            elif action == "reset_all:file_chunks":
                self.file_chunks.clear()
                self._save_state()
                self._refresh_all()
                self._open_user_memory()
            elif action == "reset_all:playlist_chunks":
                self.playlist_chunks.clear()
                self._save_state()
                self._refresh_all()
                self._open_user_memory()
            elif action.startswith("edit_rename:"):
                self._memory_edit_rename(action.split(":", 1)[1])
            elif action.startswith("edit_chunk:"):
                self._memory_edit_chunk(action.split(":", 1)[1])
            elif action.startswith("reset_rename:"):
                self.renames.pop(action.split(":", 1)[1], None)
                self._save_state()
                self._refresh_all()
                self._open_user_memory()
            elif action.startswith("reset_chunk:"):
                self.file_chunks.pop(action.split(":", 1)[1], None)
                self._save_state()
                self._refresh_all()
                self._open_user_memory()
            elif action.startswith("reset_playlist_chunk:"):
                self.playlist_chunks.pop(action.split(":", 1)[1], None)
                self._save_state()
                self._refresh_all()
                self._open_user_memory()

        self.push_screen(UserMemoryScreen(self._memory_rows()), done)

    def _memory_rows(self) -> list[MemoryAction]:
        rows = [
            MemoryAction(
                f"Reset all display names ({len(self.renames)})",
                "reset_all:renames",
                "Clear every custom display name.",
            ),
            MemoryAction(
                f"Reset all file chunks ({len(self.file_chunks)})",
                "reset_all:file_chunks",
                "Clear saved chunks attached to files.",
            ),
            MemoryAction(
                f"Reset all playlist chunks ({len(self.playlist_chunks)})",
                "reset_all:playlist_chunks",
                "Clear chunks attached to playlist positions.",
            ),
        ]
        for basename, name in sorted(self.renames.items()):
            rows.append(
                MemoryAction(
                    f"Name  {basename} -> {name}",
                    f"edit_rename:{basename}",
                    "Enter edits this custom display name. x resets it.",
                    f"reset_rename:{basename}",
                )
            )
        for basename, chunk in sorted(self.file_chunks.items()):
            rows.append(
                MemoryAction(
                    f"Chunk {basename}  {format_duration(chunk[0])} - {format_duration(chunk[1])}",
                    f"edit_chunk:{basename}",
                    "Enter edits this file chunk as start-end, for example 1:20-2:10. x resets it.",
                    f"reset_chunk:{basename}",
                )
            )
        for index, chunk in sorted(self.playlist_chunks.items(), key=lambda item: int(item[0]) if item[0].isdigit() else 0):
            label = f"Playlist chunk #{int(index) + 1 if index.isdigit() else index}  {format_duration(chunk[0])} - {format_duration(chunk[1])}"
            rows.append(MemoryAction(label, "", "Playlist chunks are position-based. x resets this one.", f"reset_playlist_chunk:{index}"))
        return rows

    def _memory_edit_rename(self, basename: str) -> None:
        current = self.renames.get(basename, "")

        def done(value: str) -> None:
            if value:
                self.renames[basename] = value
            else:
                self.renames.pop(basename, None)
            self._save_state()
            self._refresh_all()
            self._open_user_memory()

        self.push_screen(TextInputScreen("Display name", current), done)

    def _memory_edit_chunk(self, basename: str) -> None:
        chunk = self.file_chunks.get(basename, [0.0, 0.0])
        current = f"{format_duration(chunk[0])}-{format_duration(chunk[1])}"

        def done(value: str) -> None:
            if not value:
                self._open_user_memory()
                return
            parsed = _parse_chunk_range(value)
            if not parsed:
                self.notify("Use start-end, for example 1:20-2:10", severity="warning")
                self._open_user_memory()
                return
            self.file_chunks[basename] = parsed
            self._save_state()
            self._refresh_all()
            self._open_user_memory()

        self.push_screen(TextInputScreen("File chunk", current, hint="Use start-end, e.g. 1:20-2:10 - Esc cancel"), done)

    def _open_about(self) -> None:
        def done(action: str) -> None:
            if action == "check_updates":
                self._open_updates()

        self.push_screen(AboutScreen(__version__, __build__, __release__, self.config.install_method), done)

    def _open_updates(self) -> None:
        status = self.updates.check()

        def done(action: str) -> None:
            if action == "check_updates":
                self._open_updates()
            elif action == "install_update":
                installed = self.updates.install()
                self.push_screen(UpdateScreen(installed.title, installed.detail, installed.can_install))

        self.push_screen(UpdateScreen(status.title, status.detail, status.can_install), done)

    def _apply_theme(self, theme_name: str) -> None:
        if theme_name and theme_name in THEMES:
            self._theme_name = theme_name
            self.store.save_theme(theme_name)
            self.refresh_css(animate=False)
            self._refresh_all()

    def _screen_choices(self) -> list[tuple[str, str]]:
        choices = [("auto-external", "Auto external display")]
        choices.extend((str(item.index), item.label) for item in self.mpv.displays.snapshot(max_age=0.0))
        return choices

    def _apply_default_screen(self, screen: str) -> None:
        if not screen:
            return
        self.state.settings.screen = screen
        self._save_state()
        self._refresh_all()

    def _apply_module_layout(self, layout: ModuleLayout | None) -> None:
        if layout is None:
            return
        self.module_layout = layout
        self.module_hooks = self.registry.active_hooks(self.module_layout)
        self._save_state()
        self.refresh(recompose=True)
        self.call_after_refresh(self._after_layout_recompose)

    def _after_layout_recompose(self) -> None:
        self._refresh_all()
        try:
            self.query_one("#lib-list", ListView).focus()
        except Exception:
            try:
                self.query_one("#pl-list", ListView).focus()
            except Exception:
                pass

    def _apply_folder(self, value: str) -> None:
        if not value:
            return
        path = expand_path(value)
        if not path.is_dir():
            self.notify(f"Not a directory: {value}", severity="error")
            return
        self.state.settings.video_dir_mode = "fixed"
        self.video_dir = path
        self._save_state()
        self._refresh_after_folder_change()

    def _start_download_flow(self) -> None:
        def got_url(url: str) -> None:
            if not url:
                return
            self.notify("Resolving title...")
            thread = threading.Thread(target=self._resolve_download_title, args=(url,), daemon=True)
            thread.start()

        self.push_screen(TextInputScreen("Download URL", placeholder="https://..."), got_url)

    def _resolve_download_title(self, url: str) -> None:
        title, error = resolve_title(url, self.state.settings.custom_args.get("yt-dlp", ""))
        proposed = title or _filename_from_url(url)

        def ask_name() -> None:
            if error:
                self.notify(error, severity="warning")

            def got_name(name: str) -> None:
                self.downloads.start(url, name or proposed, self.state.settings.custom_args.get("yt-dlp", ""))
                self._update_footer()

            self.push_screen(TextInputScreen("Download filename", proposed), got_name)

        self.call_from_thread(ask_name)

    def _download_update(self, _entry: DownloadEntry) -> None:
        self.call_from_thread(self._update_footer)

    def _download_done(self, entry: DownloadEntry, ok: bool) -> None:
        def done() -> None:
            if ok:
                self._load_library()
                self.filtered_files = list(self.all_files)
                self._refresh_all()
                self.notify(f"Download complete: {entry.filename}")
            elif not entry.cancelled:
                self.notify(f"Download failed: {entry.filename}", severity="error")

        self.call_from_thread(done)

    def _cancel_download(self, entry_id: int) -> None:
        self.downloads.cancel(entry_id)
        self._update_footer()

    def _play_download(self, entry_id: int) -> None:
        entry = next((item for item in self.downloads.entries if item.id == entry_id), None)
        if not entry:
            return
        if entry.percent < 60 and not entry.done:
            self.notify("Wait until at least 60% is downloaded", severity="warning")
            return
        stem = entry.output_template.replace(".%(ext)s", "")
        for path in self.video_dir.iterdir() if self.video_dir.exists() else []:
            if path.is_file() and (path.stem == Path(stem).name or entry.filename.lower() in path.name.lower()):
                self._play_file(str(path), None)
                return
        self.notify("Could not find downloaded file", severity="warning")

    def _play_file(self, path: str, chunk: Optional[Chunk]) -> None:
        screen = self.mpv.detect_screen(self.state.settings.screen)
        ok = self.mpv.play_file(
            path,
            paths=self.all_files,
            renames=self.renames,
            chunks=self.file_chunks,
            volume=self.state.settings.volume,
            muted=self.state.settings.muted,
            screen=screen,
            loop_mode=self.loop_mode,
            chunk=chunk,
            extra_args=self.state.settings.custom_args.get("vp", ""),
        )
        if ok:
            self.current_file = path
            self.session_state["main"] = {
                "session_id": "main",
                "key": "main",
                "source": "library",
                "path": path,
                "screen": screen,
                "volume": self.state.settings.volume,
                "muted": self.state.settings.muted,
                "pos": 0.0,
                "duration": 0.0,
                "paused": False,
                "running": True,
            }
            self.playlist_dirty = False
            self._refresh_all()
            self.notify(f"Playing {display_name(path, self.renames)}")
        else:
            self.notify("Could not start mpv", severity="error")

    def _play_playlist(self, start: int) -> None:
        screen = self.mpv.detect_screen(self.state.settings.screen)
        ok = self.mpv.play_playlist(
            self.playlist,
            start,
            paths=self.all_files,
            renames=self.renames,
            chunks=self.file_chunks,
            volume=self.state.settings.volume,
            muted=self.state.settings.muted,
            screen=screen,
            loop_mode=self.loop_mode,
            chunk_for_index=self._chunk_for_playlist_index,
            extra_args=self.state.settings.custom_args.get("vp", ""),
        )
        if ok:
            self.current_file = self.playlist[start]
            self.session_state["main"] = {
                "session_id": "main",
                "key": "main",
                "source": "playlist",
                "path": self.playlist[start],
                "screen": screen,
                "volume": self.state.settings.volume,
                "muted": self.state.settings.muted,
                "pos": 0.0,
                "duration": 0.0,
                "paused": False,
                "running": True,
            }
            self.playlist_dirty = False
            self._refresh_all()
        else:
            self.notify("Could not start playlist", severity="error")

    def _sync_progress(self) -> None:
        sessions = self.mpv.active_session_ids()
        if sessions:
            changed = False
            for session_id in sessions:
                props = self.mpv.get_properties(["time-pos", "duration", "pause", "path", "volume", "mute"], session_id=session_id)
                runtime = self.session_state.setdefault(
                    session_id,
                    {"session_id": session_id, "key": session_id, "path": None, "running": True},
                )
                runtime["running"] = True
                if props.get("path") and props.get("path") != "null":
                    path = str(props["path"])
                    changed = changed or runtime.get("path") != path
                    runtime["path"] = path
                    if session_id == "main":
                        self.current_file = path
                if isinstance(props.get("time-pos"), (int, float)):
                    new_pos = float(props["time-pos"])
                    changed = changed or abs(new_pos - float(runtime.get("pos") or 0)) >= 0.25
                    runtime["pos"] = new_pos
                    if session_id == "main":
                        self.last_pos = new_pos
                if isinstance(props.get("duration"), (int, float)):
                    new_duration = float(props["duration"])
                    changed = changed or new_duration != runtime.get("duration")
                    runtime["duration"] = new_duration
                    if session_id == "main":
                        self.last_duration = new_duration
                if isinstance(props.get("pause"), bool):
                    new_paused = bool(props["pause"])
                    changed = changed or new_paused != runtime.get("paused")
                    runtime["paused"] = new_paused
                    if session_id == "main":
                        self.last_paused = new_paused
                if isinstance(props.get("volume"), (int, float)):
                    runtime["volume"] = int(props["volume"])
                if isinstance(props.get("mute"), bool):
                    runtime["muted"] = bool(props["mute"])
            event_changed = self._handle_mpv_event()
            if changed and not event_changed:
                self._update_screen_option_labels()
                self._update_info()
                self._update_status()
        if self.downloads.active():
            self._update_footer()

    def _sync_full(self) -> None:
        old = set(self.all_files)
        self._load_library()
        if set(self.all_files) != old:
            self.state.playlist = [path for path in self.playlist if Path(path).exists()]
            self._apply_filter()
            self._save_state()
            self._refresh_all()
            return

        old_current = self.current_file
        active_sessions = set(self.mpv.active_session_ids())
        session_activity_changed = False
        for session_id in list(self.session_state):
            if session_id not in active_sessions and self.session_state[session_id].get("running"):
                key = self.session_state[session_id].get("key")
                if isinstance(key, str):
                    self.screen_expanded.discard(key)
                self.session_state[session_id]["running"] = False
                session_activity_changed = True
        if "main" in active_sessions:
            path = self.mpv.get_property("path")
            self.current_file = str(path) if path and path != "null" else None
        elif not active_sessions:
            self.current_file = None
        event_changed = self._handle_mpv_event()
        if (self.current_file != old_current or session_activity_changed) and not event_changed:
            self._refresh_library()
            self._refresh_playlist()
            self._update_status()
            self._update_info()

    def _handle_mpv_event(self) -> bool:
        events = self.mpv.read_events()
        if not events:
            return False
        changed = False
        for event in events:
            changed = self._handle_one_mpv_event(event) or changed
        return changed

    def _handle_one_mpv_event(self, event: dict) -> bool:
        session_id = str(event.get("session_id", "main"))
        if event.get("event") == "chunk_set":
            filename = event.get("file")
            start = event.get("start")
            end = event.get("end")
            if filename and isinstance(start, (int, float)) and isinstance(end, (int, float)):
                self.file_chunks[str(filename)] = [min(float(start), float(end)), max(float(start), float(end))]
                self._save_state()
                self._refresh_all()
                return True
        elif event.get("event") == "volume":
            volume = event.get("volume")
            if isinstance(volume, (int, float)):
                runtime = self.session_state.get(session_id)
                if self._screens_enabled() and runtime and runtime.get("key") not in {None, "main"}:
                    key = str(runtime["key"])
                    opts = self._screen_options(key, str(runtime.get("source", "library")))
                    opts.volume = max(0, min(200, int(volume)))
                    self.state.screen_options[key] = opts.to_dict()
                else:
                    self.state.settings.volume = max(0, min(200, int(volume)))
                self._save_state()
                self._update_footer()
                self._update_screen_option_labels()
                return True
        elif event.get("event") == "mute":
            muted = event.get("muted")
            if isinstance(muted, bool):
                runtime = self.session_state.get(session_id)
                if self._screens_enabled() and runtime and runtime.get("key") not in {None, "main"}:
                    key = str(runtime["key"])
                    opts = self._screen_options(key, str(runtime.get("source", "library")))
                    opts.muted = muted
                    self.state.screen_options[key] = opts.to_dict()
                else:
                    self.state.settings.muted = muted
                self._save_state()
                self._update_footer()
                self._update_screen_option_labels()
                return True
        return False

    def _save_state(self) -> None:
        if self.state.settings.video_dir_mode == "fixed":
            self.state.settings.video_dir = self._home_relative(self.video_dir)
        self.state.settings.module_layout = self.module_layout.to_dict()
        self.store.save(self.state)

    def _quit(self) -> None:
        self._save_state()
        self.mpv.quit_all()
        self.exit()

    @staticmethod
    def _files_match(left: str, right: str) -> bool:
        if left == right or Path(left).name == Path(right).name:
            return True
        try:
            return Path(left).resolve() == Path(right).resolve()
        except OSError:
            return False

    @staticmethod
    def _home_relative(path: Path) -> str:
        text = str(path)
        home = str(Path.home())
        return text.replace(home, "~", 1) if text.startswith(home) else text


def _item_attr(view: ListView, attr: str) -> object:
    item = view.highlighted_child
    if item and hasattr(item, attr):
        return getattr(item, attr)
    if item:
        for child in item.children:
            if hasattr(child, attr):
                return getattr(child, attr)
    return None


def _footer_key_action(part: str, theme: dict) -> str:
    key, _, action = part.partition(" ")
    return f"{_footer_key(key)}[{theme['fg']}] {action}[/{theme['fg']}]" if action else _footer_key(key)


def _footer_key(key: str) -> str:
    return f"[bold {FOOTER_KEY_COLOR}]{key}[/bold {FOOTER_KEY_COLOR}]"


def _volume_slider(volume: int, width: int = 16) -> str:
    clamped = max(0, min(200, int(volume)))
    filled = int(round((clamped / 200.0) * width))
    return "[" + ("=" * filled) + ("-" * (width - filled)) + "]"


def _event_matches(event: events.Key, names: set[str]) -> bool:
    key = (event.key or "").lower()
    character = (getattr(event, "character", "") or "").lower()
    aliases = getattr(event, "aliases", ()) or ()
    if key in names or character in names:
        return True
    return any(str(alias).lower() in names for alias in aliases)


def _is_screen_toggle_key(event: events.Key) -> bool:
    key = (event.key or "").lower()
    character = (getattr(event, "character", "") or "").lower()
    aliases = {str(alias).lower() for alias in (getattr(event, "aliases", ()) or ())}
    return key in {"shift+space", "v"} or character == "v" or "shift+space" in aliases


def _parse_chunk_range(value: str) -> Optional[Chunk]:
    if "-" not in value:
        return None
    left, right = value.split("-", 1)
    start = parse_timestamp(left.strip())
    end = parse_timestamp(right.strip())
    if start is None or end is None or start == end:
        return None
    return [min(start, end), max(start, end)]


def _filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).stem if path else ""
    return name.replace("-", " ").replace("_", " ").strip() or "download"


def main() -> None:
    VideoPlayerApp().run()
