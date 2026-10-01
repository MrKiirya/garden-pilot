"""The device configuration validates with the pinned ESPHome and the example secrets."""

from __future__ import annotations

import os
import subprocess

import pytest

from conftest import REPO_ROOT, load_esphome_yaml

pytestmark = pytest.mark.config


def test_entry_file_is_a_package_list() -> None:
    config = load_esphome_yaml(REPO_ROOT / "garden-pilot.yaml")
    assert isinstance(config, dict)
    assert set(config) == {"esphome", "esp32", "logger", "packages"}, "keep the entry file to these sections"


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
