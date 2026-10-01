"""Config matrix: entry-file variants built from the real garden-pilot.yaml must pass `esphome config`."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.config

CORE = ["hardware", "core_network", "core_time"]
ALL = None  # keep every package line
# name -> package keys to keep (None = all), or ("without", [keys])
VARIANTS: dict[str, tuple[str, list[str] | None]] = {
    "full": ("keep", ALL),
    "headless": ("keep", CORE),
    "no_touch_debug": ("without", ["touch_dot_test"]),
}

_KEY = re.compile(r"^  ([A-Za-z0-9_]+):")


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


def build_variant(source: str, mode: str, keys: list[str] | None) -> str:
    out: list[str] = []
    in_packages = False
    for line in source.splitlines():
        if re.match(r"^packages:\s*$", line):
            in_packages = True
            out.append(line)
            continue
        if in_packages:
            m = _KEY.match(line)
            if m:
                key = m.group(1)
                if mode == "keep" and keys is not None and key not in keys:
                    continue
                if mode == "without" and keys is not None and key in keys:
                    continue
            elif line.strip() and not line.startswith(" "):
                in_packages = False
            elif line.strip().startswith("#") or not line.strip():
                if mode == "keep" and keys is not None:
                    continue  # drop comments/blank lines of removed blocks
        out.append(line)
    return "\n".join(out) + "\n"


@pytest.mark.parametrize("name", list(VARIANTS))
def test_variant_validates(name: str, tmp_path: Path) -> None:
    mode, keys = VARIANTS[name]
    source = (REPO_ROOT / "garden-pilot.yaml").read_text(encoding="utf-8")
    variant = build_variant(source, mode, keys)
    all_keys = package_keys(source)
    if keys is not None:
        assert set(keys) <= set(all_keys), f"unknown package keys in variant {name}: {set(keys) - set(all_keys)}"
    expected = all_keys if keys is None else (
        [k for k in all_keys if k in keys] if mode == "keep" else [k for k in all_keys if k not in keys]
    )
    assert package_keys(variant) == expected, f"variant {name} has unexpected packages"
    if name != "full":
        assert package_keys(variant) != all_keys, f"variant {name} is identical to the full config"
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
