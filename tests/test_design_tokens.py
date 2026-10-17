"""LVGL pages that follow the design system may only use colours from design/tokens.json."""

from __future__ import annotations

import json
import re

import pytest

from conftest import REPO_ROOT, load_esphome_yaml

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
# Built-in sizes of the type scale C tokens (caption 10, label 12, value 14, value-lg 16, button-md 10, button-sm 8); the `clock` token is the custom font gp_font_clock (screensaver only).
TOKEN_FONTS = {"montserrat_10", "montserrat_12", "montserrat_14", "montserrat_16", "gp_font_clock",
               "gp_font_button_md", "gp_font_button_sm"}
BUTTON_FONTS = {"gp_font_button_md": 10, "gp_font_button_sm": 8}  # custom Bold fonts of the button-md / button-sm tokens
BASE = "packages/lvgl/base.yaml"
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


def _styles() -> dict:
    tokens = json.loads((REPO_ROOT / "design/tokens.json").read_text(encoding="utf-8"))
    return {s["name"]: s for g in tokens["type"]["groups"] for s in g["styles"]}


def test_type_scale_c() -> None:
    styles = _styles()
    got = {n: (styles[n]["fontSize"], styles[n]["lineHeight"], styles[n]["fontWeight"])
           for n in ("caption", "label", "value", "value-lg", "button-md", "button-sm")}
    assert got == {
        "caption": ("10px", "11px", 600),
        "label": ("12px", "13px", 600),
        "value": ("14px", "15px", 700),
        "value-lg": ("16px", "17px", 700),
        "button-md": ("10px", "11px", 700),
        "button-sm": ("8px", "9px", 700),
    }


def test_heat_colours() -> None:
    tokens = json.loads((REPO_ROOT / "design/tokens.json").read_text(encoding="utf-8"))
    colors = {c["name"]: c["value"].lower() for c in tokens["color"]["tokens"]}
    assert (colors["heat"], colors["heat-fill"], colors["on-heat"]) == ("#ff7a59", "#e0582b", "#2b0a00")


def _labels(node, in_button=False):
    """Yield (in_button, props) for every label widget, tracking action-button ancestors.

    A `button` is an action button (label roles button-md / button-sm) when it is at most 32 px tall: 20 px in-card,
    26 px transport, 32 px nav. Taller buttons (the Setup tiles, 52 px) are cards and use the text roles.
    """
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "label" and isinstance(val, dict):
                yield in_button, val
            if isinstance(val, (dict, list)):
                action = key == "button" and isinstance(val, dict) and val.get("height", 0) <= 32
                yield from _labels(val, in_button or action)
    elif isinstance(node, list):
        for v in node:
            yield from _labels(v, in_button)


@pytest.mark.parametrize("page", TOKENIZED_PAGES)
def test_page_font_roles(page: str) -> None:
    data = load_esphome_yaml(REPO_ROOT / page)
    for in_button, props in _labels(data):
        font = props.get("text_font")
        if font is None or font == "gp_font_clock":
            continue
        if font in BUTTON_FONTS:
            assert in_button, f"{page}: {font} is for button labels only ({props.get('text')!r})"
            continue
        size = int(font.removeprefix("montserrat_"))
        text = props.get("text")
        is_symbol = isinstance(text, str) and bool(text) and ord(text[0]) >= 0xE000  # LVGL symbol (\uF...)
        what = props.get("id") or text
        if is_symbol:
            assert size in (12, 14), f"{page}: symbol {what!r} uses {font}"
        elif in_button:
            raise AssertionError(f"{page}: button label {what!r} must use gp_font_button_md / gp_font_button_sm, not {font}")
        else:
            assert size in (10, 12, 14, 16), f"{page}: label {what!r} uses {font}"


def test_clock_token() -> None:
    styles = _styles()
    clock = styles["clock"]
    assert (clock["fontSize"], clock["lineHeight"], clock["fontWeight"]) == ("40px", "44px", 700)
    assert clock["glyphs"] == "0123456789:-"
    custom = {"clock", "button-md", "button-sm"}
    assert {"montserrat_" + s["fontSize"].rstrip("px") for n, s in styles.items() if n not in custom} == {
        f for f in TOKEN_FONTS if f.startswith("montserrat_")
    }
    assert {"montserrat_10", "montserrat_12", "montserrat_14", "montserrat_16"} == {
        f for f in TOKEN_FONTS if f.startswith("montserrat_")
    }


def test_button_fonts_match_tokens() -> None:
    styles = _styles()
    fonts = {f["id"]: f for f in load_esphome_yaml(REPO_ROOT / BASE)["font"]}
    assert set(fonts) == set(BUTTON_FONTS)
    for token, fid in (("button-md", "gp_font_button_md"), ("button-sm", "gp_font_button_sm")):
        font, style = fonts[fid], styles[token]
        assert style["font"] == fid
        assert font["size"] == BUTTON_FONTS[fid] == int(style["fontSize"].rstrip("px"))
        assert font["glyphs"] == style["glyphs"]
        assert font["file"] == "${gp_root}/packages/lvgl/fonts/Montserrat-Bold.ttf"
        assert font.get("bpp", 4) in (2, 4)
        assert len(set(style["glyphs"])) == len(style["glyphs"]) < 60, "keep the baked fonts small"


@pytest.mark.parametrize("page", TOKENIZED_PAGES)
def test_button_glyphs_cover_button_texts(page: str) -> None:
    glyphs = set(_styles()["button-md"]["glyphs"]) & set(_styles()["button-sm"]["glyphs"])
    for in_button, props in _labels(load_esphome_yaml(REPO_ROOT / page)):
        text = props.get("text")
        if in_button and props.get("text_font") in BUTTON_FONTS:
            assert set(text) <= glyphs, f"{page}: {text!r} has glyphs missing from the button fonts"


def test_montserrat_8_is_gone() -> None:
    for path in (REPO_ROOT / "packages").rglob("*.yaml"):
        assert "montserrat_8" not in path.read_text(encoding="utf-8"), path
