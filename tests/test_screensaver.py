"""Screensaver (task 011): the 40 px clock font, the idle trigger and its guards, the entry-file wiring."""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from conftest import REPO_ROOT, load_esphome_yaml
from test_layout import _package_files, _strip_comments, _yaml_files
from test_screens import _by_id, _load, _walk, _widgets

pytestmark = pytest.mark.unit

SAVER = "packages/lvgl/screensaver.yaml"
STATUS = "packages/greenhouse/screensaver_status.yaml"
FONT_DIR = REPO_ROOT / "packages/lvgl/fonts"
ENTRIES = ["garden-pilot.yaml", "garden-pilot-sim.yaml"]


def _clock_token() -> dict:
    tokens = json.loads((REPO_ROOT / "design/tokens.json").read_text(encoding="utf-8"))
    styles = [s for g in tokens["type"]["groups"] for s in g["styles"]]
    return next(s for s in styles if s["name"] == "clock")


def test_font_matches_token() -> None:
    token = _clock_token()
    fonts = _load(SAVER)["font"]
    assert [f["id"] for f in fonts] == ["gp_font_clock"]
    font = fonts[0]
    assert font["size"] == int(token["fontSize"].rstrip("px")) == 40
    assert font["glyphs"] == token["glyphs"]
    path = REPO_ROOT / font["file"]
    assert path.is_file() and path.parent == FONT_DIR
    assert (FONT_DIR / "OFL.txt").is_file()
    header = (REPO_ROOT / SAVER).read_text(encoding="utf-8")
    assert hashlib.sha256(path.read_bytes()).hexdigest() in header, "the TTF checksum must be in the header comment"
    for yaml_path in _yaml_files("packages"):
        if yaml_path != REPO_ROOT / SAVER:
            data = load_esphome_yaml(yaml_path)
            assert not (isinstance(data, dict) and "font" in data), f"only the screensaver may declare a font: {yaml_path}"
    for yaml_path in _yaml_files("packages"):
        if yaml_path != REPO_ROOT / SAVER:
            assert "gp_font_clock" not in yaml_path.read_text(encoding="utf-8")


def test_idle_guards() -> None:
    data = _load(SAVER)
    assert set(data) <= {"substitutions", "font", "lvgl", "script", "interval"}
    assert data["substitutions"]["screensaver_timeout"] == "5min"
    idle = data["lvgl"]["on_idle"]
    assert len(idle) == 1 and idle[0]["timeout"] == "${screensaver_timeout}"
    guard = idle[0]["then"][0]["if"]
    parts = guard["condition"]["and"]
    assert len(parts) == 4
    positives = [p for p in parts if "lambda" in p]
    negatives = [p["not"] for p in parts if "not" in p]
    assert len(positives) == 1 and "gp_boot_done" in positives[0]["lambda"] and "!" not in positives[0]["lambda"]
    assert len(negatives) == 3
    neg_text = [str(n) for n in negatives]
    for needed in ("gp_confirm_open", "gp_service_mode", "boot_page"):
        assert sum(needed in t for t in neg_text) == 1, needed
    assert "lvgl.page.is_showing" in str(negatives) and not any("or" in n for n in negatives if isinstance(n, dict) and "or" in n)
    steps = guard["then"]
    names = [next(iter(d)) for d in steps]
    assert "script.execute" in names and steps[0] == {"script.execute": "gp_screensaver_update_clock"}
    fg = [i for i, d in enumerate(steps) if "lv_obj_move_foreground(id(gp_screensaver_layer))" in str(d.get("lambda", ""))]
    show = [i for i, d in enumerate(steps) if d.get("lvgl.widget.show") == "gp_screensaver_layer"]
    assert fg and show and fg[0] < show[0], "the overlay must move to the foreground before it is shown"
    clock = {s["id"]: s for s in data["script"]}["gp_screensaver_update_clock"]
    cond = clock["then"][0]["if"]
    assert "ha_time).now().is_valid()" in cond["condition"]["lambda"]
    assert cond["else"][0]["lvgl.label.update"]["text"] == "--:--"
    assert {"script.execute": "gp_screensaver_update_clock"} in data["interval"][0]["then"]
    root = data["lvgl"]["top_layer"]["widgets"][0]["obj"]
    assert root["id"] == "gp_screensaver_layer"
    assert root["hidden"] is True
    assert (root["x"], root["y"], root["width"], root["height"]) == (0, 0, 320, 240)
    assert {"lvgl.widget.hide": "gp_screensaver_layer"} in root["on_press"]
    for wid in ("gp_screensaver_clock", "gp_screensaver_status", "gp_screensaver_bed_dot", "gp_screensaver_bed_label"):
        _by_id(data["lvgl"], wid)
    assert _by_id(data["lvgl"], "gp_screensaver_clock")["text_font"] == "gp_font_clock"
    text = _strip_comments((REPO_ROOT / SAVER).read_text(encoding="utf-8"))
    assert not re.search(r"lvgl\.page\.show|sprinkler\.|switch\.|board_relay|valve", text.replace("valve test", ""))


