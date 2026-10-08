# garden_zones — static lane assignment (new file, not part of upstream ESPHome).
# Copyright (c) GardenPilot contributors.
# Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
#
# Pure Python, standard library only (no ESPHome imports): unit tested by tests/test_garden_zones.py.
"""Assigns the zones of one group to lanes (one stock-style controller per lane).

`max_parallel` is 1, "all" or a positive integer; `pins` holds, per zone in zone order, the explicit `lane:` or None.
Returns the lanes as ordered lists of zone numbers; the position of a zone in its lane is its valve index.
"""

from __future__ import annotations

from collections.abc import Sequence


class LanePlanError(ValueError):
    """The lane configuration of a group is invalid; the message names the group."""


def plan_lanes(group: str, max_parallel: int | str, pins: Sequence[int | None]) -> list[list[int]]:
    count = len(pins)
    if count == 0:
        raise LanePlanError(f"group '{group}': at least one zone is required")
    pinned = [pin for pin in pins if pin is not None]
    mode = max_parallel.lower() if isinstance(max_parallel, str) else max_parallel
    if mode == "1":
        mode = 1
    if mode not in ("all", 1) and not (isinstance(mode, int) and mode >= 1):
        raise LanePlanError(f"group '{group}': max_parallel must be 1, all or a positive integer, got {max_parallel!r}")

    if pinned and (mode == 1 or mode == "all"):
        raise LanePlanError(f"group '{group}': 'lane' needs an integer max_parallel greater than 1, got {mode}")
    if mode == 1:
        return [list(range(count))]
    if mode == "all":
        return [[zone] for zone in range(count)]

    lanes_available = int(mode)
    if pinned:
        if len(pinned) != count:
            raise LanePlanError(f"group '{group}': either every zone has a 'lane' or none (all-or-none)")
        slots: list[list[int]] = [[] for _ in range(lanes_available)]
        for zone, pin in enumerate(pins):
            assert pin is not None
            if not 0 <= pin < lanes_available:
                raise LanePlanError(
                    f"group '{group}': zone {zone} has lane {pin}, but max_parallel is {lanes_available} "
                    f"(lanes are 0..{lanes_available - 1})"
                )
            slots[pin].append(zone)
        return [lane for lane in slots if lane]

    if lanes_available >= count:
        return [[zone] for zone in range(count)]
    return [[zone for zone in range(count) if zone % lanes_available == lane] for lane in range(lanes_available)]
