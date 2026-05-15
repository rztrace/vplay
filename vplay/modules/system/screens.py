from __future__ import annotations

from ..base import HookPoint, ModuleKind, ModuleSpec


SPEC = ModuleSpec(
    id="screens",
    title="Screens",
    kind=ModuleKind.SYSTEM,
    core=False,
    enabled_by_default=True,
    surfaces=("enhancer", "settings"),
    key_preferences=("shift+space", "v"),
    capabilities=(
        "route playback to displays",
        "add inline per-track playback controls",
        "run independent mpv sessions",
        "provide screen settings",
    ),
    target_modules=("library", "playlist"),
    hook_points=(
        HookPoint.LIBRARY_ROW,
        HookPoint.PLAYLIST_ROW,
        HookPoint.PLAYBACK_OPTIONS,
        HookPoint.MODULE_FOOTER,
        HookPoint.SETTINGS,
    ),
    renderer="screens",
)
