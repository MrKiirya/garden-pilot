"""Config matrix: entry-file variants built from the real garden-pilot.yaml must pass `esphome config`."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from conftest import REPO_ROOT, require_sdl_or_skip

pytestmark = pytest.mark.config

CORE = ["hardware", "core_api", "core_ota", "core_network", "core_time", "core_time_sntp"]
# the gp_* layer: bed.yaml adds gp_zone switches, so every row with beds carries the gp packages (HA actions need core_api)
GP = ["core_gp", "gh_gp"]
GP_API = ["core_gp", "core_gp_api", "gh_gp"]
BEDS_2 = [*CORE, "gh_irrigation", "gh_bed_1", "gh_bed_2", *GP_API]
SIM_BEDS_3 = ["hardware", "gh_irrigation", "gh_bed_1", "gh_bed_2", "gh_bed_3", *GP]
SIM_BEDS_2 = ["hardware", "gh_irrigation", "gh_bed_1", "gh_bed_2", *GP]
SCHEDULE = ["gh_schedule", "gh_schedule_slot_1", "gh_schedule_slot_2"]
SIM = "hardware/sim.yaml"
SIM_ENTRY = "garden-pilot-sim.yaml"
SIM_API_ONLY = [
    "hardware", "core_api", "core_time_host", "gh_irrigation", "gh_bed_1", "sim_bed_1_soil", "gh_bed_2",
    "sim_bed_2_soil", "gh_bed_3", "sim_bed_3_soil", *GP_API, "sim_sensors", "sim_drift",
]


@dataclass(frozen=True)
class Variant:
    mode: str  # "keep" (only `keys`, None = all) or "without" (all but `keys`)
    keys: list[str] | None = None
    hardware: str | None = None  # replacement path of the `hardware` include
    enable: tuple[str, ...] = ()  # commented-out example blocks to uncomment first
    source: str = "garden-pilot.yaml"  # entry file the variant is built from
    subst: tuple[str, ...] = ()  # `-s KEY VALUE` command-line substitutions (flat: key, value, key, value, ...)
    edits: tuple[tuple[str, str], ...] = ()  # (old, new) text replacements in the built entry file
    adds: tuple[str, ...] = ()  # package keys that `edits` add to the entry file (appended to the expected keys)
    fails_with: tuple[str, ...] = ()  # expected failure: `esphome config` must fail and print all of these



CORE_GP_LINE = "  core_gp: !include packages/core/gp.yaml\n"
BEDS_456 = "".join(
    f"  gh_bed_{n}: !include\n    file: packages/greenhouse/bed.yaml\n"
    f'    vars: {{bed: "{n}", bed_name: "Greenhouse bed {n}", relay: "{n}"}}\n'
    for n in (4, 5, 6)
)

VARIANTS: dict[str, Variant] = {
    "full": Variant("keep"),
    "headless": Variant("keep", CORE),
    "no_sntp": Variant("without", ["core_time_sntp"]),
    "headless_sntp_only": Variant("keep", ["hardware", "core_api", "core_ota", "core_network", "core_time_sntp"]),
    "no_touch_debug": Variant("without", ["touch_dot_test"]),
    "no_wifi_status": Variant("without", ["lvgl_network_wifi"]),
    "no_boot_wifi": Variant("without", ["lvgl_boot_wifi"]),
    "no_screensaver": Variant("without", ["lvgl_screensaver", "gh_screensaver_status"]),
    "headless_diag": Variant("keep", [*CORE, "core_diagnostics"]),
    "beds_2_headless": Variant("keep", BEDS_2),
    "bed_soil_headless": Variant(
        "keep",
        [*CORE, "gh_irrigation", "gh_bed_1", "gh_bed_1_soil", "gh_bed_2", "gh_bed_3", *GP_API],
        enable=("gh_bed_1_soil",),
    ),
    "beds_1_headless": Variant("keep", [*CORE, "gh_irrigation", "gh_bed_1", *GP_API]),
    # the gp layer without the Home Assistant actions (no API needed) and the gp error cases
    "gp_headless": Variant("keep", [*CORE, "gh_irrigation", "gh_bed_1", *GP]),
    "gp_unknown_engine_group": Variant("keep", [*CORE, *GP_API], fails_with=("gh_zones",)),
    # bed 4 as the third bed: position 4 does not fit a 3-zone group
    "gp_zone_position_out_of_range": Variant(
        "keep", [*CORE, "gh_irrigation", "gh_bed_1", "gh_bed_2", "gh_bed_3", *GP_API],
        edits=(('vars: {bed: "3", bed_name: "Greenhouse bed 3", relay: "3"}',
                'vars: {bed: "4", bed_name: "Greenhouse bed 3", relay: "3"}'),),
        fails_with=("gp_zone positions", "1..3"),
    ),
    # parallel greenhouse: every bed on its own lane (-s overrides the package default substitution)
    "beds_3_parallel_headless": Variant(
        "keep", [*CORE, "gh_irrigation", "gh_bed_1", "gh_bed_2", "gh_bed_3", *GP_API], subst=("gh_max_parallel", "all")
    ),
    # a watchdog limit below the bed run-duration max (55 min) must be rejected at config time
    "max_on_time_too_short": Variant(
        "keep", [*CORE, "gh_irrigation", "gh_bed_1", "gh_bed_2", *GP_API], subst=("gh_max_on_time", "30min"),
        fails_with=("max_value", "max_on_time"),
    ),
    # `never` disables the watchdog limit on purpose (human decision): it must stay valid
    "max_on_time_never": Variant(
        "keep", [*CORE, "gh_irrigation", "gh_bed_1", "gh_bed_2", *GP_API], subst=("gh_max_on_time", "never"),
    ),
    # schedules (task 019): headless (no LVGL: the skip condition is gp.inhibited), hub without slots, bad slot number,
    # catch-up window limits
    "schedule_headless": Variant("keep", [*BEDS_2, *SCHEDULE]),
    "schedule_no_slots": Variant("keep", [*BEDS_2, "gh_schedule"]),
    "schedule_window_zero": Variant("keep", [*BEDS_2, *SCHEDULE], subst=("gh_schedule_catch_up_window", "0s")),
    "schedule_window_too_long": Variant(
        "keep", [*BEDS_2, *SCHEDULE], subst=("gh_schedule_catch_up_window", "7h"), fails_with=("6 hours",)
    ),
    "schedule_bad_slot": Variant(
        "keep", [*BEDS_2, *SCHEDULE],
        edits=(('vars: {slot: "2", start: "07:00:00"}', 'vars: {slot: "9", start: "07:00:00"}'),),
        fails_with=("slot", "8"),
    ),
    # one bed with the whole LVGL UI: the Greenhouse page with a single full-width card, slots 2-6 hidden (task 025)
    "beds_1_lvgl": Variant("without", ["gh_bed_2", "gh_bed_3"]),
    "sim_beds_3": Variant("keep", SIM_BEDS_3, hardware=SIM),
    "sim_beds_1": Variant("keep", ["hardware", "gh_irrigation", "gh_bed_1", *GP], hardware=SIM),
    "sim_beds_2": Variant("keep", SIM_BEDS_2, hardware=SIM),
    # PC emulator entry file (host + SDL); the first two need SDL2 dev files, sim_api_only does not.
    "sim_full": Variant("keep", source=SIM_ENTRY),
    # six beds on relays 1..6 of the 12-relay profile: the compact card grid (layout coverage, task 025)
    "beds_6_lvgl": Variant(
        "keep", adds=("gh_bed_4", "gh_bed_5", "gh_bed_6"), edits=((CORE_GP_LINE, BEDS_456 + CORE_GP_LINE),)
    ),
    "sim_no_touch_debug": Variant("without", ["touch_dot_test"], source=SIM_ENTRY),
    "sim_no_board_page": Variant("without", ["sim_sensors_lvgl", "sim_page_board"], source=SIM_ENTRY),
    "sim_api_only": Variant("keep", SIM_API_ONLY, source=SIM_ENTRY),
    "sim_schedule_api_only": Variant("keep", [*SIM_API_ONLY, *SCHEDULE], source=SIM_ENTRY),
}

_KEY = re.compile(r"^  ([A-Za-z0-9_]+):")
_EXAMPLE_START = re.compile(r"^  # ([A-Za-z0-9_]+): !include\s*$")
_EXAMPLE_CONT = re.compile(r"^  #   ")
_HARDWARE = re.compile(r"^(  hardware: !include\s+)\S+(.*)$")


def package_keys(text: str) -> list[str]:
    keys: list[str] = []
    in_packages = False
    for line in text.splitlines():
        if re.match(r"^packages:\s*$", line):
            in_packages = True
        elif in_packages:
            m = _KEY.match(line)
            if m:
                keys.append(m.group(1))
    return keys


def uncomment_examples(source: str, enable: tuple[str, ...]) -> str:
    """Uncomment the example blocks named in `enable` (`  # key: !include` + `  #   ...` lines)."""
    out: list[str] = []
    active = False
    for line in source.splitlines():
        m = _EXAMPLE_START.match(line)
        if m:
            active = m.group(1) in enable
        elif not _EXAMPLE_CONT.match(line):
            active = False
        out.append(line[:2] + line[4:] if active else line)
    return "\n".join(out) + "\n"


def build_variant(
    source: str,
    mode: str,
    keys: list[str] | None = None,
    hardware: str | None = None,
    enable: tuple[str, ...] = (),
) -> str:
    """Build an entry-file variant line by line; a package entry is its key line plus indented continuations."""
    out: list[str] = []
    in_packages = False
    skipping = False
    for line in uncomment_examples(source, enable).splitlines():
        if re.match(r"^packages:\s*$", line):
            in_packages = True
            out.append(line)
            continue
        if in_packages:
            m = _KEY.match(line)
            if m:
                key = m.group(1)
                drop = (mode == "keep" and keys is not None and key not in keys) or (
                    mode == "without" and keys is not None and key in keys
                )
                skipping = drop
                if drop:
                    continue
                h = _HARDWARE.match(line)
                if hardware and h:
                    line = f"{h.group(1)}{hardware}{h.group(2)}"
            elif line.strip() and not line.startswith(" "):
                in_packages = False
                skipping = False
            elif skipping and line.startswith("    ") and not line.strip().startswith("#"):
                continue  # continuation (vars: ...) of a dropped block
            elif line.strip().startswith("#") or not line.strip():
                skipping = False
                if mode == "keep" and keys is not None:
                    continue  # drop comments/blank lines of removed blocks
        out.append(line)
    return "\n".join(out) + "\n"


SAMPLE = """\
packages:
  hardware: !include hardware/a.yaml
  # A comment.
  one: !include
    file: packages/one.yaml
    vars: {x: "1"}
  # Optional example.
  # ex: !include
  #   file: packages/ex.yaml
  #   vars: {y: "2"}
  two: !include packages/two.yaml
