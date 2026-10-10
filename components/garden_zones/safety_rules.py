# garden_zones — safety validation rules (new file, not part of upstream ESPHome).
# Copyright (c) GardenPilot contributors.
# Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
#
# Pure Python, standard library only (unit tested without ESPHome). All times are milliseconds. Every function returns an
# error message (str) or None; groups.py raises cv.Invalid with it.

ZONE_MARGIN_MS = 2000  # a run must end this long before max_on_time (the sprinkler opens a valve ~2 s late)
PUMP_IDLE_MARGIN_MS = 2000

MAX_ON_TIME_DEFAULT_MS = 60 * 60 * 1000
PUMP_MAX_ON_TIME_DEFAULT_MS = 2 * 60 * 60 * 1000
PUMP_IDLE_TIMEOUT_DEFAULT_MS = 10 * 1000
ON_TIME_MIN_MS = 1000
# Any positive duration is a valid limit, up to what a 32-bit millisecond timer can track wrap-safely (49.7 days; 30 days
# leaves a wide margin). The watchdog is disabled only explicitly with `never`.
ON_TIME_MAX_MS = 30 * 24 * 60 * 60 * 1000
NEVER = "never"

PUMP_ONLY_KEYS = ("pump_max_on_time", "pump_idle_timeout")

_SAFE_RESTORE_MODES = {"ALWAYS_OFF", "RESTORE_DEFAULT_OFF"}


def longest_run_ms(run_duration_ms, number_max_value, number_unit):
    """Longest run a zone can be configured to: its `run_duration`, or the run duration number's `max_value`."""
    if run_duration_ms is not None:
        return int(run_duration_ms)
    seconds = number_max_value * (60 if str(number_unit).lower() == "min" else 1)
    return int(seconds * 1000)


def zone_limit_error(zone, run_ms, start_delay_ms, max_on_ms, from_number=False):
    """`longest_run + pump delays + 2 s <= max_on_time` must hold for every zone.

    The pump delays are the ones that keep a valve open longer than its run: the pump-first / valve-first start delays
    and `pump_stop_valve_delay` (pump off first, the valve stays open); callers pass their sum or maximum."""
    needed = run_ms + start_delay_ms + ZONE_MARGIN_MS
    if needed <= max_on_ms:
        return None
    what = (
        f"the run duration number's max_value allows {run_ms / 1000:g} s"
        if from_number
        else f"run_duration is {run_ms / 1000:g} s"
    )
    fix = (
        "lower max_value of the run_duration_number or raise max_on_time"
        if from_number
        else "shorten the run or raise max_on_time"
    )
    delay = f" + pump delays {start_delay_ms / 1000:g} s" if start_delay_ms else ""
    return (
        f"{zone}: {what}{delay} + {ZONE_MARGIN_MS / 1000:g} s margin exceeds max_on_time "
        f"({max_on_ms / 1000:g} s); {fix}"
    )


def pump_limit_error(group, pump_max_ms, zone_limits_ms):
    """`pump_max_on_time` must not be below the effective `max_on_time` of any zone of the group."""
    for zone, limit in zone_limits_ms.items():
        if pump_max_ms < limit:
            return (
                f"group '{group}': pump_max_on_time ({pump_max_ms / 1000:g} s) is below max_on_time of {zone} "
                f"({limit / 1000:g} s); one normal zone run would trip the pump"
            )
    return None


def pump_idle_error(group, idle_ms, start_valve_delay_ms, stop_pump_delay_ms):
    """The pump may legally run without an open valve while it starts first (`pump_start_valve_delay`: the valve opens
    after this delay) and while it stays on after the valve closed (`pump_stop_pump_delay`)."""
    needed = max(start_valve_delay_ms, stop_pump_delay_ms) + PUMP_IDLE_MARGIN_MS
    if idle_ms >= needed:
        return None
    return (
        f"group '{group}': pump_idle_timeout ({idle_ms / 1000:g} s) must be at least "
        f"{needed / 1000:g} s (the longer of pump_start_valve_delay / pump_stop_pump_delay + 2 s)"
    )


def pump_keys_error(group, has_pump, keys):
    if has_pump:
        return None
    used = [key for key in keys if key in PUMP_ONLY_KEYS]
    if not used:
        return None
    return f"group '{group}': {', '.join(used)} need pump_switch_id"


def normalize_restore_mode(mode):
    """Accepts the YAML name or the generated C++ enum text (`switch_::SWITCH_ALWAYS_OFF`)."""
    text = str(mode).rsplit("::", 1)[-1]
    if text.startswith("SWITCH_"):
        text = text[len("SWITCH_") :]
    if text == "RESTORE_DISABLED":
        text = "DISABLED"
    return text


def restore_mode_error(switch_id, role, mode):
    normalized = normalize_restore_mode(mode)
    if normalized in _SAFE_RESTORE_MODES:
        return None
    return (
        f"{role} switch '{switch_id}' has restore_mode {normalized}; an actuator must be OFF after boot "
        "(use ALWAYS_OFF or RESTORE_DEFAULT_OFF)"
    )
