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
    assert keys[:6] == ["hardware", "core_api", "core_ota", "core_network", "core_time", "core_time_sntp"]
    hardware = config["packages"]["hardware"]
    assert hardware["__tag__"] == "include" and hardware["value"].startswith("hardware/")


@pytest.mark.unit
def test_sim_entry_file_is_a_package_list() -> None:
    config = load_esphome_yaml(REPO_ROOT / "garden-pilot-sim.yaml")
    assert isinstance(config, dict)
    assert set(config) <= {"substitutions", "esphome", "logger", "api", "packages"}
    keys = list(config["packages"])
    assert keys[:6] == ["hardware", "core_api", "core_time_host", "core_diagnostics", "display_sdl", "lvgl_base"]
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


@pytest.mark.config
def test_header_clock_merged() -> None:
    """Every page's `!extend gp_header_clock_update` appends its label update (the lists merge, not replace)."""
    import yaml

    from conftest import _EsphomeLoader

    result = subprocess.run(
        ["sh", "script/config"],
        cwd=REPO_ROOT,
        env={**os.environ, "GP_SECRETS": "example", "GP_VERBOSE": "1"},
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout
    start = out.index("esphome:") if "esphome:" in out else 0
    end = out.index("INFO Configuration is valid!") if "INFO Configuration is valid!" in out else len(out)
    config = yaml.load(out[start:end], Loader=_EsphomeLoader)  # noqa: S506 - SafeLoader subclass
    scripts = [s for s in config["script"] if s["id"] == "gp_header_clock_update"]
    assert len(scripts) == 1

    def updated(node: object) -> list[str]:
        if isinstance(node, dict):
            upd = node.get("lvgl.label.update")
            if isinstance(upd, list):  # the validated config wraps the action in a list
                upd = upd[0] if upd else None
            found = [str(upd["id"][0]["id"] if isinstance(upd["id"], list) else upd["id"])] if isinstance(upd, dict) else []
            return found + [i for v in node.values() for i in updated(v)]
        if isinstance(node, list):
            return [i for v in node for i in updated(v)]
        return []

    assert sorted(updated(scripts[0]["then"])) == [
        "gh_sed_clock_label", "history_clock_label", "home_clock_label", "network_clock_label", "sched_clock_label",
        "setup_clock_label", "valve_test_clock_label",
    ]
