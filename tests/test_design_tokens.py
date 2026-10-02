"""LVGL pages that follow the design system may only use colours from design/tokens.json."""

from __future__ import annotations

import json
import re

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.unit

# Pages already rebuilt on the design system. Add a page here when it is migrated (SPEC §8).
TOKENIZED_PAGES = [
    "packages/lvgl/page_home.yaml",
    "packages/sim/page_board.yaml",
    "packages/sim/sensors_lvgl.yaml",
]
LVGL_COLOR = re.compile(r"\b0x([0-9a-fA-F]{6})\b")


def _token_colors() -> set[str]:
    tokens = json.loads((REPO_ROOT / "design/tokens.json").read_text(encoding="utf-8"))
    return {entry["value"].lower().lstrip("#") for entry in tokens["color"]["tokens"]}


def test_tokens_file_has_the_device_palette() -> None:
    assert {"131313", "1c1b1b", "78dc77", "4caf50", "93000a"} <= _token_colors()


@pytest.mark.parametrize("page", TOKENIZED_PAGES)
def test_page_uses_only_token_colors(page: str) -> None:
    used = {c.lower() for c in LVGL_COLOR.findall((REPO_ROOT / page).read_text(encoding="utf-8"))}
    unknown = used - _token_colors()
    assert not unknown, f"{page} uses colours outside design/tokens.json: {sorted(unknown)}"
