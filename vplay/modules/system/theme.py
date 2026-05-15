from __future__ import annotations

from ..base import HookPoint, ModuleKind, ModuleSpec


SPEC = ModuleSpec(
    id="theme",
    title="Theme",
    kind=ModuleKind.SYSTEM,
    core=True,
    enabled_by_default=True,
    surfaces=("enhancer", "settings"),
    key_preferences=("t",),
    capabilities=("apply color scheme", "provide settings pane"),
    hook_points=(HookPoint.SETTINGS,),
    renderer="theme",
)
