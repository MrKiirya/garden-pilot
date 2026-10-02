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
    "packages/lvgl/page_setup.yaml",
    "packages/lvgl/page_network.yaml",
    "packages/lvgl/dialog_confirm.yaml",
    "packages/lvgl/network_wifi_status.yaml",
    "packages/lvgl/page_boot.yaml",
    "packages/greenhouse/lvgl_valve_test.yaml",
    "packages/lvgl/screensaver.yaml",
    "packages/greenhouse/screensaver_status.yaml",
]
# Built-in sizes of the four base tokens; the `clock` token is the custom font gp_font_clock (screensaver only).
TOKEN_FONTS = {"montserrat_8", "montserrat_10", "montserrat_12", "montserrat_14", "gp_font_clock"}
CLOCK_FONT_FILE = "packages/lvgl/screensaver.yaml"
LVGL_FONT = re.compile(r"\b(?:montserrat_\d+|gp_font_clock)\b")
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


@pytest.mark.parametrize("page", TOKENIZED_PAGES)
def test_page_uses_only_token_fonts(page: str) -> None:
    used = set(LVGL_FONT.findall((REPO_ROOT / page).read_text(encoding="utf-8")))
    assert used <= TOKEN_FONTS, f"{page} uses font sizes outside tokens.json: {sorted(used - TOKEN_FONTS)}"
    if page != CLOCK_FONT_FILE:
        assert "gp_font_clock" not in used, f"{page}: gp_font_clock is for the screensaver only"


def test_clock_token() -> None:
    tokens = json.loads((REPO_ROOT / "design/tokens.json").read_text(encoding="utf-8"))
    styles = {s["name"]: s for g in tokens["type"]["groups"] for s in g["styles"]}
    clock = styles["clock"]
    assert (clock["fontSize"], clock["lineHeight"], clock["fontWeight"]) == ("40px", "44px", 700)
    assert clock["glyphs"] == "0123456789:-"
    assert {"montserrat_" + s["fontSize"].rstrip("px") for n, s in styles.items() if n != "clock"} == {
        f for f in TOKEN_FONTS if f.startswith("montserrat_")
    }