def test_status_package() -> None:
    data = _load(STATUS)
    assert set(data) <= {"interval"}
    text = _strip_comments((REPO_ROOT / STATUS).read_text(encoding="utf-8"))
    assert "gp_screensaver_status" in text and "gh_air_temperature" in text and "gh_soil_moisture_pct" in text
    assert not re.search(r"sprinkler\.(?!\s*$)\w+:|switch\.", text), "reads only, never acts"


@pytest.mark.parametrize("entry", ENTRIES)
def test_entry_files(entry: str) -> None:
    data = load_esphome_yaml(REPO_ROOT / entry)
    assert isinstance(data, dict)
    keys = list(data["packages"])
    files = _package_files(data)
    assert files["lvgl_screensaver"] == SAVER and files["gh_screensaver_status"] == STATUS
    assert keys.index("lvgl_dialog_confirm") < keys.index("lvgl_screensaver")
    assert keys.index("gh_sprinkler_lvgl") < keys.index("gh_screensaver_status")
    subs = data["substitutions"]
    if entry == "garden-pilot.yaml":
        assert "screensaver_timeout" not in subs
    else:
        assert subs["screensaver_timeout"] == "1min"
    default = _load(SAVER)["substitutions"]["screensaver_timeout"]
    assert int(default.removesuffix("min")) >= 1


def test_screensaver_text_is_ascii_and_clock_in_glyph_set() -> None:
    data = _load(SAVER)
    glyphs = set(_clock_token()["glyphs"])
    clock = _by_id(data["lvgl"], "gp_screensaver_clock")
    assert set(clock["text"]) <= glyphs
    for rel in (SAVER, STATUS):
        for d in _walk(_load(rel)):
            val = d.get("text")
            if isinstance(val, str):
                assert val.isascii(), (rel, val)
        assert _strip_comments((REPO_ROOT / rel).read_text(encoding="utf-8")).isascii(), rel
    assert any(p.get("text") == "Touch to wake" for _t, p in _widgets(data["lvgl"]))


def test_no_font_download_urls() -> None:
    for path in _yaml_files("packages"):
        text = path.read_text(encoding="utf-8")
        assert "gfonts://" not in text and not re.search(r"https://.*\.ttf", text), path


def test_screensaver_is_the_top_layer_foreground_in_the_emulator() -> None:
    """The SIM button and the confirm layer share the top layer; the overlay must be moved above them when shown."""
    sim_files = _package_files(load_esphome_yaml(REPO_ROOT / "garden-pilot-sim.yaml")).values()
    other = [f for f in sim_files if isinstance(_load(f).get("lvgl", {}), dict) and (_load(f).get("lvgl") or {}).get("top_layer")
             and f != SAVER]
    assert "packages/sim/page_board.yaml" in other, "the SIM button is a top-layer widget that could cover the overlay"
    text = _strip_comments((REPO_ROOT / SAVER).read_text(encoding="utf-8"))
    assert text.index("lv_obj_move_foreground(id(gp_screensaver_layer))") < text.index("lvgl.widget.show: gp_screensaver_layer")