"""


@pytest.mark.unit
def test_builder_blocks() -> None:
    dropped = build_variant(SAMPLE, "without", ["one"])
    assert "packages/one.yaml" not in dropped and "vars: {x" not in dropped
    assert package_keys(dropped) == ["hardware", "two"]
    kept = build_variant(SAMPLE, "keep", ["hardware", "one"])
    assert "file: packages/one.yaml" in kept and 'vars: {x: "1"}' in kept
    assert package_keys(kept) == ["hardware", "one"]
    assert "ex" not in package_keys(build_variant(SAMPLE, "keep"))
    enabled = build_variant(SAMPLE, "keep", None, enable=("ex",))
    assert package_keys(enabled) == ["hardware", "one", "ex", "two"]
    assert '    file: packages/ex.yaml\n    vars: {y: "2"}\n' in enabled
    assert yaml.safe_load(enabled.replace("!include", ""))["packages"]["ex"]["vars"] == {"y": "2"}
    hw = build_variant(SAMPLE, "keep", None, hardware="hardware/sim.yaml")
    assert "  hardware: !include hardware/sim.yaml\n" in hw
    assert hw.replace("hardware/sim.yaml", "hardware/a.yaml") == SAMPLE


def _with_adds(expected: list[str], adds: tuple[str, ...]) -> list[str]:
    """`adds` are inserted in front of core_gp (the order of the edit)."""
    at = expected.index("core_gp")
    return [*expected[:at], *adds, *expected[at:]]


@pytest.mark.parametrize("name", list(VARIANTS))
def test_variant_validates(name: str, tmp_path: Path) -> None:
    v = VARIANTS[name]
    source = (REPO_ROOT / v.source).read_text(encoding="utf-8")
    variant = build_variant(source, v.mode, v.keys, v.hardware, v.enable)
    for old, new in v.edits:
        assert old in variant, f"variant {name}: {old!r} not found"
        variant = variant.replace(old, new)
    all_keys = package_keys(uncomment_examples(source, v.enable))
    if v.keys is not None:
        assert set(v.keys) <= set(all_keys), f"unknown package keys in variant {name}: {set(v.keys) - set(all_keys)}"
    expected = all_keys if v.keys is None else (
        [k for k in all_keys if k in v.keys] if v.mode == "keep" else [k for k in all_keys if k not in v.keys]
    )
    expected = _with_adds(expected, v.adds) if v.adds else expected
    assert package_keys(variant) == expected, f"variant {name} has unexpected packages"
    if name not in ("full", "sim_full"):
        assert package_keys(variant) != all_keys, f"variant {name} is identical to the full config"
    if v.hardware:
        assert f"hardware: !include {v.hardware}" in variant
    if "display_sdl" in package_keys(variant):
        require_sdl_or_skip()
    (tmp_path / v.source).write_text(variant, encoding="utf-8")
    for folder in ("packages", "hardware", "components"):
        if (REPO_ROOT / folder).exists():
            shutil.copytree(REPO_ROOT / folder, tmp_path / folder)
    shutil.copy(REPO_ROOT / "secrets.example.yaml", tmp_path / "secrets.yaml")
    args = [a for i in range(0, len(v.subst), 2) for a in ("-s", v.subst[i], v.subst[i + 1])]
    result = subprocess.run(
        ["sh", str(REPO_ROOT / "script" / "_esphome"), *args, "config", str(tmp_path / v.source)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = result.stdout + result.stderr
    if v.fails_with:
        assert result.returncode != 0, f"variant {name} must fail validation"
        for text in v.fails_with:
            assert text in output, f"variant {name}: {text!r} not in the error output:\n{output[-3000:]}"
        return
    assert result.returncode == 0, output[-4000:]


def test_sntp_servers_override(tmp_path: Path) -> None:
    source = (REPO_ROOT / "garden-pilot.yaml").read_text(encoding="utf-8")
    variant = build_variant(source, "keep", CORE)
    assert "\nsubstitutions:\n" in variant
    variant = variant.replace("\nsubstitutions:\n", "\nsubstitutions:\n  sntp_server_1: ntp.example.lan\n", 1)
    (tmp_path / "garden-pilot.yaml").write_text(variant, encoding="utf-8")
    for folder in ("packages", "hardware", "components"):
        if (REPO_ROOT / folder).exists():
            shutil.copytree(REPO_ROOT / folder, tmp_path / folder)
    shutil.copy(REPO_ROOT / "secrets.example.yaml", tmp_path / "secrets.yaml")
    result = subprocess.run(
        ["sh", str(REPO_ROOT / "script" / "_esphome"), "config", str(tmp_path / "garden-pilot.yaml")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    assert "ntp.example.lan" in result.stdout
    assert "0.pool.ntp.org" not in result.stdout
    assert "1.pool.ntp.org" in result.stdout


def _config_with_substitution(tmp_path: Path, line: str | None) -> str:
    source = (REPO_ROOT / "garden-pilot.yaml").read_text(encoding="utf-8")
    variant = build_variant(source, "keep", CORE)
    if line:
        assert "\nsubstitutions:\n" in variant
        variant = variant.replace("\nsubstitutions:\n", f"\nsubstitutions:\n  {line}\n", 1)
    (tmp_path / "garden-pilot.yaml").write_text(variant, encoding="utf-8")
    for folder in ("packages", "hardware", "components"):
        if (REPO_ROOT / folder).exists():
            shutil.copytree(REPO_ROOT / folder, tmp_path / folder)
    shutil.copy(REPO_ROOT / "secrets.example.yaml", tmp_path / "secrets.yaml")
    result = subprocess.run(
        ["sh", str(REPO_ROOT / "script" / "_esphome"), "config", str(tmp_path / "garden-pilot.yaml")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    return result.stdout


# `esphome config` shows the zone normalized to a POSIX string (UTC -> UTC0, Europe/Moscow -> MSK-3).
def test_timezone_default_is_utc_on_both_sources(tmp_path: Path) -> None:
    out = _config_with_substitution(tmp_path, None)
    assert out.count("    timezone: UTC0") == 2, out


def test_timezone_override(tmp_path: Path) -> None:
    out = _config_with_substitution(tmp_path, "timezone: Europe/Moscow")
    assert out.count("    timezone: MSK-3") == 2, out
    assert "timezone: UTC0" not in out
