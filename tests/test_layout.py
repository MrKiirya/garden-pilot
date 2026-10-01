"""Layout rules: pins and board settings only in hardware/, secrets only in the entry file, core without LVGL."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_ROOT, load_esphome_yaml

pytestmark = pytest.mark.unit

ENTRY = REPO_ROOT / "garden-pilot.yaml"


def tracked_files() -> list[Path]:
    """Tracked plus new (not ignored) files, so the checks also cover a task before its first commit.

    Including untracked files is on purpose: locally this is stricter than CI, which only sees tracked files.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [REPO_ROOT / n for n in sorted(set(out.split("\0"))) if n and (REPO_ROOT / n).is_file()]


def _yaml_files(*folders: str) -> list[Path]:
    roots = [REPO_ROOT / f for f in folders]
    return [p for p in tracked_files() if p.suffix == ".yaml" and any(r in p.parents for r in roots)]


def _strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def _hardware_profiles() -> list[Path]:
    profiles = sorted((REPO_ROOT / "hardware").glob("*.yaml"))
    assert profiles, "no hardware/*.yaml profile found"
    return profiles


def _has_secret_tag(node: object) -> bool:
    if isinstance(node, dict):
        return node.get("__tag__") == "secret" or any(_has_secret_tag(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_secret_tag(v) for v in node)
    return False


def _subst_keys(path: Path) -> set[str]:
    data = load_esphome_yaml(path)
    assert isinstance(data, dict)
    return set(data.get("substitutions") or {})


def _pin_refs() -> set[str]:
    refs: set[str] = set()
    for path in _yaml_files("packages"):
        refs |= set(re.findall(r"\$\{(\w+_pin)\}", _strip_comments(path.read_text(encoding="utf-8"))))
    return refs


def test_pins_only_in_hardware() -> None:
    hardware = REPO_ROOT / "hardware"
    offenders = []
    for path in tracked_files():
        if path.suffix != ".yaml" or hardware in path.parents:
            continue
        if re.search(r"GPIO\d+", _strip_comments(path.read_text(encoding="utf-8"))):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"GPIO literals outside hardware/: {offenders}"


def test_hardware_profiles_shape() -> None:
    profiles = _hardware_profiles()
    for path in profiles:
        data = load_esphome_yaml(path)
        assert isinstance(data, dict)
        assert set(data) <= {"substitutions", "esp32", "psram"}, path.name
        assert "board" in data["esp32"], path.name
        assert data.get("substitutions"), path.name


def test_hardware_profiles_define_every_pin_used() -> None:
    used = _pin_refs()
    assert used
    for path in _hardware_profiles():
        pins = {k for k in _subst_keys(path) if k.endswith("_pin")}
        assert used <= pins, f"{path.name} lacks pins: {sorted(used - pins)}"
        assert pins <= used, f"{path.name} defines unused pins: {sorted(pins - used)}"


def test_hardware_board_settings_are_used() -> None:
    """Non-pin board substitutions (display/touch orientation, calibration) must be referenced by a package."""
    text = "\n".join(_strip_comments(p.read_text(encoding="utf-8")) for p in _yaml_files("packages"))
    for path in _hardware_profiles():
        assert _subst_keys(path), f"{path.name} has no substitutions"
        for key in _subst_keys(path):
            assert f"${{{key}}}" in text, f"{path.name}: {key} is not used under packages/"


def test_no_secret_outside_entry_file() -> None:
    for path in _yaml_files("packages", "hardware"):
        assert "!secret" not in _strip_comments(path.read_text(encoding="utf-8")), path
    entry = load_esphome_yaml(ENTRY)
    assert isinstance(entry, dict)
    for section, value in entry.items():
        if section != "substitutions":
            assert not _has_secret_tag(value), f"!secret outside substitutions in {section}"
    tags = [v.get("__tag__") for v in entry["substitutions"].values() if isinstance(v, dict)]
    assert "secret" in tags, "the entry file should assign secrets to substitutions"


def test_substitutions_resolve() -> None:
    defined: set[str] = set()
    entry = load_esphome_yaml(ENTRY)
    assert isinstance(entry, dict)
    defined |= set(entry.get("substitutions") or {})
    for path in _hardware_profiles():
        defined |= _subst_keys(path)
    package_files = _yaml_files("packages")
    for path in package_files:
        data = load_esphome_yaml(path)
        if isinstance(data, dict):
            defined |= set(data.get("substitutions") or {})
    missing = set()
    for path in package_files:
        for name in re.findall(r"\$\{(\w+)\}", _strip_comments(path.read_text(encoding="utf-8"))):
            if name not in defined:
                missing.add((path.name, name))
    assert not missing, f"undefined substitutions: {sorted(missing)}"


def test_core_is_display_independent() -> None:
    lvgl_ids: set[str] = set()
    for path in _yaml_files("packages/lvgl"):
        lvgl_ids |= set(re.findall(r"\bid:\s*(\w+)", path.read_text(encoding="utf-8")))
    core = _yaml_files("packages/core")
    assert core, "packages/core is empty"
    for path in core:
        text = _strip_comments(path.read_text(encoding="utf-8"))
        assert "lvgl" not in text.lower(), path
        used = {i for i in lvgl_ids if re.search(rf"\b{re.escape(i)}\b", text)}
        assert not used, f"{path} references LVGL ids {sorted(used)}"


def test_gpio_actuators_are_safe() -> None:
    checked = 0
    for path in _yaml_files("packages", "hardware"):
        data = load_esphome_yaml(path)
        if not isinstance(data, dict):
            continue
        for sw in data.get("switch") or []:
            if isinstance(sw, dict) and sw.get("platform") == "gpio":
                checked += 1
                assert sw.get("internal") is True, f"{path.name}: gpio switch must be internal"
                assert sw.get("restore_mode") in {"RESTORE_DEFAULT_OFF", "ALWAYS_OFF"}, path.name
    assert checked, "no gpio switches found"
