from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from types import ModuleType

from .base import ModuleSpec
from .hooks import ModuleHooks
from .keymap import AssignedKey, assign_module_keys


SYSTEM_PACKAGE = "vplay.modules.system"
USER_PACKAGE = "vplay.modules.user"


@dataclass
class ModuleRegistry:
    specs: dict[str, ModuleSpec]
    assigned_keys: dict[str, AssignedKey]

    @classmethod
    def discover(cls) -> "ModuleRegistry":
        specs: dict[str, ModuleSpec] = {}
        for package_name in (SYSTEM_PACKAGE, USER_PACKAGE):
            package = importlib.import_module(package_name)
            for module_info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
                module = importlib.import_module(module_info.name)
                spec = _load_spec(module)
                if spec:
                    specs[spec.id] = spec
        ordered = sorted(specs.values(), key=lambda spec: (not spec.core, spec.kind.value, spec.id))
        return cls(specs=specs, assigned_keys=assign_module_keys(ordered))

    def system_specs(self) -> list[ModuleSpec]:
        return [spec for spec in self.specs.values() if spec.kind.value == "system"]

    def user_specs(self) -> list[ModuleSpec]:
        return [spec for spec in self.specs.values() if spec.kind.value == "user"]

    def active_hooks(self, layout) -> ModuleHooks:
        hooks = ModuleHooks()
        for module_id, spec in self.specs.items():
            if layout.enabled.get(module_id, False):
                hooks.add(spec)
        return hooks


def _load_spec(module: ModuleType) -> ModuleSpec | None:
    raw = getattr(module, "SPEC", None)
    if isinstance(raw, ModuleSpec):
        return raw
    if isinstance(raw, dict):
        return ModuleSpec.from_dict(raw)
    return None
