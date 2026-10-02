"""Valve test and service mode (task 010): the safety limits of the actuator-facing screen."""

from __future__ import annotations

import re

import pytest

from conftest import REPO_ROOT, load_esphome_yaml
from test_layout import _strip_comments
from test_screens import _by_id, _entry_files, _load, _page, _show_targets, _walk

pytestmark = pytest.mark.unit

FILE = "packages/greenhouse/lvgl_valve_test.yaml"
PAGE = "valve_test_page"
MAX_SECONDS = 10
SESSION_MAX_SECONDS = 600
ALLOWED_SPRINKLER = {"sprinkler.start_single_valve", "sprinkler.shutdown", "sprinkler.clear_queued_valves"}


def _seconds(value: object) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|min)", str(value))
    assert m, f"not a plain duration: {value!r}"
    return float(m.group(1)) * {"ms": 0.001, "s": 1, "min": 60}[m.group(2)]


def _scripts() -> dict[str, dict]:
    return {s["id"]: s for s in _load(FILE)["script"]}


def _actions(node: object, key: str) -> list:
    return [d[key] for d in _walk(node) if key in d]


def _text() -> str:
    return _strip_comments((REPO_ROOT / FILE).read_text(encoding="utf-8"))


def test_valve_test_limit() -> None:
    data = _load(FILE)
    limit = _seconds(data["substitutions"]["valve_test_max_time"])
    assert 0 < limit <= MAX_SECONDS, "the valve test limit must not exceed 10 s (human's call to raise it)"
    start = _scripts()["gp_valve_test_start"]
    singles = _actions(start["then"], "sprinkler.start_single_valve")
    assert len(singles) == 1
    assert singles[0]["id"] == "gh_sprinkler"
    assert singles[0]["run_duration"] == "${valve_test_max_time}"
    # No other valve start anywhere in the file (the number only comes from the page's TEST buttons).
    assert len(_actions(data, "sprinkler.start_single_valve")) == 1
    guard = _scripts()["gp_valve_test_guard"]
    assert guard["mode"] == "restart"
    steps = guard["then"]
    assert steps[0] == {"delay": "${valve_test_max_time}"}
    assert steps[-1] == {"sprinkler.shutdown": "gh_sprinkler"}
    # The guard is started by every valve start (second, independent enforcement).
    gated = next(d for d in start["then"] if "if" in d)["if"]["then"]
    order = [next(iter(s)) for s in gated]
    assert {"script.execute": "gp_valve_test_guard"} in gated
    assert order.index("sprinkler.shutdown") < order.index("sprinkler.start_single_valve")
    assert order.index("script.execute") < order.index("sprinkler.start_single_valve"), "guard starts first"


def test_valve_test_actions_are_safe() -> None:
    data = _load(FILE)
    found = {k for d in _walk(data) for k in d if isinstance(k, str) and k.startswith("sprinkler.")}
    assert found <= ALLOWED_SPRINKLER, sorted(found - ALLOWED_SPRINKLER)
    for key in ALLOWED_SPRINKLER:
        for target in _actions(data, key):
            tid = target.get("id") if isinstance(target, dict) else target
            assert tid == "gh_sprinkler", (key, target)
    text = _text()
    assert not re.search(r"switch\.(turn_on|toggle|turn_off)", text)
    assert "board_relay" not in text
    assert "gh_sprinkler_main_switch" not in text


