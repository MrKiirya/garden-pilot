"""Task 027: the History page (packages/greenhouse/lvgl_history.yaml) and its wiring."""

from __future__ import annotations

import re

import pytest

from conftest import REPO_ROOT, load_esphome_yaml
from test_layout import _strip_comments
from test_screens import ENTRIES, _by_id, _load, _walk

pytestmark = pytest.mark.unit

HISTORY = "packages/greenhouse/lvgl_history.yaml"
PAGE_ID = "gh_history_page"
ROWS = [f"gh_hist_row{i}" for i in range(1, 7)]


def _history_page() -> dict:
    return next(p for p in _load(HISTORY)["lvgl"]["pages"] if p["id"] == PAGE_ID)


def test_history_page_shape() -> None:
    page = _history_page()
    ids = [d["id"] for d in _walk(page) if isinstance(d.get("id"), str)]
    assert set(ROWS) <= set(ids)
    assert len([i for i in ids if re.fullmatch(r"gh_hist_row\d+", i)]) <= 8, "a fixed window of rows, never 100 widgets"
    assert {"gh_hist_pager", "gh_hist_btn_prev", "gh_hist_btn_next", "gh_history_btn_back"} <= set(ids)
    assert not [i for i in ids if "nav_btn" in i], "sub-pages have no bottom navigation"
    back = _by_id(page, "gh_history_btn_back")
    assert back["on_click"] == [{"lvgl.page.show": "greenhouse_page"}]
    for wid in ("gh_hist_btn_prev", "gh_hist_btn_next", "gh_history_btn_back"):
        assert int(_by_id(page, wid)["height"]) >= 20


def test_header_button_opens_the_page() -> None:
    pages = _load(HISTORY)["lvgl"]["pages"]
    extend = next(p for p in pages if p["id"] != PAGE_ID)
    button = _by_id(extend, "gh_btn_history")
    assert button["on_click"] == [{"lvgl.page.show": PAGE_ID}]
    assert int(button["height"]) >= 20
    # the header button sits inside the 22 px header and inside the screen
    assert int(button["y"]) + int(button["height"]) <= 22
    assert int(button["x"]) + int(button["width"]) <= 320


def test_history_reads_only_through_gp() -> None:
    code = _strip_comments((REPO_ROOT / HISTORY).read_text(encoding="utf-8"))
    assert not re.search(r"garden_zones|gh_zones|board_relay|sprinkler|id\(gh_bed", code)
    assert set(re.findall(r"id\((gp_\w+)\)", code)) <= {"gp_greenhouse", "gp_hist_seen"}
    keys = {k for d in _walk(_load(HISTORY)) for k in d if isinstance(k, str) and "." in k and k.startswith("gp.")}
    assert not keys, "the page only reads history; it starts nothing"


def test_poller_is_guarded_and_lambdas_are_one_line() -> None:
    data = _load(HISTORY)
    pollers = data["interval"]
    assert len(pollers) == 1
    step = pollers[0]["then"][0]
    assert "if" in step and "history_changed_since" in step["if"]["condition"]["lambda"]
    for d in _walk(data):
        if d.get("__tag__") == "lambda":
            assert len([ln for ln in d["value"].splitlines() if ln.strip()]) <= 1, d["value"]
    # no LVGL update from a trigger other than the page load, the buttons and the poller
    text = (REPO_ROOT / HISTORY).read_text(encoding="utf-8")
    assert not re.search(r"on_value|on_state|on_alert_change", text)


def test_page_reset_on_open() -> None:
    assert _history_page()["on_load"] == [{"script.execute": "gh_hist_open"}]
    scripts = {s["id"]: s for s in _load(HISTORY)["script"]}
    assert {"gh_hist_render", "gh_hist_open"} <= set(scripts)
    render = str(scripts["gh_hist_render"]["then"])
    for row in ROWS + ["gh_hist_pager"]:
        assert row in render


@pytest.mark.parametrize("entry", ENTRIES)
def test_entries_include_history_after_the_greenhouse_page(entry: str) -> None:
    keys = list(load_esphome_yaml(REPO_ROOT / entry)["packages"])
    assert keys.index("gh_lvgl_history") == keys.index("gh_lvgl_page") + 1


def test_history_formatter_is_pure_and_documented() -> None:
    header = (REPO_ROOT / "components/gp/format_history.h").read_text(encoding="utf-8")
    assert not re.search(r'#include\s+["<]esphome/', header)
    readme = (REPO_ROOT / "components/gp/README.md").read_text(encoding="utf-8")
    for needle in ("history_changed_since", "skipped wet", "result"):
        assert needle in readme, needle
