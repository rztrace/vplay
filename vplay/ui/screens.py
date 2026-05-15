from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from ..config import THEMES
from ..media import progress_bar
from ..models import DownloadEntry
from ..modules.base import MAX_VISIBLE_MODULES, SLOT_ORDER, ModuleConflict, ModuleSlot
from ..modules.layout import ModuleLayout
from ..modules.registry import ModuleRegistry


@dataclass(frozen=True)
class SettingsAction:
    label: str
    action: str
    description: str = ""


@dataclass(frozen=True)
class MemoryAction:
    label: str
    action: str
    description: str = ""
    reset_action: str = ""


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    #confirm-box { width: 60; max-width: 90%; height: auto; padding: 1 2; background: $surface; border: heavy $accent; }
    #confirm-title { width: 100%; content-align: center middle; text-style: bold; color: $accent; }
    #confirm-detail { width: 100%; content-align: center middle; margin: 1 0; color: $text; }
    #confirm-hint { width: 100%; content-align: center middle; color: $text-muted; }
    """
    BINDINGS = [Binding("y,enter", "confirm"), Binding("n,escape,q", "cancel")]

    def __init__(self, title: str, detail: str = ""):
        super().__init__()
        self._title = title
        self._detail = detail

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self._title, id="confirm-title"),
            Static(self._detail, id="confirm-detail"),
            Static("Enter/y confirm - Esc cancel", id="confirm-hint"),
            id="confirm-box",
        )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class TextInputScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    TextInputScreen { align: center middle; }
    #input-box { width: 72; max-width: 95%; height: auto; padding: 1 2; background: $surface; border: solid $primary; }
    #input-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #input-field { width: 100%; }
    #input-hint { width: 100%; color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [Binding("escape", "cancel")]

    def __init__(self, title: str, value: str = "", placeholder: str = "", hint: str = "Enter save - Esc cancel"):
        super().__init__()
        self._title = title
        self._value = value
        self._placeholder = placeholder
        self._hint = hint

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self._title, id="input-title"),
            Input(value=self._value, placeholder=self._placeholder, id="input-field"),
            Static(self._hint, id="input-hint"),
            id="input-box",
        )

    def on_mount(self) -> None:
        self.query_one("#input-field", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    #help-scroll { width: 76; max-width: 95%; height: 90%; padding: 1 2; overflow-y: auto; background: $surface; border: solid $primary; }
    """
    BINDINGS = [Binding("escape,q,question_mark,enter", "close")]

    def __init__(self, theme: dict, version: str = "", build: str = ""):
        super().__init__()
        self._theme = theme
        self._version = version
        self._build = build

    def compose(self) -> ComposeResult:
        t = self._theme
        k, f, d = t["accent"], t["fg"], t["dim"]
        build = f" build {self._build}" if self._build else ""
        version = f" [{d}]{self._version}{build}[/{d}]" if self._version else ""
        text = f"""\
[bold {k}]vplay[/bold {k}]{version}

[bold {f}]Library[/bold {f}]
  [{k}]Space[/{k}] play file    [{k}]a[/{k}] add to playlist    [{k}]r[/{k}] rename display name
  [{k}]u[/{k}] undo rename  [{k}]d[/{k}] delete file        [{k}]s[/{k}] set chunk from mpv position

[bold {f}]Playlist[/bold {f}]
  [{k}]Space[/{k}] play/pause   [{k}]x[/{k}] remove            [{k}]J/K[/{k}] move entry
  [{k}]c[/{k}] clear        [{k}]s[/{k}] set entry chunk    [{k}]u[/{k}] remove entry chunk

[bold {f}]Global[/bold {f}]
  [{k}]Tab[/{k}] switch panes   [{k}]/[/{k}] search           [{k}]Esc[/{k}] command mode
  [{k}]l[/{k}] loop mode      [{k}]=/-[/{k}] volume        [{k}]m[/{k}] mute
  [{k}]z[/{k}] downloads      [{k}];[/{k}] settings       [{k}]q[/{k}] quit

[bold {f}]Screens Module[/bold {f}]
  [{k}]Shift+Space[/{k}] unfold per-track screen controls  [{k}]v[/{k}] fallback toggle
  [{k}]p[/{k}] play/pause selected screen session          [{k}]x/Esc[/{k}] stop selected session
  [{k}]S[/{k}] cycle screen    [{k}]n[/{k}] play next      [{k}]l[/{k}] loop selected session
  [{k}]=/-[/{k}] session volume [{k}]m[/{k}] session mute  [{k}]left/right[/{k}] seek selected session

[bold {f}]Add ons modules[/bold {f}]
  Settings -> Add ons modules
  [{k}]Space[/{k}] toggle non-core modules · [{k}]h/l[/{k}] move slot · [{k}]J/K[/{k}] reorder
  [{k}]s[/{k}] split orientation · [{k}]u[/{k}] unsplit · [{k}]r[/{k}] reset · [{k}]Enter[/{k}] save

[bold {f}]Commands[/bold {f}]
  :set volume=75
  :set mute=true
  :set folder=~/movs
  :set screen=0
  :set vp=--profile=gpu-hq
  :set yt-dlp=--cookies-from-browser chrome
  :status all

[{d}]Enter or Esc closes this help.[/{d}]"""
        yield VerticalScroll(Static(text, id="help-text"), id="help-scroll")

    def action_close(self) -> None:
        self.app.pop_screen()


class ThemePickerScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    ThemePickerScreen { align: center middle; }
    #theme-box { width: 38; max-width: 90%; height: 80%; padding: 1 2; background: $surface; border: solid $primary; }
    #theme-title { width: 100%; content-align: center middle; text-style: bold; color: $accent; margin-bottom: 1; }
    #theme-list { height: 1fr; background: $surface; }
    #theme-hint { height: 1; margin-top: 1; color: $text-muted; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    def __init__(self, current: str):
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Select theme", id="theme-title"),
            ListView(id="theme-list"),
            Static("Enter apply - Esc cancel", id="theme-hint"),
            id="theme-box",
        )

    def on_mount(self) -> None:
        view = self.query_one("#theme-list", ListView)
        for index, (key, data) in enumerate(THEMES.items()):
            prefix = "* " if key == self._current else "  "
            item = ListItem(Label(f"{prefix}{data['name']}"))
            item.theme_key = key
            view.append(item)
            if key == self._current:
                view.index = index
        view.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if hasattr(event.item, "theme_key"):
            self.dismiss(event.item.theme_key)

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            item = self.query_one("#theme-list", ListView).highlighted_child
            if item and hasattr(item, "theme_key"):
                self.dismiss(item.theme_key)
            event.prevent_default()

    def action_cancel(self) -> None:
        self.dismiss("")


class ScreenPickerScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    ScreenPickerScreen { align: center middle; }
    #screen-box { width: 64; max-width: 95%; height: auto; max-height: 80%; padding: 1 2; background: $surface; border: solid $primary; }
    #screen-title { width: 100%; content-align: center middle; text-style: bold; color: $accent; margin-bottom: 1; }
    #screen-list { height: auto; background: $surface; }
    #screen-hint { height: 1; margin-top: 1; color: $text-muted; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    def __init__(self, current: str, choices: Sequence[tuple[str, str]]):
        super().__init__()
        self._current = current
        self._choices = list(choices)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Default playback screen", id="screen-title"),
            ListView(id="screen-list"),
            Static("Enter apply - Esc cancel", id="screen-hint"),
            id="screen-box",
        )

    def on_mount(self) -> None:
        view = self.query_one("#screen-list", ListView)
        selected = 0
        for index, (value, label) in enumerate(self._choices):
            prefix = "* " if value == self._current else "  "
            item = ListItem(Label(f"{prefix}{label}"))
            item.screen_value = value
            view.append(item)
            if value == self._current:
                selected = index
        if view.children:
            view.index = selected
        view.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if hasattr(event.item, "screen_value"):
            self.dismiss(event.item.screen_value)

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            item = self.query_one("#screen-list", ListView).highlighted_child
            if item and hasattr(item, "screen_value"):
                self.dismiss(item.screen_value)
            event.prevent_default()

    def action_cancel(self) -> None:
        self.dismiss("")


class FolderSetupScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    FolderSetupScreen { align: center middle; }
    #folder-setup-box { width: 76; max-width: 96%; height: auto; padding: 1 2; background: $surface; border: solid $primary; }
    #folder-setup-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #folder-setup-detail { width: 100%; color: $text; margin-bottom: 1; }
    #folder-setup-list { height: auto; background: $surface; }
    #folder-setup-hint { width: 100%; color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    def __init__(self, missing_path: str):
        super().__init__()
        self._missing_path = missing_path

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Choose video folder", id="folder-setup-title"),
            Static(f"  {self._missing_path} does not exist.", id="folder-setup-detail"),
            ListView(id="folder-setup-list"),
            Static("Enter select - Esc keep current setting", id="folder-setup-hint"),
            id="folder-setup-box",
        )

    def on_mount(self) -> None:
        view = self.query_one("#folder-setup-list", ListView)
        choices = (
            ("Create and use default folder", "create_default"),
            ("Choose another folder", "browse"),
            ("Use this terminal folder", "use_cwd"),
        )
        for label, action in choices:
            item = ListItem(Label(f"  {label}"))
            item.folder_setup_action = action
            view.append(item)
        view.index = 0
        view.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(getattr(event.item, "folder_setup_action", ""))

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            item = self.query_one("#folder-setup-list", ListView).highlighted_child
            self.dismiss(getattr(item, "folder_setup_action", "") if item else "")
            event.prevent_default()

    def action_cancel(self) -> None:
        self.dismiss("")


class DirectoryPickerScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    DirectoryPickerScreen { align: center middle; }
    #dir-box { width: 88; max-width: 98%; height: 88%; padding: 1 2; background: $surface; border: solid $primary; }
    #dir-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #dir-path { width: 100%; color: $text; margin-bottom: 1; }
    #dir-list { height: 1fr; background: $surface; }
    #dir-hint { width: 100%; color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    def __init__(self, start: str):
        super().__init__()
        self._current = Path(start).expanduser()

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Folder browser", id="dir-title"),
            Static("", id="dir-path"),
            ListView(id="dir-list"),
            Static("Enter open - u use folder - n new folder - h/backspace parent - ~ home - Esc cancel", id="dir-hint"),
            id="dir-box",
        )

    def on_mount(self) -> None:
        self._refresh()

    def on_key(self, event: events.Key) -> None:
        key = event.key
        if key == "enter":
            item = self.query_one("#dir-list", ListView).highlighted_child
            action = getattr(item, "dir_action", "") if item else ""
            path = getattr(item, "dir_path", "") if item else ""
            if action == "open" and path:
                self._current = Path(path)
                self._refresh()
            elif action == "use" and path:
                self.dismiss(f"use:{path}")
            event.prevent_default()
        elif key == "u":
            self.dismiss(f"use:{self._current}")
            event.prevent_default()
        elif key == "n":
            self.dismiss(f"new:{self._current}")
            event.prevent_default()
        elif key in {"h", "backspace", "delete"}:
            self._current = self._current.parent
            self._refresh()
            event.prevent_default()
        elif key == "home" or getattr(event, "character", "") == "~":
            self._current = Path.home()
            self._refresh()
            event.prevent_default()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        action = getattr(event.item, "dir_action", "")
        path = getattr(event.item, "dir_path", "")
        if action == "open" and path:
            self._current = Path(path)
            self._refresh()
        elif action == "use" and path:
            self.dismiss(f"use:{path}")

    def action_cancel(self) -> None:
        self.dismiss("")

    def _refresh(self) -> None:
        if not self._current.exists():
            self._current = self._current.parent
        self._current = self._current.resolve()
        self.query_one("#dir-path", Static).update(f"  {self._current}")
        view = self.query_one("#dir-list", ListView)
        view.clear()
        rows = [("Use this folder", "use", self._current), ("..", "open", self._current.parent)]
        try:
            dirs = sorted((path for path in self._current.iterdir() if path.is_dir()), key=lambda item: item.name.lower())
        except OSError:
            dirs = []
        rows.extend((path.name, "open", path) for path in dirs)
        for label, action, path in rows:
            prefix = "[use]" if action == "use" else "[dir]"
            item = ListItem(Label(f"  {prefix:<5} {label}"))
            item.dir_action = action
            item.dir_path = str(path)
            view.append(item)
        view.index = 0
        view.focus()


class SettingsScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    SettingsScreen { align: center middle; }
    #settings-box { width: 72; max-width: 95%; height: auto; padding: 1 2; background: $surface; border: solid $primary; }
    #settings-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #settings-list { height: auto; background: $surface; }
    #settings-detail { width: 100%; min-height: 3; color: $text; margin-top: 1; }
    #settings-hint { width: 100%; color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    DEFAULT_ACTIONS = [
        SettingsAction("Themes", "module_settings:theme", "Choose the active color scheme."),
        SettingsAction("Video folder", "folder", "Choose where vplay scans for local media."),
        SettingsAction("Add ons modules", "module_editor", "Enable, disable, and place modules."),
        SettingsAction("User memory", "user_memory", "Review saved names and playback chunks."),
        SettingsAction("About", "about", "Version, developer, and update check."),
    ]

    def __init__(self, actions: Optional[Sequence[SettingsAction | tuple[str, str] | tuple[str, str, str]]] = None):
        super().__init__()
        self._actions = [_settings_action(item) for item in (actions or self.DEFAULT_ACTIONS)]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Settings", id="settings-title"),
            ListView(id="settings-list"),
            Static("", id="settings-detail"),
            Static("Enter select - Esc close", id="settings-hint"),
            id="settings-box",
        )

    def on_mount(self) -> None:
        view = self.query_one("#settings-list", ListView)
        for action in self._actions:
            item = ListItem(Label(f"  {action.label}"))
            item.settings_action = action.action
            item.settings_description = action.description
            view.append(item)
        if view.children:
            view.index = 0
        view.focus()
        self._update_detail()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if hasattr(event.item, "settings_action"):
            self.dismiss(event.item.settings_action)

    def on_list_view_highlighted(self, _event: ListView.Highlighted) -> None:
        self._update_detail()

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            item = self.query_one("#settings-list", ListView).highlighted_child
            if item and hasattr(item, "settings_action"):
                self.dismiss(item.settings_action)
            event.prevent_default()

    def action_cancel(self) -> None:
        self.dismiss("")

    def _update_detail(self) -> None:
        item = self.query_one("#settings-list", ListView).highlighted_child
        detail = getattr(item, "settings_description", "") if item else ""
        self.query_one("#settings-detail", Static).update(f"  {detail}" if detail else "")


def _settings_action(item: SettingsAction | tuple[str, str] | tuple[str, str, str]) -> SettingsAction:
    if isinstance(item, SettingsAction):
        return item
    if len(item) == 2:
        label, action = item
        return SettingsAction(str(label), str(action))
    label, action, description = item
    return SettingsAction(str(label), str(action), str(description))


class ModuleConflictScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    ModuleConflictScreen { align: center middle; }
    #conflict-box { width: 72; max-width: 95%; height: auto; padding: 1 2; background: $surface; border: solid $primary; }
    #conflict-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #conflict-detail { width: 100%; color: $text; margin-bottom: 1; }
    #conflict-list { height: auto; background: $surface; }
    #conflict-hint { width: 100%; color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    CHOICES = [
        ("Replace occupant", "replace"),
        ("Split horizontal", "split_horizontal"),
        ("Split vertical", "split_vertical"),
        ("Cancel", "cancel"),
    ]

    def __init__(self, conflict: ModuleConflict, module_title: str, occupant_titles: Sequence[str]):
        super().__init__()
        self._conflict = conflict
        self._module_title = module_title
        self._occupants = ", ".join(occupant_titles)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Module slot conflict", id="conflict-title"),
            Static(f"{self._module_title} wants {self._conflict.slot}, currently used by {self._occupants}.", id="conflict-detail"),
            ListView(id="conflict-list"),
            Static("Enter choose - Esc cancel", id="conflict-hint"),
            id="conflict-box",
        )

    def on_mount(self) -> None:
        view = self.query_one("#conflict-list", ListView)
        for label, action in self.CHOICES:
            item = ListItem(Label(f"  {label}"))
            item.conflict_action = action
            view.append(item)
        view.index = 0
        view.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if hasattr(event.item, "conflict_action"):
            self.dismiss(event.item.conflict_action)

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            item = self.query_one("#conflict-list", ListView).highlighted_child
            if item and hasattr(item, "conflict_action"):
                self.dismiss(item.conflict_action)
            event.prevent_default()

    def action_cancel(self) -> None:
        self.dismiss("cancel")


