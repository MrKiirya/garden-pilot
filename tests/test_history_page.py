"""Task 027 (design D20): the History page (packages/greenhouse/lvgl_history.yaml), its row include, its entry from the
Schedule page and the source plumbing that feeds the SOURCE column."""

from __future__ import annotations

import re

import pytest

from conftest import REPO_ROOT, load_esphome_yaml
from test_layout import _strip_comments
from test_screens import ENTRIES, _by_id, _load, _walk

pytestmark = pytest.mark.unit

HISTORY = "packages/greenhouse/lvgl_history.yaml"
ROW = "packages/lvgl/history_row.yaml"
ROW_REFRESH = "packages/lvgl/history_row_refresh.yaml"
SCHEDULES_SHELL = "packages/lvgl/page_schedules.yaml"
PAGE_ID = "gh_history_page"
COLUMNS = {"date": (8, 38), "time": (48, 42), "zone": (92, 62), "on": (158, 66), "src": (226, 86)}
CAPTIONS = {"DATE": 8, "TIME": 48, "ZONE": 92, "TIME ON": 158, "SOURCE": 226}
TOKEN_COLOURS = {0x131313, 0x3f4a3c, 0xe5e2e1, 0xbecab9, 0x78dc77, 0xffb870, 0x1c1b1b}


def _history_page() -> dict:
    return next(p for p in _load(HISTORY)["lvgl"]["pages"] if p["id"] == PAGE_ID)


def _includes(node: object) -> list[dict]:
    return [d["value"] for d in _walk(node) if d.get("__tag__") == "include" and isinstance(d.get("value"), dict)]


def _num(value: object) -> int:
    return int(value)


def test_d20_geometry() -> None:
    page = _history_page()
    labels = [d for d in _walk(page) if "text" in d and "text_font" in d and "id" not in d]
    # column captions: y 28, montserrat_10, text-dim
    for text, x in CAPTIONS.items():
        caption = next(d for d in labels if d["text"] == text)
        assert (_num(caption["x"]), _num(caption["y"]), caption["text_font"], caption["text_color"]) == (x, 28, "montserrat_10", 0xBECAB9)
    # header: title x 8 y 4 and the shared clock
    title = _by_id(page, "gh_hist_title")
    assert (title["x"], title["y"], title["text_font"], title["text"]) == (8, 4, "montserrat_12", "History")
    clock = _by_id(page, "history_clock_label")
    assert (clock["align"], clock["x"], clock["y"], clock["text_font"], clock["text"]) == ("TOP_RIGHT", -8, 4, "montserrat_12", "--:--")
    # divider under the captions: x 8, y 38, 304 x 1
    dividers = [d for d in _walk(page) if d.get("height") == 1 and d.get("y") == 38]
    assert dividers and (dividers[0]["x"], dividers[0]["width"]) == (8, 304)
    # eight rows at y = 44 + 18 * (n - 1) from one include
    rows = [v for v in _includes(page) if v["file"].endswith("history_row.yaml")]
    assert [(v["vars"]["n"], v["vars"]["y"], v["vars"]["p"]) for v in rows] == [(str(n), str(44 + 18 * (n - 1)), "gh") for n in range(1, 9)]
    # the include: five labels at the column x / width, montserrat_12
    row = load_esphome_yaml(REPO_ROOT / ROW)["obj"]
    assert (row["x"], row["width"], row["height"]) == (0, 320, 18)
    cells = {}
    for d in _walk(row):
        if isinstance(d.get("id"), str) and d["id"].startswith("${p}_hist_r${n}_"):
            cells[d["id"].rsplit("_", 1)[1]] = d
    assert set(cells) == set(COLUMNS)
    for name, (x, w) in COLUMNS.items():
        cell = cells[name]
        assert (cell["x"], cell["y"], cell["width"], cell["text_font"]) == (x, 0, w, "montserrat_12"), name
    assert cells["zone"]["long_mode"] == "DOT" and cells["src"]["long_mode"] == "DOT"
    # empty state
    empty = _by_id(page, "gh_hist_empty")
    assert (empty["text"], empty["text_font"], empty["y"]) == ("No watering yet", "montserrat_12", 110)
    # buttons: y 210, h 26, gp_font_button_md labels
    for bid, x, w, text in (
        ("gh_hist_btn_back", 8, 92, "BACK"),
        ("gh_hist_btn_newer", 104, 100, "NEWER"),
        ("gh_hist_btn_older", 208, 104, "OLDER"),
    ):
        button = _by_id(page, bid)
        assert (button["x"], button["y"], button["width"], button["height"]) == (x, 210, w, 26), bid
        label = next(d for d in _walk(button) if d.get("text") == text)
        assert label["text_font"] == "gp_font_button_md", bid
    assert _by_id(page, "gh_hist_btn_newer")["widgets"][0]["image"]["src"] == "gp_icon_chevron_left"
    assert _by_id(page, "gh_hist_btn_older")["widgets"][-1]["image"]["src"] == "gp_icon_chevron_right"
    # only token colours
    text = _strip_comments((REPO_ROOT / HISTORY).read_text(encoding="utf-8")) + _strip_comments((REPO_ROOT / ROW).read_text(encoding="utf-8"))
    for value in re.findall(r"0x([0-9a-fA-F]{6})\b", text):
        assert int(value, 16) in TOKEN_COLOURS, value
    assert not any(k.startswith("text_font") and v.startswith("montserrat_8") for d in _walk(page) for k, v in d.items() if isinstance(v, str))


