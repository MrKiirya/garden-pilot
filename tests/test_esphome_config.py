"""The device configuration validates with the pinned ESPHome and the example secrets."""

from __future__ import annotations

import os
import subprocess

import pytest

from conftest import REPO_ROOT, load_esphome_yaml, require_sdl_or_skip


@pytest.mark.unit
def test_entry_file_is_a_package_list() -> None:
    config = load_esphome_yaml(REPO_ROOT / "garden-pilot.yaml")
    assert isinstance(config, dict)
    assert set(config) == {"substitutions", "esphome", "logger", "packages"}, "keep the entry file to these sections"
    keys = list(config["packages"])
    assert keys[:5] == ["hardware", "core_api", "core_ota", "core_network", "core_time"]
    hardware = config["packages"]["hardware"]
    assert hardware["__tag__"] == "include" and hardware["value"].startswith("hardware/")


@pytest.mark.unit
def test_sim_entry_file_is_a_package_list() -> None:
    config = load_esphome_yaml(REPO_ROOT / "garden-pilot-sim.yaml")
    assert isinstance(config, dict)
    assert set(config) <= {"substitutions", "esphome", "logger", "api", "packages"}
    keys = list(config["packages"])
    assert keys[:5] == ["hardware", "core_api", "core_time_host", "display_sdl", "lvgl_base"]
    hardware = config["packages"]["hardware"]
    assert hardware["__tag__"] == "include" and hardware["value"] == "hardware/sim.yaml"


@pytest.mark.config
def test_esphome_config_passes_for_the_sim_entry_file() -> None:
    require_sdl_or_skip()
    result = subprocess.run(
        ["sh", "script/config", "garden-pilot-sim.yaml"],
        cwd=REPO_ROOT,
        env={**os.environ, "GP_SECRETS": "example"},
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-4000:]


@pytest.mark.config
def test_esphome_config_passes_with_example_secrets() -> None:
    result = subprocess.run(
        ["sh", "script/config"],
        cwd=REPO_ROOT,
        env={**os.environ, "GP_SECRETS": "example"},
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-4000:]
