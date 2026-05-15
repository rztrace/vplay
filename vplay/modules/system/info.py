from __future__ import annotations

from ..base import ModuleKind, ModuleSpec


SPEC = ModuleSpec(
    id="info",
    title="Info",
    kind=ModuleKind.SYSTEM,
    default_slot="right_bottom",
    core=True,
    enabled_by_default=True,
    surfaces=("pane",),
    key_preferences=("i",),
    capabilities=("selected media metadata", "playback progress", "chunk summary"),
    renderer="info",
)