def test_chevron_icons_are_vendored() -> None:
    from PIL import Image

    images = {i["id"]: i for i in _load(HISTORY)["image"]}
    assert set(images) == {"gp_icon_chevron_left", "gp_icon_chevron_right"}
    for name, item in (("chevron-left", images["gp_icon_chevron_left"]), ("chevron-right", images["gp_icon_chevron_right"])):
        assert item["file"] == f"${{gp_root}}/packages/lvgl/icons/{name}.png"
        assert item["type"] == "RGB565" and item["transparency"] == "alpha_channel"
        with Image.open(REPO_ROOT / "packages/lvgl/icons" / f"{name}.png") as im:
            assert im.size == (10, 10) and im.mode == "RGBA"
            assert im.getchannel("A").getbbox() is not None
        assert (REPO_ROOT / "design/icons" / f"{name}.svg").is_file(), "source SVG"
    assert _load(HISTORY)["substitutions"]["gp_root"] == "."


def test_history_entry_exit() -> None:
    # no HISTORY button on the Greenhouse page any more
    for path in (REPO_ROOT / "packages").rglob("*.yaml"):
        assert "gh_btn_history" not in path.read_text(encoding="utf-8"), path
    # the Schedule page button: visible, >= 20 px, runs the no-op script that the history package extends
    shell = load_esphome_yaml(REPO_ROOT / SCHEDULES_SHELL)
    page = next(p for p in shell["lvgl"]["pages"] if p["id"] == "schedules_page")
    button = _by_id(page, "sched_btn_history")
    assert button["on_click"] == [{"script.execute": "sched_history_open"}]
    assert button["height"] >= 20
    assert any(s["id"] == "sched_history_open" for s in shell["script"])
    shell_text = _strip_comments((REPO_ROOT / SCHEDULES_SHELL).read_text(encoding="utf-8"))
    assert not re.search(r"\bgh_|garden_schedule", shell_text), "the generic shell names no domain ids"
    row_text = _strip_comments((REPO_ROOT / ROW).read_text(encoding="utf-8"))
    assert not re.search(r"\bgh_|garden_schedule", row_text)
    # the history package shows the button and extends the script to open the page
    data = _load(HISTORY)
    extended = next(p for p in data["lvgl"]["pages"] if p["id"] != PAGE_ID)
    assert {"lvgl.widget.show": "sched_btn_history"} in extended["on_load"]
    opener = next(s for s in data["script"] if "sched_history_open" in str(s.get("id")))
    steps = [next(iter(step)) for step in opener["then"]]
    assert steps == ["globals.set", "lvgl.page.show"]
    assert opener["then"][1] == {"lvgl.page.show": PAGE_ID}
    # BACK returns to the schedule page; no bottom navigation on the history page
    page = _history_page()
    assert _by_id(page, "gh_hist_btn_back")["on_click"] == [{"lvgl.page.show": "schedules_page"}]
    assert not [d["id"] for d in _walk(page) if isinstance(d.get("id"), str) and "nav_btn" in d["id"]]
    for wid in ("gh_hist_btn_back", "gh_hist_btn_newer", "gh_hist_btn_older"):
        assert int(_by_id(page, wid)["height"]) >= 20


def test_history_reads_only_through_gp() -> None:
    code = _strip_comments((REPO_ROOT / HISTORY).read_text(encoding="utf-8"))
    assert not re.search(r"garden_zones|gh_zones|board_relay|sprinkler|id\(gh_bed", code)
    allowed = {"gp_greenhouse", "gp_hist_seen", "gp_header_clock_text"}
    assert set(re.findall(r"id\((gp_\w+)\)", code)) <= allowed
    refresh = _strip_comments((REPO_ROOT / ROW_REFRESH).read_text(encoding="utf-8"))
    assert set(re.findall(r"id\((gp_\w+)\)", refresh)) == set(), "the group id comes in as a var"
    keys = {k for d in _walk(_load(HISTORY)) for k in d if isinstance(k, str) and k.startswith("gp.")}
    assert not keys, "the page only reads history; it starts nothing"


def test_poller_is_guarded_and_lambdas_are_one_line() -> None:
    data = _load(HISTORY)
    pollers = data["interval"]
    assert len(pollers) == 1
    step = pollers[0]["then"][0]
    condition = step["if"]["condition"]["lambda"]
    # history_tick = history_changed_since (always evaluated) || (page visible && a row on it is open: the live tick)
    assert "history_tick" in condition and "gh_hist_visible" in condition
    glue = (REPO_ROOT / "components/gp/gp.h").read_text(encoding="utf-8")
    tick = glue[glue.index("bool history_tick"):]
    assert tick.index("history_changed_since") < tick.index("history_has_open")
    for path in (HISTORY, ROW_REFRESH):
        for d in _walk(_load(path)):
            if d.get("__tag__") == "lambda":
                assert len([ln for ln in d["value"].splitlines() if ln.strip()]) <= 1, d["value"]
    text = (REPO_ROOT / HISTORY).read_text(encoding="utf-8")
    assert not re.search(r"on_value|on_state|on_alert_change", text)