def test_service_mode_lifecycle() -> None:
    data = _load(FILE)
    globs = {g["id"]: g for g in data["globals"]}
    assert globs["gp_service_mode"]["restore_value"] is False
    assert str(globs["gp_service_mode"]["initial_value"]).lower() == "false"
    page = _page(FILE, PAGE)
    assert {"script.execute": "gp_service_enter"} in page["on_load"]
    scripts = _scripts()
    enter = scripts["gp_service_enter"]["then"]
    assert {"sprinkler.shutdown": "gh_sprinkler"} in enter
    assert {"sprinkler.clear_queued_valves": "gh_sprinkler"} in enter
    assert any(d.get("globals.set", {}).get("id") == "gp_service_mode"
               and str(d["globals.set"]["value"]).lower() == "true" for d in enter)
    assert {"script.execute": "gp_service_session"} in enter
    leave = scripts["gp_service_exit"]["then"]
    assert {"sprinkler.shutdown": "gh_sprinkler"} in leave
    assert {"script.stop": "gp_valve_test_guard"} in leave
    assert {"script.stop": "gp_service_session"} in leave
    assert any(d.get("globals.set", {}).get("id") == "gp_service_mode"
               and str(d["globals.set"]["value"]).lower() == "false" for d in leave)
    assert {"lvgl.page.show": "setup_page"} in leave
    stop = scripts["gp_valve_test_stop"]["then"]
    assert {"script.stop": "gp_valve_test_guard"} in stop and {"sprinkler.shutdown": "gh_sprinkler"} in stop
    session = scripts["gp_service_session"]
    assert session["mode"] == "restart"
    assert 0 < _seconds(session["then"][0]["delay"]) <= SESSION_MAX_SECONDS
    assert {"script.execute": "gp_service_exit"} in session["then"]
    # A start is refused outside service mode.
    start = scripts["gp_valve_test_start"]["then"]
    gate = next(d for d in start if "if" in d)["if"]
    assert "gp_service_mode" in str(gate["condition"])
    assert any("sprinkler.start_single_valve" in d for d in _walk(gate["then"]))
    assert not any("sprinkler.start_single_valve" in d for d in start if "if" not in d)
    # 1 s interval blocks external runs while the guard is not running.
    intervals = [i for i in data["interval"] if _seconds(i["interval"]) <= 1]
    assert intervals
    block = [d for d in _walk(intervals[0]["then"]) if "sprinkler.shutdown" in d]
    assert block, "the poller must shut down external runs"
    first = intervals[0]["then"][0]["if"]
    conds = first["condition"]["and"]
    assert len(conds) == 3
    assert "gp_service_mode" in str(conds[0])
    assert "active_valve" in str(conds[1]) and "queued_valve" in str(conds[1])
    assert conds[2] == {"not": {"script.is_running": "gp_valve_test_guard"}}, "the test's own valve must not be killed"
    assert {"sprinkler.shutdown": "gh_sprinkler"} in first["then"]
    body = str(intervals[0]["then"])
    assert "gp_service_mode" in body and "script.is_running" in body and "gp_valve_test_guard" in body
    assert "sprinkler.clear_queued_valves" in body
    assert "service mode: external start blocked" in body


def test_leaving_the_page_ends_service_mode() -> None:
    assert _page(FILE, PAGE)["on_unload"] == [{"script.execute": "gp_service_leave"}]
    leave = _scripts()["gp_service_leave"]["then"]
    assert {"sprinkler.shutdown": "gh_sprinkler"} in leave
    assert {"script.stop": "gp_valve_test_guard"} in leave
    assert {"script.stop": "gp_service_session"} in leave
    assert any(d.get("globals.set", {}).get("id") == "gp_service_mode"
               and str(d["globals.set"]["value"]).lower() == "false" for d in leave)
    assert not any("lvgl.page.show" in d for d in leave), "leaving must not navigate (the user already did)"


def test_stop_and_exit_buttons() -> None:
    page = _page(FILE, PAGE)
    assert _by_id(page, "valve_test_btn_stop")["on_click"] == [{"script.execute": "gp_valve_test_stop"}]
    assert _by_id(page, "valve_test_btn_exit")["on_click"] == [{"script.execute": "gp_service_exit"}]


def test_valve_rows_match_beds() -> None:
    page = _page(FILE, PAGE)
    ids = {p["id"] for d in _walk(page) for item in d.get("widgets") or [] if isinstance(item, dict)
           for p in item.values() if isinstance(p, dict) and "id" in p}
    buttons = sorted(i for i in ids if re.fullmatch(r"valve_test_bed\d+_btn", i))
    assert buttons == ["valve_test_bed1_btn", "valve_test_bed2_btn", "valve_test_bed3_btn"]
    for n in (1, 2, 3):
        click = _by_id(page, f"valve_test_bed{n}_btn")["on_click"]
        assert click == [{"script.execute": {"id": "gp_valve_test_start", "valve": n - 1}}]
        _by_id(page, f"valve_test_bed{n}_status")
    assert not re.search(r"lawn|pump", _text(), re.IGNORECASE)


def test_valve_test_reachable_only_from_setup() -> None:
    assert _show_targets(_by_id(_page("packages/lvgl/page_setup.yaml", "setup_page"), "setup_tile_service")) == [PAGE]
    for entry in ("garden-pilot.yaml", "garden-pilot-sim.yaml"):
        files = _entry_files(entry)
        assert FILE in files
        for f in files:
            if f in (FILE, "packages/lvgl/page_setup.yaml"):
                continue
            assert PAGE not in (REPO_ROOT / f).read_text(encoding="utf-8"), f
