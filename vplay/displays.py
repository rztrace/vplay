from __future__ import annotations

import ctypes
import json
import subprocess
import time
from ctypes import POINTER, Structure, byref, c_double, c_int32, c_uint32
from dataclasses import dataclass
from typing import Optional


class CGPoint(Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


class CGSize(Structure):
    _fields_ = [("width", c_double), ("height", c_double)]


class CGRect(Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


@dataclass(frozen=True)
class DisplayInfo:
    index: int
    display_id: int
    name: str
    main: bool
    builtin: bool
    online: bool
    active: bool
    mirrored: bool
    bounds: tuple[float, float, float, float]
    pixels: tuple[int, int]
    vendor: int
    model: int
    serial: int

    @property
    def stable_key(self) -> str:
        return f"{self.vendor:x}:{self.model:x}:{self.serial:x}"

    @property
    def label(self) -> str:
        flags = []
        if self.main:
            flags.append("main")
        if self.builtin:
            flags.append("built-in")
        if self.mirrored:
            flags.append("mirrored")
        suffix = f" ({', '.join(flags)})" if flags else ""
        return f"{self.index}: {self.name}{suffix}"


class DisplayCatalog:
    def __init__(self) -> None:
        self._core_graphics = _load_core_graphics()
        self._last_snapshot: tuple[float, list[DisplayInfo]] | None = None
        self._last_names: tuple[float, dict[int, str]] | None = None

    def snapshot(self, *, max_age: float = 1.0, enrich_names: bool = True) -> list[DisplayInfo]:
        now = time.time()
        if self._last_snapshot and now - self._last_snapshot[0] <= max_age:
            return list(self._last_snapshot[1])
        displays = self._core_graphics_snapshot()
        if enrich_names:
            names = self._display_names()
            displays = [
                DisplayInfo(
                    index=item.index,
                    display_id=item.display_id,
                    name=names.get(item.display_id, item.name),
                    main=item.main,
                    builtin=item.builtin,
                    online=item.online,
                    active=item.active,
                    mirrored=item.mirrored,
                    bounds=item.bounds,
                    pixels=item.pixels,
                    vendor=item.vendor,
                    model=item.model,
                    serial=item.serial,
                )
                for item in displays
            ]
        self._last_snapshot = (now, displays)
        return list(displays)

    def resolve(self, preference: str) -> str:
        displays = self.snapshot(max_age=0.5)
        preference = preference or "auto-external"
        if preference in {"auto", "auto-external", "external"}:
            external = next((item for item in displays if item.active and not item.builtin and not item.mirrored), None)
            if external:
                return str(external.index)
            return "1" if len(displays) > 1 else "0"
        if preference.startswith("stable:"):
            wanted = preference.removeprefix("stable:")
            match = next((item for item in displays if item.stable_key == wanted), None)
            if match:
                return str(match.index)
            return self.resolve("auto-external")
        if preference.startswith("name:"):
            wanted = preference.removeprefix("name:").lower()
            match = next((item for item in displays if item.name.lower() == wanted), None)
            if match:
                return str(match.index)
            return self.resolve("auto-external")
        return preference

    def next_preference(self, current: str) -> str:
        displays = self.snapshot(max_age=0.2)
        values = ["auto-external"] + [str(item.index) for item in displays]
        if not values:
            return "auto-external"
        try:
            index = values.index(current)
        except ValueError:
            index = -1
        return values[(index + 1) % len(values)]

    def describe(self, preference: str) -> str:
        displays = self.snapshot(max_age=0.5)
        if preference in {"auto", "auto-external", "external"}:
            resolved = self.resolve(preference)
            match = next((item for item in displays if str(item.index) == resolved), None)
            return f"auto -> {match.label if match else resolved}"
        if preference.startswith("stable:"):
            resolved = self.resolve(preference)
            match = next((item for item in displays if str(item.index) == resolved), None)
            return match.label if match else preference
        match = next((item for item in displays if str(item.index) == str(preference)), None)
        return match.label if match else str(preference)

    def _core_graphics_snapshot(self) -> list[DisplayInfo]:
        cg = self._core_graphics
        if cg is None:
            return []
        try:
            count = c_uint32()
            list_function = cg.CGGetActiveDisplayList
            if list_function(0, None, byref(count)) != 0 or count.value <= 0:
                list_function = cg.CGGetOnlineDisplayList
                count = c_uint32()
            if list_function(0, None, byref(count)) != 0 or count.value <= 0:
                return []
            displays = (c_uint32 * count.value)()
            if list_function(count.value, displays, byref(count)) != 0:
                return []
            main = int(cg.CGMainDisplayID())
            result = []
            for index, raw_display_id in enumerate(displays[: count.value]):
                display_id = int(raw_display_id)
                bounds = cg.CGDisplayBounds(display_id)
                result.append(
                    DisplayInfo(
                        index=index,
                        display_id=display_id,
                        name=f"Screen {index}",
                        main=display_id == main,
                        builtin=bool(cg.CGDisplayIsBuiltin(display_id)),
                        online=bool(cg.CGDisplayIsOnline(display_id)),
                        active=bool(cg.CGDisplayIsActive(display_id)),
                        mirrored=bool(cg.CGDisplayIsInMirrorSet(display_id)),
                        bounds=(bounds.origin.x, bounds.origin.y, bounds.size.width, bounds.size.height),
                        pixels=(int(cg.CGDisplayPixelsWide(display_id)), int(cg.CGDisplayPixelsHigh(display_id))),
                        vendor=int(cg.CGDisplayVendorNumber(display_id)),
                        model=int(cg.CGDisplayModelNumber(display_id)),
                        serial=int(cg.CGDisplaySerialNumber(display_id)),
                    )
                )
            return result
        except (AttributeError, OSError, ValueError):
            return []

    def _display_names(self) -> dict[int, str]:
        now = time.time()
        if self._last_names and now - self._last_names[0] <= 15:
            return dict(self._last_names[1])
        names: dict[int, str] = {}
        try:
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            data = json.loads(result.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            self._last_names = (now, names)
            return names
        for gpu in data.get("SPDisplaysDataType", []):
            for display in gpu.get("spdisplays_ndrvs", []):
                try:
                    display_id = int(str(display.get("_spdisplays_displayID", "")), 10)
                except ValueError:
                    continue
                name = str(display.get("_name") or "").strip()
                if name:
                    names[display_id] = name
        self._last_names = (now, names)
        return names


def _load_core_graphics() -> Optional[ctypes.CDLL]:
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    except OSError:
        return None
    cg.CGGetActiveDisplayList.argtypes = [c_uint32, POINTER(c_uint32), POINTER(c_uint32)]
    cg.CGGetActiveDisplayList.restype = c_int32
    cg.CGGetOnlineDisplayList.argtypes = [c_uint32, POINTER(c_uint32), POINTER(c_uint32)]
    cg.CGGetOnlineDisplayList.restype = c_int32
    cg.CGMainDisplayID.argtypes = []
    cg.CGMainDisplayID.restype = c_uint32
    cg.CGDisplayBounds.argtypes = [c_uint32]
    cg.CGDisplayBounds.restype = CGRect
    for name in (
        "CGDisplayPixelsWide",
        "CGDisplayPixelsHigh",
        "CGDisplayIsBuiltin",
        "CGDisplayIsOnline",
        "CGDisplayIsActive",
        "CGDisplayIsInMirrorSet",
        "CGDisplayVendorNumber",
        "CGDisplayModelNumber",
        "CGDisplaySerialNumber",
    ):
        function = getattr(cg, name)
        function.argtypes = [c_uint32]
        function.restype = c_uint32
    return cg
