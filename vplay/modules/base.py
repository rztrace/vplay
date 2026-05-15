from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Mapping, Optional, Sequence


ModuleSlot = Literal["left", "right_top", "right_bottom"]
SplitMode = Literal["vertical", "horizontal"]
ModuleSurface = Literal["pane", "enhancer", "settings"]


class HookPoint(str, Enum):
    LIBRARY_ROW = "library.row"
    PLAYLIST_ROW = "playlist.row"
    MODULE_FOOTER = "module.footer"
    PLAYBACK_OPTIONS = "playback.options"
    SETTINGS = "settings"


class ModuleKind(str, Enum):
    SYSTEM = "system"
    USER = "user"


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    title: str
    kind: ModuleKind
    default_slot: Optional[ModuleSlot] = None
    core: bool = False
    enabled_by_default: bool = False
    surfaces: Sequence[ModuleSurface] = ("pane",)
    key_preferences: Sequence[str] = field(default_factory=tuple)
    capabilities: Sequence[str] = field(default_factory=tuple)
    target_modules: Sequence[str] = field(default_factory=tuple)
    hook_points: Sequence[HookPoint] = field(default_factory=tuple)
    content: str = ""
    renderer: str = "static"
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def has_pane(self) -> bool:
        return "pane" in self.surfaces

    @property
    def has_settings(self) -> bool:
        return "settings" in self.surfaces

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ModuleSpec":
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            kind=ModuleKind(str(data.get("kind", ModuleKind.USER.value))),
            default_slot=data.get("default_slot", None),  # type: ignore[arg-type]
            core=bool(data.get("core", False)),
            enabled_by_default=bool(data.get("enabled_by_default", False)),
            surfaces=tuple(str(s) for s in data.get("surfaces", ("pane",))),  # type: ignore[union-attr]
            key_preferences=tuple(str(k) for k in data.get("key_preferences", ())),  # type: ignore[union-attr]
            capabilities=tuple(str(c) for c in data.get("capabilities", ())),  # type: ignore[union-attr]
            target_modules=tuple(str(m) for m in data.get("target_modules", ())),  # type: ignore[union-attr]
            hook_points=tuple(HookPoint(str(h)) for h in data.get("hook_points", ())),  # type: ignore[union-attr]
            content=str(data.get("content", "")),
            renderer=str(data.get("renderer", "static")),
            metadata=dict(data.get("metadata", {})),  # type: ignore[arg-type]
        )


@dataclass
class ModulePlacement:
    module_id: str
    slot: ModuleSlot
    enabled: bool = True


@dataclass
class ModuleConflict:
    module_id: str
    slot: ModuleSlot
    occupants: tuple[str, ...]


SLOT_ORDER: tuple[ModuleSlot, ...] = ("left", "right_top", "right_bottom")
DEFAULT_SLOT_SPLITS: dict[ModuleSlot, SplitMode] = {
    "left": "vertical",
    "right_top": "vertical",
    "right_bottom": "horizontal",
}
MAX_VISIBLE_MODULES = 6