class ModuleEditorScreen(ModalScreen[Optional[ModuleLayout]]):
    DEFAULT_CSS = """
    ModuleEditorScreen { align: center middle; }
    #module-box { width: 94; max-width: 98%; height: 88%; padding: 1 2; background: $surface; border: solid $primary; }
    #module-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #module-list { height: 1fr; background: $surface; }
    #module-hint { width: 100%; color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    def __init__(self, registry: ModuleRegistry, layout: ModuleLayout):
        super().__init__()
        self._registry = registry
        self._layout = layout.copy()

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Add ons modules", id="module-title"),
            ListView(id="module-list"),
            Static("Space toggle - h/l slot - J/K order - s split - u unsplit - r reset - Enter save - Esc cancel", id="module-hint"),
            id="module-box",
        )

    def on_mount(self) -> None:
        self._refresh_list()
        self.query_one("#module-list", ListView).focus()

    def on_key(self, event: events.Key) -> None:
        key = event.key
        module_id = self._selected_module_id()
        if key in ("enter", "w"):
            self.dismiss(self._layout)
            event.prevent_default()
            return
        if key in ("escape", "q"):
            self.dismiss(None)
            event.prevent_default()
            return
        if key == "r":
            self._layout.reset(self._registry)
            self._refresh_list()
            event.prevent_default()
            return
        if not module_id:
            return
        if key == "space":
            self._toggle(module_id)
        elif key in ("h", "left"):
            self._move_slot(module_id, -1)
        elif key in ("l", "right"):
            self._move_slot(module_id, 1)
        elif key in ("J", "shift+j"):
            self._layout.move_within_slot(module_id, 1)
            self._refresh_list(module_id)
        elif key in ("K", "shift+k"):
            self._layout.move_within_slot(module_id, -1)
            self._refresh_list(module_id)
        elif key == "s":
            slot = self._layout.slots.get(module_id)
            if slot:
                mode = self._layout.cycle_split(slot)
                self.app.notify(f"{slot} split: {mode}")
                self._refresh_list(module_id)
        elif key == "u":
            slot = self._layout.slots.get(module_id)
            if slot and not self._layout.unsplit_slot(slot, module_id, self._registry):
                self.app.notify("Cannot unsplit across another core module", severity="warning")
            self._refresh_list(module_id)
        else:
            return
        event.prevent_default()

    def _toggle(self, module_id: str) -> None:
        spec = self._registry.specs[module_id]
        enabled = self._layout.enabled.get(module_id, False)
        if spec.core:
            self.app.notify("Core modules cannot be disabled", severity="warning")
            return
        if enabled:
            self._layout.set_enabled(module_id, False, self._registry)
            self._refresh_list(module_id)
            return
        if spec.has_pane and not self._layout.can_enable(module_id):
            self.app.notify(f"Maximum visible modules is {MAX_VISIBLE_MODULES}", severity="warning")
            return
        slot = self._layout.slots.get(module_id, spec.default_slot)
        occupants = tuple(item for item in self._layout.visible_in_slot(slot) if item != module_id)
        if occupants:
            self._ask_conflict(ModuleConflict(module_id, slot, occupants))
            return
        self._layout.set_enabled(module_id, True, self._registry)
        self._refresh_list(module_id)

    def _move_slot(self, module_id: str, direction: int) -> None:
        spec = self._registry.specs[module_id]
        if not spec.has_pane:
            self.app.notify(f"{spec.title} does not own a pane", severity="warning")
            return
        current = self._layout.slots.get(module_id, spec.default_slot or "right_bottom")
        current_index = SLOT_ORDER.index(current)
        target = SLOT_ORDER[(current_index + direction) % len(SLOT_ORDER)]
        conflict = self._layout.move_to_slot(module_id, target)
        if conflict:
            self._ask_conflict(conflict)
            return
        self._refresh_list(module_id)

    def _ask_conflict(self, conflict: ModuleConflict) -> None:
        spec = self._registry.specs[conflict.module_id]
        titles = [self._registry.specs[module_id].title for module_id in conflict.occupants]

        def done(action: str) -> None:
            if action == "replace":
                if not self._layout.replace_into_slot(conflict.module_id, conflict.slot, self._registry):
                    self.app.notify("Cannot replace a core module", severity="warning")
            elif action == "split_horizontal":
                if not self._layout.split_into_slot(conflict.module_id, conflict.slot, "horizontal"):
                    self.app.notify(f"Maximum visible modules is {MAX_VISIBLE_MODULES}", severity="warning")
            elif action == "split_vertical":
                if not self._layout.split_into_slot(conflict.module_id, conflict.slot, "vertical"):
                    self.app.notify(f"Maximum visible modules is {MAX_VISIBLE_MODULES}", severity="warning")
            self._refresh_list(conflict.module_id)

        self.app.push_screen(ModuleConflictScreen(conflict, spec.title, titles), done)

    def _refresh_list(self, selected_module_id: str | None = None) -> None:
        view = self.query_one("#module-list", ListView)
        previous = view.index or 0
        view.clear()
        rows = self._rows()
        selected_index = previous
        for index, module_id in enumerate(rows):
            spec = self._registry.specs[module_id]
            enabled = self._layout.enabled.get(module_id, False)
            slot = self._layout.slots.get(module_id, spec.default_slot) if spec.has_pane else "-"
            split = self._layout.splits.get(slot, "") if spec.has_pane else "-"
            key = self._registry.assigned_keys.get(module_id)
            marker = "*" if enabled else " "
            core = "core" if spec.core else spec.kind.value
            key_text = f" key:{key.key}" if key and key.key else ""
            surfaces = ",".join(spec.surfaces)
            line = f"{marker} {spec.title:<14} {core:<6} {surfaces:<17} slot:{slot:<12} split:{split:<10}{key_text}"
            item = ListItem(Label(line))
            item.module_id = module_id
            view.append(item)
            if module_id == selected_module_id:
                selected_index = index
        if view.children:
            view.index = min(selected_index, len(view.children) - 1)

    def _rows(self) -> list[str]:
        rows: list[str] = []
        for slot in SLOT_ORDER:
            rows.extend(self._layout.order.get(slot, []))
        for module_id in sorted(self._registry.specs):
            if module_id not in rows:
                rows.append(module_id)
        return rows

    def _selected_module_id(self) -> str | None:
        item = self.query_one("#module-list", ListView).highlighted_child
        if item and hasattr(item, "module_id"):
            return item.module_id
        return None

    def action_cancel(self) -> None:
        self.dismiss(None)


class UserMemoryScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    UserMemoryScreen { align: center middle; }
    #memory-box { width: 92; max-width: 98%; height: 88%; padding: 1 2; background: $surface; border: solid $primary; }
    #memory-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #memory-list { height: 1fr; background: $surface; }
    #memory-detail { width: 100%; height: 3; color: $text; margin-top: 1; }
    #memory-hint { width: 100%; color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    def __init__(self, rows: Sequence[MemoryAction]):
        super().__init__()
        self._rows = list(rows)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("User memory", id="memory-title"),
            ListView(id="memory-list"),
            Static("", id="memory-detail"),
            Static("Enter edit/run - x reset selected - Esc close", id="memory-hint"),
            id="memory-box",
        )

    def on_mount(self) -> None:
        view = self.query_one("#memory-list", ListView)
        for row in self._rows:
            item = ListItem(Label(f"  {row.label}"))
            item.memory_action = row.action
            item.memory_reset_action = row.reset_action
            item.memory_description = row.description
            view.append(item)
        if view.children:
            view.index = 0
        view.focus()
        self._update_detail()

    def on_list_view_highlighted(self, _event: ListView.Highlighted) -> None:
        self._update_detail()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        action = getattr(event.item, "memory_action", "")
        if action:
            self.dismiss(action)

    def on_key(self, event: events.Key) -> None:
        item = self.query_one("#memory-list", ListView).highlighted_child
        if not item:
            return
        if event.key == "enter":
            action = getattr(item, "memory_action", "")
            if action:
                self.dismiss(action)
            event.prevent_default()
        elif event.key == "x":
            action = getattr(item, "memory_reset_action", "")
            if action:
                self.dismiss(action)
            event.prevent_default()

    def action_cancel(self) -> None:
        self.dismiss("")

    def _update_detail(self) -> None:
        item = self.query_one("#memory-list", ListView).highlighted_child
        detail = getattr(item, "memory_description", "") if item else ""
        self.query_one("#memory-detail", Static).update(f"  {detail}" if detail else "")


class AboutScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    AboutScreen { align: center middle; }
    #about-box { width: 68; max-width: 95%; height: auto; padding: 1 2; background: $surface; border: solid $primary; }
    #about-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #about-text { width: 100%; color: $text; margin-bottom: 1; }
    #about-list { height: auto; background: $surface; }
    #about-hint { width: 100%; color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    def __init__(self, version: str, build: str, release: str, install_method: str = "source"):
        super().__init__()
        self._version = version
        self._build = build
        self._release = release
        self._install_method = install_method

    def compose(self) -> ComposeResult:
        text = (
            f"  Developer: Raz\n"
            f"  Version: {self._version}\n"
            f"  Build: {self._build}\n"
            f"  Release: {self._release}\n"
            f"  Install: {self._install_method}"
        )
        yield Vertical(
            Static("About vplay", id="about-title"),
            Static(text, id="about-text"),
            ListView(id="about-list"),
            Static("Enter select - Esc close", id="about-hint"),
            id="about-box",
        )

    def on_mount(self) -> None:
        view = self.query_one("#about-list", ListView)
        check = ListItem(Label("  Check for updates"))
        check.about_action = "check_updates"
        close = ListItem(Label("  Close"))
        close.about_action = ""
        view.append(check)
        view.append(close)
        view.index = 0
        view.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(getattr(event.item, "about_action", ""))

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            item = self.query_one("#about-list", ListView).highlighted_child
            self.dismiss(getattr(item, "about_action", "") if item else "")
            event.prevent_default()

    def action_cancel(self) -> None:
        self.dismiss("")


class UpdateScreen(ModalScreen[str]):
    DEFAULT_CSS = """
    UpdateScreen { align: center middle; }
    #update-box { width: 76; max-width: 96%; height: auto; padding: 1 2; background: $surface; border: solid $primary; }
    #update-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #update-text { width: 100%; color: $text; margin-bottom: 1; }
    #update-list { height: auto; background: $surface; }
    #update-hint { width: 100%; color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [Binding("escape,q", "cancel")]

    def __init__(self, title: str, detail: str, can_install: bool):
        super().__init__()
        self._title = title
        self._detail = detail
        self._can_install = can_install

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self._title, id="update-title"),
            Static(self._detail, id="update-text"),
            ListView(id="update-list"),
            Static("Enter select - Esc close", id="update-hint"),
            id="update-box",
        )

    def on_mount(self) -> None:
        view = self.query_one("#update-list", ListView)
        if self._can_install:
            install = ListItem(Label("  Install update"))
            install.update_action = "install_update"
            view.append(install)
        recheck = ListItem(Label("  Check again"))
        recheck.update_action = "check_updates"
        close = ListItem(Label("  Close"))
        close.update_action = ""
        view.append(recheck)
        view.append(close)
        view.index = 0
        view.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(getattr(event.item, "update_action", ""))

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            item = self.query_one("#update-list", ListView).highlighted_child
            self.dismiss(getattr(item, "update_action", "") if item else "")
            event.prevent_default()

    def action_cancel(self) -> None:
        self.dismiss("")


class DownloadQueueScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    DownloadQueueScreen { align: center middle; }
    #queue-box { width: 84; max-width: 95%; height: 60%; padding: 1 2; background: $surface; border: solid $primary; }
    #queue-title { width: 100%; text-style: bold; color: $accent; margin-bottom: 1; }
    #queue-list { height: 1fr; background: $surface; }
    #queue-hint { height: 1; margin-top: 1; color: $text-muted; }
    """
    BINDINGS = [Binding("escape,q", "close")]

    def __init__(
        self,
        entries: Callable[[], Sequence[DownloadEntry]],
        cancel: Callable[[int], None],
        play: Callable[[int], None],
    ):
        super().__init__()
        self._entries = entries
        self._cancel = cancel
        self._play = play

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Downloads", id="queue-title"),
            ListView(id="queue-list"),
            Static("x cancel - Space play partial - Esc close", id="queue-hint"),
            id="queue-box",
        )

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(1.0, self._refresh)
        self.query_one("#queue-list", ListView).focus()

    def on_key(self, event: events.Key) -> None:
        item = self.query_one("#queue-list", ListView).highlighted_child
        if not item or not hasattr(item, "download_id"):
            return
        if event.key == "x":
            self._cancel(item.download_id)
            self._refresh()
            event.prevent_default()
        elif event.key == "space":
            self._play(item.download_id)
            event.prevent_default()

    def _refresh(self) -> None:
        view = self.query_one("#queue-list", ListView)
        saved = view.index or 0
        view.clear()
        entries = list(self._entries())
        if not entries:
            item = ListItem(Label("  No downloads"))
            item.download_id = None
            view.append(item)
            return
        for entry in entries:
            name = entry.filename[:40]
            if entry.done:
                line = f"  {name}  {entry.status}"
            else:
                line = f"  {name}  {progress_bar(entry.percent, 100, 16)} {entry.percent:.0f}%"
                if entry.speed:
                    line += f"  {entry.speed}"
            item = ListItem(Label(line))
            item.download_id = entry.id
            view.append(item)
        if view.children:
            view.index = min(saved, len(view.children) - 1)

    def action_close(self) -> None:
        self.app.pop_screen()