def test_render_and_visibility_flags() -> None:
    data = _load(HISTORY)
    page = _history_page()
    assert any("gh_hist_visible" in str(step) and "true" in str(step) for step in page["on_load"])
    assert any("gh_hist_visible" in str(step) and "false" in str(step) for step in page["on_unload"])
    assert "gh_hist_render" in str(page["on_load"])
    scripts = {s["id"]: s for s in data["script"] if isinstance(s.get("id"), str)}
    render = str(scripts["gh_hist_render"]["then"])
    for n in range(1, 9):
        assert f"gh_hist_r{n}_refresh" in render
    assert "gh_hist_title" in render and "gh_hist_empty" in render
    # the header clock is one action on the shared poller
    extend = next(s for s in data["script"] if "gp_header_clock_update" in str(s.get("id")))
    assert len(extend["then"]) == 1 and extend["then"][0]["lvgl.label.update"]["id"] == "history_clock_label"
    refresh_includes = [v for v in _includes(data) if v["file"].endswith("history_row_refresh.yaml")]
    assert [v["vars"]["n"] for v in refresh_includes] == [str(n) for n in range(1, 9)]
    assert all(v["vars"]["group"] == "gp_greenhouse" and v["vars"]["page"] == "gh_hist_page" for v in refresh_includes)
    # NEWER / OLDER move the page through the clamp helper and render
    for bid, step in (("gh_hist_btn_newer", "- 1"), ("gh_hist_btn_older", "+ 1")):
        click = str(_by_id(page, bid)["on_click"])
        assert "history_clamp_page" in click and step in click and "gh_hist_render" in click


@pytest.mark.parametrize("entry", ENTRIES)
def test_entries_include_history_after_the_greenhouse_page(entry: str) -> None:
    keys = list(load_esphome_yaml(REPO_ROOT / entry)["packages"])
    assert keys.index("gh_lvgl_history") == keys.index("gh_lvgl_page") + 1
    assert keys.index("gh_lvgl_history") > keys.index("lvgl_page_schedules"), "extends schedules_page and sched_history_open"


def test_sources_wired() -> None:
    """The SOURCE column: schedules pass `source: schedule` + slot, Home Assistant paths pass `source: ha`."""
    schedule = _load("packages/greenhouse/schedule.yaml")
    enqueue = next(step["gp.enqueue_zones"] for step in schedule["garden_schedule"][0]["on_run"] if "gp.enqueue_zones" in step)
    assert enqueue["source"] == "schedule"
    assert enqueue["slot"]["value"] == "return slot;"
    api = _load("packages/core/gp_api.yaml")
    started = [(k, v) for d in _walk(api) for k, v in d.items() if k in ("gp.run_zone", "gp.enqueue_zone", "gp.full_cycle")]
    assert len(started) == 3
    for key, value in started:
        assert value["source"] == "ha", key
    main = next(s for s in _load("packages/greenhouse/gp.yaml")["switch"] if s.get("name") == "Greenhouse irrigation")
    assert main["turn_on_action"] == [{"gp.full_cycle": {"id": "gp_greenhouse", "source": "ha"}}]
    # screens never claim a Home Assistant or schedule start; the valve test stays `service`
    for path in (REPO_ROOT / "packages" / "greenhouse").glob("lvgl_*.yaml"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"source:\s*(ha|schedule)\b", _strip_comments(text)), path
    assert "source: service" in (REPO_ROOT / "packages/greenhouse/lvgl_valve_test.yaml").read_text(encoding="utf-8")
    # the zone switch is a Home Assistant entity
    glue = (REPO_ROOT / "components/gp/gp.h").read_text(encoding="utf-8")
    assert "run_zone(this->zone_, {}, Source::HA)" in glue
    init = (REPO_ROOT / "components/gp/__init__.py").read_text(encoding="utf-8")
    assert '"manual", "ha", "schedule", "service"' in init  # gp.run_zone
    assert 'CONF_SLOT' in init


def test_history_formatter_is_pure_and_documented() -> None:
    for header in ("format_history.h", "journal.h", "history.h", "zone_model.h"):
        text = (REPO_ROOT / "components/gp" / header).read_text(encoding="utf-8")
        assert not re.search(r'#include\s+["<]esphome/', text), header
    readme = (REPO_ROOT / "components/gp/README.md").read_text(encoding="utf-8")
    for needle in ("history_changed_since", "interrupted", "flash_write_interval", "source", "OPEN"):
        assert needle in readme, needle
    layout = (REPO_ROOT / "components/gp/history.h").read_text(encoding="utf-8")
    assert "MAGIC = 0x47503031" in layout
    assert 'sizeof(HistoryEntry) == 12' in layout and 'sizeof(PersistBlob) == 1336' in layout
