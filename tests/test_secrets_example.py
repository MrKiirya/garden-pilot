"""secrets.example.yaml must cover every !secret and hold only obvious placeholders."""

from __future__ import annotations

import base64
import re

import pytest
import yaml

from conftest import REPO_ROOT

pytestmark = pytest.mark.unit

SECRET_REF = re.compile(r"!secret\s+([A-Za-z0-9_]+)")
EXAMPLE_API_KEY_TEXT = b"garden-pilot-example-key-dummy!!"
EXAMPLE_SIM_KEY_TEXT = b"garden-pilot-sim-public-dummy!!!"


def _secret_refs() -> set[str]:
    refs: set[str] = set()
    for path in REPO_ROOT.glob("**/*.yaml"):
        if any(part in {".venv", ".esphome"} for part in path.parts) or path.name.startswith("secrets"):
            continue
        refs |= set(SECRET_REF.findall(path.read_text(encoding="utf-8")))
    return refs


def _example() -> dict[str, str]:
    return yaml.safe_load((REPO_ROOT / "secrets.example.yaml").read_text(encoding="utf-8"))


def test_every_secret_reference_has_an_example() -> None:
    missing = _secret_refs() - set(_example())
    assert not missing, f"add these keys to secrets.example.yaml: {sorted(missing)}"


def test_example_has_no_unused_keys() -> None:
    unused = set(_example()) - _secret_refs()
    assert not unused, f"secrets.example.yaml keys not referenced by any !secret: {sorted(unused)}"


@pytest.mark.parametrize("key", sorted(_example()))
def test_example_values_are_obvious_placeholders(key: str) -> None:
    value = _example()[key]
    if key == "sim_api_encryption_key":
        assert base64.b64decode(value, validate=True) == EXAMPLE_SIM_KEY_TEXT
    elif key == "api_encryption_key":
        # ESPHome rejects an all-zeros key, so the placeholder is readable text instead.
        assert base64.b64decode(value) == EXAMPLE_API_KEY_TEXT
    else:
        assert set(value) == {"0"}, f"{key} must be a zero-only placeholder"


def test_sim_api_key_is_valid_and_distinct() -> None:
    example = _example()
    raw = base64.b64decode(example["sim_api_encryption_key"], validate=True)
    assert len(raw) == 32
    assert example["sim_api_encryption_key"] != example["api_encryption_key"]
    assert raw != b"\0" * 32, "ESPHome rejects an all-zeros key"


def test_real_secrets_file_is_not_tracked() -> None:
    from conftest import tracked_files

    tracked = [p for p in tracked_files() if p.name == "secrets.yaml"]
    assert not tracked, f"secrets.yaml must never be committed: {tracked}"
