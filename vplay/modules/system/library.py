from __future__ import annotations

from ..base import ModuleKind, ModuleSpec


SPEC = ModuleSpec(
    id="library",
    title="Library",
    kind=ModuleKind.SYSTEM,
    default_slot="left",
    core=True,
    enabled_by_default=True,
    surfaces=("pane",),
    key_preferences=("o",),
    capabilities=("scan videos", "play file", "rename display names", "set file chunks"),
    renderer="library",
)
