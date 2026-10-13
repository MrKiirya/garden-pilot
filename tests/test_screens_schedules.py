"""Schedules page (WATER tab, task 026): shell, greenhouse rows, nav targets, Home NEXT and the toggle action."""

from __future__ import annotations

import re

import pytest

from conftest import REPO_ROOT, load_esphome_yaml
from test_layout import _strip_comments
from test_screens import HOME, SETUP, _by_id, _entry_files, _load, _page, _show_targets, _walk, _widgets

pytestmark = pytest.mark.unit

SHELL = "packages/lvgl/page_schedules.yaml"
ROWS = "packages/greenhouse/lvgl_schedules.yaml"
STATUS = "packages/greenhouse/gp_lvgl_status.yaml"
COMPONENT = REPO_ROOT / "components" / "garden_schedule"
NAV = {"dash": "home_page", "zones": "greenhouse_page", "water": "schedules_page", "setup": "setup_page"}
ACTIVE = "0x4caf50"


def _text(rel: str) -> str:
    return _strip_comments((REPO_ROOT / rel).read_text(encoding="utf-8"))


def test_schedules_shell_and_rows() -> None:
    shell = _text(SHELL)
    assert not re.search(r"\bgh_|garden_schedule|gp_|gp\.|garden_zones|gh_zones", shell), "the shell is generic"
    page = _page(SHELL, "schedules_page")
    _by_id(page, "sched_empty_label")
    rows = _text(ROWS)
    data = _load(ROWS)
    ext = data["lvgl"]["pages"][0]["id"]
    assert ext.get("__tag__") == "extend" and ext["value"] == "schedules_page", "rows extend the shell page"
    # the only actions: the slot toggle, the master switch, paging and the page's own scripts
    keys = {k for d in _walk(data) for k in d if isinstance(k, str) and "." in k}
    assert keys <= {
        "garden_schedule.toggle_slot", "switch.toggle", "script.execute", "globals.set", "lvgl.widget.show",
        "lvgl.widget.hide", "lvgl.widget.update", "lvgl.label.update",
    }, keys
    assert "gp." not in rows.replace("gp_", "") and not re.search(r"garden_zones|gh_zones|board_relay|sprinkler", rows)
    toggles = [d["garden_schedule.toggle_slot"] for d in _walk(data) if "garden_schedule.toggle_slot" in d]
    assert len(toggles) == 3 and all(t["id"] == "gh_schedule" for t in toggles)
    assert [d["switch.toggle"] for d in _walk(data) if "switch.toggle" in d] == ["gh_schedules_on"]
    for wtype, _props in _widgets(data["lvgl"]):
        assert wtype not in {"roller", "spinbox", "textarea", "keyboard", "dropdown", "slider"}, "view only: no editor"
    # tappable ends are at least btn-h-sm (20 px) tall
    for _t, props in _widgets(data["lvgl"]):
        if _t == "button":
            assert int(props["height"]) >= 20, props["id"]


def test_rows_fit_the_page_without_scrolling() -> None:
    data = _load(ROWS)
    boxes = {}
    for wtype, props in _widgets(data["lvgl"]):
        if wtype == "obj" and str(props.get("id", "")).startswith(("gh_sched_master", "gh_sched_row")):
            boxes[props["id"]] = (int(props["y"]), int(props["y"]) + int(props["height"]))
    assert len(boxes) == 4
    ordered = sorted(boxes.values())
    assert ordered[0][0] >= 24, "below the header divider"
    assert ordered[-1][1] <= 200, "above the nav bar (y=201)"
    for (_a0, a1), (b0, _b1) in zip(ordered, ordered[1:]):
        assert b0 - a1 >= 2, "rows do not touch"


def test_nav_bars_target_the_right_pages() -> None:
    for rel, page_id, prefix in ((HOME, "home_page", "nav_btn_"), (SETUP, "setup_page", "setup_nav_btn_"),
                                 (SHELL, "schedules_page", "sched_nav_btn_")):
        page = _page(rel, page_id)
        for name, target in NAV.items():
            assert _show_targets(_by_id(page, prefix + name)) == [target], (rel, name)
    # the shell: exactly its own tab is green
    page = _page(SHELL, "schedules_page")
    active = [name for name in NAV if _by_id(page, f"sched_nav_btn_{name}").get("bg_color") == int(ACTIVE, 16)]
    assert active == ["water"]


@pytest.mark.parametrize("entry", ["garden-pilot.yaml", "garden-pilot-sim.yaml"])
def test_entries_include_the_schedule_screens(entry: str) -> None:
    keys = list(load_esphome_yaml(REPO_ROOT / entry)["packages"])
    assert keys.index("lvgl_page_lawn") < keys.index("lvgl_page_schedules") < keys.index("lvgl_dialog_confirm")
    slots = [k for k in keys if k.startswith("gh_schedule_slot_")]
    assert keys.index(slots[-1]) < keys.index("gh_lvgl_schedules")
    files = _entry_files(entry)
    assert SHELL in files and ROWS in files


def test_lawn_page_is_untouched_but_unreachable() -> None:
    """WATER opens Schedules now; lawn_page stays included (decided default, SPEC 8)."""
    for rel in (HOME, SETUP):
        assert "lawn_page" not in _text(rel)
    assert _page("packages/lvgl/page_lawn.yaml", "lawn_page")


def test_home_next_from_schedule() -> None:
    assert "gh_home_next_label" not in _text(STATUS)
    rows = _text(ROWS)
    assert re.search(r"id:\s*gh_home_next_label", rows) and "next_run_short()" in rows
    for path in (REPO_ROOT / "components" / "gp").rglob("*"):
        if path.is_file() and path.suffix in {".h", ".py", ".md"}:
            assert "home_next" not in path.read_text(encoding="utf-8"), path
    assert "home_next" not in (REPO_ROOT / "tests" / "cpp" / "test_gp_model.cpp").read_text(encoding="utf-8")


def test_pollers_guarded() -> None:
    data = _load(ROWS)
    assert len(data["interval"]) == 1
    for item in data["interval"]:
        first = item["then"][0]
        assert "if" in first and "changed_since" in str(first["if"]["condition"]), item
        assert "lvgl." not in str(item["then"]), "the poller only runs the refresh script"
    for d in _walk(data):  # LVGL is never touched from a hub trigger
        for key in ("on_run", "on_value", "on_state"):
            assert key not in d, key
    lambdas = [d["value"] for d in _walk(data) if d.get("__tag__") == "lambda"]
    lambdas += [d["lambda"] for d in _walk(data) if isinstance(d.get("lambda"), str)]
    assert lambdas and all(len([ln for ln in text.splitlines() if ln.strip()]) <= 1 for text in lambdas)
    assert data["globals"] and all(g["restore_value"] is False for g in data["globals"])


def test_toggle_slot_action_is_registered_and_documented() -> None:
    init = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert '"garden_schedule.toggle_slot"' in init and "ToggleSlotAction" in init
    header = (COMPONENT / "garden_schedule.h").read_text(encoding="utf-8")
    assert "void toggle_slot(size_t index)" in header and "ToggleSlotAction" in header
    assert "no slot at index" in header, "an out-of-range index warns and does nothing"
    readme = (COMPONENT / "README.md").read_text(encoding="utf-8")
    assert "toggle_slot" in readme and "schedule_format.h" in readme

