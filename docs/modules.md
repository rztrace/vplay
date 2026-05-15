# vplay Modules

`vplay` discovers modules from `vplay/modules/system` and `vplay/modules/user`.

System modules can require core app wiring. User modules should be simple and self-contained.

Minimal user module:

```python
from vplay.modules.base import ModuleKind, ModuleSpec

SPEC = ModuleSpec(
    id="notes",
    title="Notes",
    kind=ModuleKind.USER,
    default_slot="right_bottom",
    surfaces=("pane",),
    key_preferences=("n",),
    capabilities=("show static notes",),
    content="Add local notes here.",
)
```

A module is active only when the persisted layout enables it. Core system modules are always active.

Before adding keys, update the module spec. Let the key resolver assign the final key instead of hardcoding a global binding when possible.

Modules can also be behavior enhancers rather than panes:

```python
from vplay.modules.base import HookPoint, ModuleKind, ModuleSpec

SPEC = ModuleSpec(
    id="example_controls",
    title="Example Controls",
    kind=ModuleKind.SYSTEM,
    surfaces=("enhancer", "settings"),
    target_modules=("library", "playlist"),
    hook_points=(HookPoint.LIBRARY_ROW, HookPoint.PLAYLIST_ROW, HookPoint.SETTINGS),
    capabilities=("add inline row controls", "provide settings"),
)
```

Enhancers must describe where they attach; panes must describe where they live.

The built-in `screens` module is a default-active system enhancer. It does not own a main pane. It contributes settings and row-level playback controls to Library and Playlist, using `Shift+Space` to unfold controls under a row and `v` as a fallback when the terminal cannot distinguish shifted space. It is non-core, so users can deactivate it in Add ons modules.
