from __future__ import annotations

from ..base import ModuleKind, ModuleSpec


SPEC = ModuleSpec(
    id="notes",
    title="Notes",
    kind=ModuleKind.USER,
    default_slot="right_bottom",
    core=False,
    enabled_by_default=False,
    surfaces=("pane",),
    key_preferences=("n",),
    capabilities=("show static text", "prove user-module discovery"),
    content="User notes module. Edit vplay/modules/user/notes.py or add another user module file.",
)
