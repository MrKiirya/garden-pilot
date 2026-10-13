"""Task 025 part A: the Greenhouse page (bed cards, detail page, transport row) and its gp data. YAML shape checks; the
pure parts are in tests/cpp/test_gp_screens.cpp."""

from __future__ import annotations

import json
import re

import pytest

from conftest import REPO_ROOT, load_esphome_yaml
from test_gp_layer import _lambdas
from test_layout import _strip_comments
from test_screens import (
    GH_PAGE,
    HOME,
    SETUP,
    _assert_guarded_confirm,
    _by_id,
    _load,
    _page,
    _show_targets,
    _walk,
    _widgets,
)

pytestmark = pytest.mark.unit

CARD = "packages/lvgl/card_bed.yaml"
REFRESH = "packages/lvgl/card_bed_refresh.yaml"
STATUS = "packages/greenhouse/gp_lvgl_status.yaml"
FORMAT_SCREENS = REPO_ROOT / "components" / "gp" / "format_screens.h"
NAV_TARGETS = {"dash": "home_page", "zones": "greenhouse_page", "water": "lawn_page", "setup": "setup_page"}
GREEN_FILL = 0x4CAF50


def _text(rel: str) -> str:
    return _strip_comments((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _includes(node: object, file_suffix: str) -> list[dict]:
    """Every `!include {file, vars}` of the given file inside a structure."""
    found = []
    for d in _walk(node):
        if d.get("__tag__") == "include" and isinstance(d["value"], dict) and str(d["value"].get("file", "")).endswith(file_suffix):
            found.append(d["value"])
    return found


def _color(props: dict) -> int | None:
    value = props.get("bg_color")
    return value if isinstance(value, int) else None


# ---------------------------------------------------------------------------------------------------------- the card


def test_card_template_shape() -> None:
    data = _load(CARD)
    assert list(data) == ["obj"], "the template is one root widget"
    root = data["obj"]
    assert root["id"] == "${p}_card${slot}"
    assert root["hidden"] is True
    ids = [p["id"] for _t, p in _widgets({"widgets": [data]}) if isinstance(p.get("id"), str)]
    assert len(ids) >= 9 and all(i.startswith("${p}_card${slot}_") for i in ids if i != root["id"]), ids
    for part in ("edge", "name", "state", "time", "bar", "last", "soil", "run", "queue"):
        assert f"${{p}}_card${{slot}}_{part}" in ids, part
    text = _text(CARD)
    assert not re.search(r"gh_bed|gh_zones|garden_zones|board_relay|sprinkler|gp_greenhouse", text)
    run = _by_id({"widgets": [data]}, "${p}_card${slot}_run")
    assert run["on_click"] == [{"gp.run_zone": {"id": "${group}", "zone": {"__tag__": "lambda", "value": "return ${zone};"}}}]
    queue = _by_id({"widgets": [data]}, "${p}_card${slot}_queue")
    assert list(queue["on_click"][0]) == ["gp.enqueue_zone"]
    assert queue["on_click"][0]["gp.enqueue_zone"]["id"] == "${group}"
    for button in (run, queue):
        assert button["height"] >= 20, "in-card buttons are btn-h-sm (20 px)"
    # a compact card opens the detail page, a full one does nothing
    click = root["on_click"][0]["if"]
    assert "compact" in click["condition"]["lambda"]
    assert {"lvgl.page.show": "${detail_page}"} in click["then"]


def test_card_refresh_uses_card_ids_and_one_line_lambdas() -> None:
    refresh = _load(REFRESH)
    assert refresh["id"] == "${p}_card${slot}_update"
    assert refresh["parameters"] == {"layout": "bool"}
    card_ids = {p["id"] for _t, p in _widgets({"widgets": [_load(CARD)]}) if isinstance(p.get("id"), str)}
    card_ids.add(_load(CARD)["obj"]["id"])
    used = set(re.findall(r"\$\{p\}_card\$\{slot\}(?:_\w+)?", _text(REFRESH)))
    assert used <= card_ids | {"${p}_card${slot}_update"}, used - card_ids
    for lam in _lambdas(refresh):
        assert len([ln for ln in lam.splitlines() if ln.strip()]) == 1, lam
    text = _text(REFRESH)
    assert not re.search(r"gh_bed|gh_zones|garden_zones|board_relay|sprinkler|gp_greenhouse", text)
    # only gp_* access: the group var and the pure helpers
    assert set(re.findall(r"id\((\S+?)\)", text)) == {"${group}"}


# ----------------------------------------------------------------------------------------------- the greenhouse page


def test_greenhouse_page_cards() -> None:
    data = _load(GH_PAGE)
    cards = _includes(data, "card_bed.yaml")
    assert len(cards) == 7
    grid = [c for c in cards if c["vars"]["slot"] != "detail"]
    assert [c["vars"]["slot"] for c in grid] == ["1", "2", "3", "4", "5", "6"]
    for i, c in enumerate(grid):
        v = c["vars"]
        assert v["zone"] == str(i) and v["idx"] == str(i) and v["group"] == "gp_greenhouse" and v["p"] == "gh"
        assert v["count"] == "id(gp_greenhouse)->summary().zone_count"
    detail, = [c for c in cards if c["vars"]["slot"] == "detail"]
    assert detail["vars"]["zone"] == "id(gh_detail_zone)" and detail["vars"]["count"] == "1"
    page_ids = {p["id"] for p in data["lvgl"]["pages"]}
    assert page_ids == {"greenhouse_page", "gh_bed_detail_page"}
    detail_page = _page(GH_PAGE, "gh_bed_detail_page")
    assert len(_includes(detail_page, "card_bed.yaml")) == 1
    assert len(_includes(_page(GH_PAGE, "greenhouse_page"), "card_bed.yaml")) == 6
    for c in cards:
        assert c["vars"]["detail_page"] == "gh_bed_detail_page" and c["vars"]["detail_zone"] == "gh_detail_zone"
    globs = {g["id"]: g for g in data["globals"]}
    assert globs["gh_detail_zone"]["restore_value"] is False
    # the stats strip keeps the ids the sensor packages write
    page = _page(GH_PAGE, "greenhouse_page")
    for wid in ("gh_greenhouse_t_label", "gh_greenhouse_rh_label", "gh_greenhouse_soil_hint"):
        _by_id(page, wid)
    assert "gh_bed" not in _text(GH_PAGE).replace("gh_bed_detail_page", "")


def test_card_scripts_match_the_includes() -> None:
    """The poller includes the refresh script once per card of the page, with the same vars, and runs every one."""
    status = _load(STATUS)
    refreshes = _includes(status, "card_bed_refresh.yaml")
    cards = _includes(_load(GH_PAGE), "card_bed.yaml")
    assert len(refreshes) == len(cards) == 7
    for r, c in zip(refreshes, cards):
        for key in ("p", "group", "slot", "count", "idx", "zone"):
            assert r["vars"][key] == c["vars"][key], (key, r["vars"], c["vars"])
        assert c["vars"]["detail_update"] == f"{c['vars']['p']}_card{'detail'}_update"
    executed = {d["script.execute"]["id"]: d["script.execute"] for d in _walk(status) if isinstance(d.get("script.execute"), dict)}
    expected = {f"gh_card{c['vars']['slot']}_update" for c in cards}
    assert set(executed) == expected
    # both branches (layout once, then fill only)
    runs = [d["script.execute"]["layout"] for d in _walk(status) if isinstance(d.get("script.execute"), dict)]
    assert runs.count(True) == 7 and runs.count(False) == 7


def test_greenhouse_page_actions() -> None:
    page = _page(GH_PAGE, "greenhouse_page")
    stop = _by_id(page, "gh_btn_stop")
    call = _assert_guarded_confirm(stop["on_click"], "gp.stop_all", "gp_greenhouse")
    assert call["danger"] is True
    assert stop["bg_color"] == 0x93000A, "error-fill is the STOP button only"
    water = _by_id(page, "gh_btn_water_all")
    call = _assert_guarded_confirm(water["on_click"], "gp.full_cycle", "gp_greenhouse")
    assert call["danger"] is False
    assert call["title"] == "Water all beds?" and call["action"] == "WATER ALL"
    assert _by_id(page, "gh_btn_start_queue")["on_click"] == [{"gp.start_queue": "gp_greenhouse"}]
    for wid in ("gh_btn_stop", "gh_btn_start_queue", "gh_btn_water_all"):
        assert _by_id(page, wid)["height"] == 26, "transport buttons are btn-h-md"
    assert "0x93000a" not in _text(CARD).lower() and "0x93000a" not in _text(REFRESH).lower()
    # only gp.* actions reach the irrigation
    keys = {k for d in _walk(_load(GH_PAGE)) for k in d if isinstance(k, str) and k.startswith(("gp.", "garden_zones.", "sprinkler."))}
    assert keys <= {"gp.stop_all", "gp.full_cycle", "gp.start_queue"}, keys


def _nav_active(page: dict, prefix: str) -> set[str]:
    return {n for n in NAV_TARGETS if _color(_by_id(page, f"{prefix}btn_{n}")) == GREEN_FILL}


def test_nav_bars_consistent() -> None:
    pages = {
        "nav_": _page(HOME, "home_page"),
        "setup_nav_": _page(SETUP, "setup_page"),
        "gh_nav_": _page(GH_PAGE, "greenhouse_page"),
    }
    active = {"nav_": "dash", "setup_nav_": "setup", "gh_nav_": "zones"}
    for prefix, page in pages.items():
        for name, target in NAV_TARGETS.items():
            assert _show_targets(_by_id(page, f"{prefix}btn_{name}")) == [target], (prefix, name)
        assert _nav_active(page, prefix) == {active[prefix]}, prefix
        for name in NAV_TARGETS:
            btn = _by_id(page, f"{prefix}btn_{name}")
            assert (btn["x"], btn["y"], btn["height"]) == (_by_id(pages["nav_"], f"nav_btn_{name}")["x"], 204, 32)


def test_detail_page_has_back_and_no_nav() -> None:
    page = _page(GH_PAGE, "gh_bed_detail_page")
    assert _show_targets(_by_id(page, "gh_detail_btn_back")) == ["greenhouse_page"]
    assert not any(isinstance(p.get("id"), str) and "_nav_btn_" in p["id"] for _t, p in _widgets(page))
    assert _by_id(page, "gh_detail_btn_back")["height"] == 26


def test_card_state_colors_in_header_are_tokens() -> None:
    tokens = json.loads((REPO_ROOT / "design/tokens.json").read_text(encoding="utf-8"))
    values = {c["value"].lower().lstrip("#") for c in tokens["color"]["tokens"]}
    used = set(re.findall(r"0x([0-9a-fA-F]{6})", FORMAT_SCREENS.read_text(encoding="utf-8")))
    assert used and {u.lower() for u in used} <= values, {u for u in used if u.lower() not in values}
    assert "93000a" not in {u.lower() for u in used}, "no red on a card"


def test_pollers_guarded() -> None:
    status = _load(STATUS)
    assert status["interval"]
    for interval in status["interval"]:
        first = interval["then"][0]
        assert "if" in first and "changed_since" in str(first["if"]["condition"]), "poller runs only on a model change"
    # LVGL is written from pollers only
    for d in _walk(status):
        for key in ("on_value", "on_state", "on_alert_change"):
            assert key not in d


def test_soil_link() -> None:
    for rel in ("packages/greenhouse/bed_soil.yaml", "packages/sim/bed_soil.yaml"):
        data = _load(rel)
        zone, = data["gp_zone"]
        assert zone["id"] == {"__tag__": "extend", "value": "gh_bed${bed}_switch"}
        assert zone["soil_sensor_id"] == "gh_bed${bed}_soil_moisture"
        assert "gh_bed${bed}_soil_moisture" in str(data["sensor"][0]["id"])
    component = (REPO_ROOT / "components" / "gp_zone" / "__init__.py").read_text(encoding="utf-8")
    assert "soil_sensor_id" in component and "set_zone_soil" in component


def test_stats_strip_formats() -> None:
    """The three greenhouse-page labels show the bare value (the caption says what it is)."""
    for rel in ("packages/greenhouse/sensors_air_dht.yaml", "packages/greenhouse/sensors_soil.yaml", "packages/sim/sensors_lvgl.yaml"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "Air: " not in text and "RH: " not in text and "Soil: " not in text, rel
