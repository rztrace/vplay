from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict

from .base import HookPoint, ModuleSpec


class ModuleHooks:
    def __init__(self) -> None:
        self._by_point: DefaultDict[HookPoint, list[ModuleSpec]] = defaultdict(list)

    def add(self, spec: ModuleSpec) -> None:
        for hook in spec.hook_points:
            self._by_point[hook].append(spec)

    def for_point(self, hook: HookPoint) -> list[ModuleSpec]:
        return list(self._by_point.get(hook, []))

    def for_module(self, hook: HookPoint, module_id: str) -> list[ModuleSpec]:
        return [
            spec
            for spec in self._by_point.get(hook, [])
            if not spec.target_modules or module_id in spec.target_modules
        ]

