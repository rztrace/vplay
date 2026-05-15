from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable

from .base import DEFAULT_SLOT_SPLITS, MAX_VISIBLE_MODULES, SLOT_ORDER, ModuleConflict, ModuleSlot, SplitMode


DEFAULT_FALLBACK_SLOT: ModuleSlot = "right_bottom"


@dataclass
class ModuleLayout:
    enabled: dict[str, bool] = field(default_factory=dict)
    slots: dict[str, ModuleSlot] = field(default_factory=dict)
    order: dict[ModuleSlot, list[str]] = field(default_factory=lambda: {slot: [] for slot in SLOT_ORDER})
    splits: dict[ModuleSlot, SplitMode] = field(default_factory=lambda: dict(DEFAULT_SLOT_SPLITS))

    @classmethod
    def from_dict(cls, data: dict | None, registry) -> "ModuleLayout":
        layout = cls.defaults(registry)
        data = data or {}
        layout.enabled.update({str(k): bool(v) for k, v in (data.get("enabled") or {}).items()})
        layout.slots.update({str(k): _slot(v, layout.slots.get(str(k), "right_bottom")) for k, v in (data.get("slots") or {}).items()})
        for slot, items in (data.get("order") or {}).items():
            normalized = _slot(slot, None)
            if normalized:
                layout.order[normalized] = [
                    str(item)
                    for item in items
                    if str(item) in registry.specs and registry.specs[str(item)].has_pane
                ]
        for raw_slot, value in (data.get("splits") or {}).items():
            normalized_slot = _slot(raw_slot, None)
            if normalized_slot:
                layout.splits[normalized_slot] = _split(value)
        layout._ensure_core(registry)
        layout._rebuild_missing_order(registry)
        return layout

    @classmethod
    def defaults(cls, registry) -> "ModuleLayout":
        layout = cls()
        for spec in registry.specs.values():
            enabled = spec.core or spec.enabled_by_default
            layout.enabled[spec.id] = enabled
            if spec.has_pane:
                slot = spec.default_slot or DEFAULT_FALLBACK_SLOT
                layout.slots[spec.id] = slot
                if enabled:
                    layout.order.setdefault(slot, [])
                    if spec.id not in layout.order[slot]:
                        layout.order[slot].append(spec.id)
        return layout

    def copy(self) -> "ModuleLayout":
        return deepcopy(self)

    def to_dict(self) -> dict:
        return {
            "enabled": dict(sorted(self.enabled.items())),
            "slots": dict(sorted(self.slots.items())),
            "order": {slot: list(self.order.get(slot, [])) for slot in SLOT_ORDER},
            "splits": dict(self.splits),
        }

    def visible(self) -> list[str]:
        result: list[str] = []
        for slot in SLOT_ORDER:
            result.extend(module_id for module_id in self.order.get(slot, []) if self.enabled.get(module_id, False))
        return result

    def visible_in_slot(self, slot: ModuleSlot) -> list[str]:
        return [module_id for module_id in self.order.get(slot, []) if self.enabled.get(module_id, False)]

    def active_count(self) -> int:
        return len(self.visible())

    def can_enable(self, module_id: str) -> bool:
        return self.enabled.get(module_id, False) or self.active_count() < MAX_VISIBLE_MODULES

    def set_enabled(self, module_id: str, enabled: bool, registry) -> bool:
        spec = registry.specs[module_id]
        if spec.core and not enabled:
            return False
        if spec.has_pane and enabled and not self.can_enable(module_id):
            return False
        self.enabled[module_id] = enabled
        if spec.has_pane:
            slot = self.slots.get(module_id, spec.default_slot or DEFAULT_FALLBACK_SLOT)
            self._ensure_in_slot(module_id, slot)
        return True

    def move_to_slot(self, module_id: str, slot: ModuleSlot) -> ModuleConflict | None:
        if not self.slots.get(module_id):
            return None
        current = self.slots.get(module_id)
        occupants = tuple(item for item in self.visible_in_slot(slot) if item != module_id)
        if occupants and current != slot:
            return ModuleConflict(module_id, slot, occupants)
        self._place(module_id, slot)
        return None

    def replace_into_slot(self, module_id: str, slot: ModuleSlot, registry) -> bool:
        occupants = [occupant for occupant in self.visible_in_slot(slot) if occupant != module_id]
        if any(registry.specs[occupant].core for occupant in occupants):
            return False
        for occupant in occupants:
            self.enabled[occupant] = False
        self._place(module_id, slot)
        self.enabled[module_id] = True
        return True

    def split_into_slot(self, module_id: str, slot: ModuleSlot, split: SplitMode) -> bool:
        if not self.slots.get(module_id):
            return False
        if not self.enabled.get(module_id, False) and self.active_count() >= MAX_VISIBLE_MODULES:
            return False
        self.splits[slot] = split
        self.enabled[module_id] = True
        self._place(module_id, slot)
        return True

    def move_within_slot(self, module_id: str, direction: int) -> bool:
        slot = self.slots.get(module_id)
        if not slot:
            return False
        items = self.order.setdefault(slot, [])
        if module_id not in items:
            return False
        index = items.index(module_id)
        target = index + direction
        if not 0 <= target < len(items):
            return False
        items[index], items[target] = items[target], items[index]
        return True

    def cycle_split(self, slot: ModuleSlot) -> SplitMode:
        current = self.splits.get(slot, DEFAULT_SLOT_SPLITS[slot])
        next_value = "horizontal" if current == "vertical" else "vertical"
        self.splits[slot] = next_value
        return next_value

    def unsplit_slot(self, slot: ModuleSlot, keep_module_id: str, registry) -> bool:
        colocated = [module_id for module_id in self.visible_in_slot(slot) if module_id != keep_module_id]
        if any(registry.specs[module_id].core for module_id in colocated):
            return False
        for module_id in colocated:
            self.enabled[module_id] = False
        self.splits[slot] = DEFAULT_SLOT_SPLITS[slot]
        return True

    def reset(self, registry) -> None:
        fresh = self.defaults(registry)
        self.enabled = fresh.enabled
        self.slots = fresh.slots
        self.order = fresh.order
        self.splits = fresh.splits

    def _place(self, module_id: str, slot: ModuleSlot) -> None:
        old_slot = self.slots.get(module_id)
        if old_slot and module_id in self.order.get(old_slot, []):
            self.order[old_slot].remove(module_id)
        self.slots[module_id] = slot
        self._ensure_in_slot(module_id, slot)

    def _ensure_in_slot(self, module_id: str, slot: ModuleSlot) -> None:
        self.order.setdefault(slot, [])
        if module_id not in self.order[slot]:
            self.order[slot].append(module_id)

    def _ensure_core(self, registry) -> None:
        for spec in registry.specs.values():
            if spec.core:
                self.enabled[spec.id] = True
                if spec.has_pane:
                    self.slots.setdefault(spec.id, spec.default_slot or DEFAULT_FALLBACK_SLOT)
                    self._ensure_in_slot(spec.id, self.slots[spec.id])

    def _rebuild_missing_order(self, registry) -> None:
        known = set()
        for items in self.order.values():
            known.update(items)
        for spec in registry.specs.values():
            if not spec.has_pane:
                continue
            self.slots.setdefault(spec.id, spec.default_slot or DEFAULT_FALLBACK_SLOT)
            if spec.id not in known:
                self._ensure_in_slot(spec.id, self.slots[spec.id])


def _slot(value: object, fallback: ModuleSlot | None) -> ModuleSlot | None:
    text = str(value)
    if text in SLOT_ORDER:
        return text  # type: ignore[return-value]
    return fallback


def _split(value: object) -> SplitMode:
    return "horizontal" if str(value) == "horizontal" else "vertical"
