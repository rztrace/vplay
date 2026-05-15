from __future__ import annotations

from ..base import ModuleKind, ModuleSpec


SPEC = ModuleSpec(
    id="playlist",
    title="Playlist",
    kind=ModuleKind.SYSTEM,
    default_slot="right_top",
    core=False,
    enabled_by_default=True,
    surfaces=("pane",),
    key_preferences=("p",),
    capabilities=("ordered playlist", "play/pause", "move entries", "entry chunks"),
    renderer="playlist",
)
