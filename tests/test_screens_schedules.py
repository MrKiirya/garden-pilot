"""Schedule screens (WATER nav slot, tasks 026 and 030): the generic shell, the list rows (D08), the editor page (D09),
nav targets, Home NEXT, and the removal of the toggle action."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from conftest import REPO_ROOT, _EsphomeLoader, load_esphome_yaml
from test_layout import _strip_comments
from test_screens import (
    HOME,
    SETUP,
    _by_id,
    _entry_files,
    _load,
    _page,
    _show_targets,
    _walk,
    _widgets,
)

pytestmark = pytest.mark.unit

SHELL = "packages/lvgl/page_schedules.yaml"
ROWS = "packages/greenhouse/lvgl_schedules.yaml"
HELPERS = [
    "packages/greenhouse/lvgl_schedules_row.yaml",
    "packages/greenhouse/lvgl_schedules_row_refresh.yaml",
    "packages/greenhouse/lvgl_schedules_toggle.yaml",
    "packages/greenhouse/lvgl_schedules_toggle_refresh.yaml",
]
STATUS = "packages/greenhouse/gp_lvgl_status.yaml"
COMPONENT = REPO_ROOT / "components" / "garden_schedule"
NAV = {"dash": "home_page", "zones": "greenhouse_page", "water": "schedules_page", "setup": "setup_page"}
ACTIVE = "0x4caf50"
BUTTON_FONTS_IDS = {"gp_font_button_md", "gp_font_button_sm"}
FORBIDDEN_WIDGETS = {"roller", "spinbox", "textarea", "keyboard", "dropdown", "slider"}


def _text(rel: str) -> str:
    return _strip_comments((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _expand(node: object, base: Path) -> object:
    """Replaces every `!include {file, vars}` by the parsed file (vars substituted like ESPHome does)."""
    if isinstance(node, dict):
        if node.get("__tag__") == "include":
            value = node["value"]
            if isinstance(value, str):
                value = {"file": value, "vars": {}}
            path = base / value["file"]
            text = path.read_text(encoding="utf-8")
            for key, val in (value.get("vars") or {}).items():
                text = text.replace("${" + key + "}", str(val))
            assert "${" not in text, f"{path}: a var is not set: {sorted(set(re.findall(r'[$][{](\\w+)[}]', text)))}"
            return _expand(yaml.load(text, Loader=_EsphomeLoader), path.parent)  # noqa: S506 - SafeLoader subclass
        return {k: _expand(v, base) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand(v, base) for v in node]
    return node


def _rows_data() -> dict:
    data = _expand(_load(ROWS), (REPO_ROOT / ROWS).parent)
    assert isinstance(data, dict)
    return data


def _edit_page(data: dict) -> dict:
    return next(p for p in data["lvgl"]["pages"] if p["id"] == "gh_sched_edit_page")


def _list_page(data: dict) -> dict:
    return next(p for p in data["lvgl"]["pages"] if isinstance(p["id"], dict))


def _lambdas(data: object) -> list[str]:
    out = [d["value"] for d in _walk(data) if d.get("__tag__") == "lambda" and isinstance(d["value"], str)]
    out += [d["lambda"] for d in _walk(data) if isinstance(d.get("lambda"), str)]
    return out


def test_shell_is_generic() -> None:
    shell = _text(SHELL)
    assert not re.search(r"\bgh_|garden_schedule|\bgp\.|garden_zones|gh_zones", shell), "the shell is generic"
    page = _page(SHELL, "schedules_page")
    _by_id(page, "sched_empty_label")
    history = _by_id(page, "sched_btn_history")
    assert history.get("hidden") is True, "HISTORY stays hidden until the history task"
    assert history["height"] >= 20 and history["x"] + history["width"] <= 268, "left of the clock"
    assert "on_click" not in history
    for name, target in NAV.items():
        assert _show_targets(_by_id(page, f"sched_nav_btn_{name}")) == [target], name
    active = [n for n in NAV if _by_id(page, f"sched_nav_btn_{n}").get("bg_color") == int(ACTIVE, 16)]
    assert active == ["water"]
    label = next(p for t, p in _widgets(_by_id(page, "sched_nav_btn_water")) if t == "label")
    assert label["text"] == "SCHEDULE"
    title = next(p for t, p in _widgets(page) if t == "label" and p.get("text") == "Schedule")
    assert (title["x"], title["y"], title["text_font"]) == (8, 4, "montserrat_12")
    clock = _by_id(page, "sched_clock_label")
    assert (clock["align"], clock["x"], clock["y"], clock["text_font"]) == ("TOP_RIGHT", -8, 4, "montserrat_12")


def test_rows_and_editor_shape() -> None:
    data = _rows_data()
    ext = _list_page(data)["id"]
    assert ext["__tag__"] == "extend" and ext["value"] == "schedules_page", "the rows extend the shell page"
    # list: 4 clickable cards under the header, above the nav bar
    rows = {}
    for n in range(1, 5):
        row = _by_id(_list_page(data), f"gh_sched_row{n}")
        rows[n] = row
        assert (row["x"], row["y"], row["width"], row["height"]) == (8, 44 + 38 * (n - 1), 304, 34)
        assert (row["bg_color"], row["border_color"], row["radius"]) == (0x1C1B1B, 0x3F4A3C, 2)
        assert row.get("hidden") is True and row["on_click"][0]["lambda"] == f"id(gh_schedule)->begin_edit({n - 1});"
        assert {"lvgl.page.show": "gh_sched_edit_page"} in row["on_click"]
        ids = {p["id"]: p for _t, p in _widgets(row)}
        assert set(ids) == {f"gh_sched_row{n}_{k}" for k in ("time", "label", "caption", "status", "countdown", "chev")}
        assert ids[f"gh_sched_row{n}_time"]["text_font"] == "montserrat_14"
        for k in ("label", "caption"):
            assert ids[f"gh_sched_row{n}_{k}"]["width"] == 180 and ids[f"gh_sched_row{n}_{k}"]["long_mode"] == "DOT"
        assert ids[f"gh_sched_row{n}_label"]["text_font"] == "montserrat_12"
        assert ids[f"gh_sched_row{n}_caption"]["text_font"] == "montserrat_10"
        assert ids[f"gh_sched_row{n}_status"]["text_font"] == "montserrat_10"
        assert ids[f"gh_sched_row{n}_chev"]["text"] == ""
        # right column of the design: status word and countdown right-aligned (card-relative, minus the 1 px border)
        assert (ids[f"gh_sched_row{n}_status"]["x"], ids[f"gh_sched_row{n}_status"]["width"]) == (219, 62)
        assert (ids[f"gh_sched_row{n}_countdown"]["x"], ids[f"gh_sched_row{n}_countdown"]["width"]) == (209, 72)
        for k in ("status", "countdown"):
            assert ids[f"gh_sched_row{n}_{k}"]["text_align"] == "RIGHT" and ids[f"gh_sched_row{n}_{k}"]["text_font"] == "montserrat_10"
        assert ids[f"gh_sched_row{n}_label"]["y"] == 3 and ids[f"gh_sched_row{n}_caption"]["y"] == 18
    assert rows[1]["y"] >= 44 and rows[4]["y"] + rows[4]["height"] <= 200
    summary = {p["id"]: p for _t, p in _widgets(_list_page(data)) if str(p.get("id", "")).startswith("gh_sched_sum_")}
    assert (summary["gh_sched_sum_label"]["x"], summary["gh_sched_sum_label"]["y"]) == (46, 27)
    inn = summary["gh_sched_sum_in"]
    assert (inn["x"], inn["y"], inn["width"], inn["text_align"], inn["text_color"]) == (212, 27, 100, "RIGHT", 0x78DC77)
    assert any(p.get("text") == "NEXT" and (p["x"], p["y"]) == (8, 28) for _t, p in _widgets(_list_page(data)))
    # editor page
    edit = _edit_page(data)
    assert _show_targets(_by_id(edit, "gh_sed_btn_cancel")) == ["schedules_page"]
    for wid in (
        "gh_sed_title", "gh_sed_clock_label", "gh_sed_on_label", "gh_sed_switch", "gh_sed_btn_enable",
        "gh_sed_btn_hour_dec", "gh_sed_btn_hour_inc", "gh_sed_hour_label", "gh_sed_btn_min_dec", "gh_sed_btn_min_inc",
        "gh_sed_min_label", "gh_sed_btn_pct_dec", "gh_sed_btn_pct_inc", "gh_sed_pct_label", "gh_sed_btn_cancel",
        "gh_sed_btn_save",
    ):
        _by_id(edit, wid)
    enable = _by_id(edit, "gh_sed_btn_enable")
    assert (enable["x"], enable["y"], enable["width"], enable["height"]) == (196, 0, 56, 22)
    assert _by_id(edit, "gh_sed_switch")["clickable"] is False
    expected = {
        "gh_sed_btn_hour_dec": (8, 40, 36, 26), "gh_sed_btn_hour_inc": (112, 40, 36, 26),
        "gh_sed_btn_min_dec": (172, 40, 36, 26), "gh_sed_btn_min_inc": (276, 40, 36, 26),
        "gh_sed_btn_pct_dec": (168, 179, 36, 22), "gh_sed_btn_pct_inc": (276, 179, 36, 22),
        "gh_sed_btn_cancel": (8, 210, 150, 26), "gh_sed_btn_save": (162, 210, 150, 26),
    }
    for wid, box in expected.items():
        b = _by_id(edit, wid)
        assert (b["x"], b["y"], b["width"], b["height"]) == box, wid
    for i in range(7):
        b = _by_id(edit, f"gh_sed_btn_day{i + 1}")
        assert (b["x"], b["y"], b["width"], b["height"]) == (8 + 44 * i, 86, 40, 22)
        assert b["on_click"][0]["lambda"] == f"id(gh_schedule)->edit_toggle_day({i});"
        assert next(p for t, p in _widgets(b) if t == "label")["text"] == "MTWTFSS"[i]
    for i in range(6):
        b = _by_id(edit, f"gh_sed_btn_zone{i + 1}")
        x, y = (8 + 62 * i, 126) if i < 5 else (8, 152)
        assert (b["x"], b["y"], b["width"], b["height"]) == (x, y, 56, 22)
        assert b["on_click"][0]["lambda"] == f"id(gh_schedule)->edit_toggle_zone({i});"
        assert next(p for t, p in _widgets(b) if t == "label")["text"] == f"BED {i + 1}"
    # the caption texts of the design
    texts = {p.get("text") for t, p in _widgets(edit) if t == "label"}
    assert {"HOUR", "MINUTE", "DAYS", "ZONES", "RUN TIME"} <= texts and "START - HOUR" not in texts
    for cap, x in (("HOUR", 44), ("MINUTE", 208)):
        lab = next(p for _t, p in _widgets(edit) if p.get("text") == cap)
        assert (lab["x"], lab["y"], lab["width"], lab["text_align"]) == (x, 28, 68, "CENTER"), cap
    # every clickable is at least 20 px tall (design rule), nothing but buttons and the row cards is clickable
    for _t, props in _widgets(data["lvgl"]):
        if "on_click" in props:
            assert int(props["height"]) >= 20, props["id"]
        assert _t not in FORBIDDEN_WIDGETS, "no roller, spinbox, textarea, keyboard, dropdown or slider"
    # no engine and no direct entity actions; only the hub's draft and the page's own scripts
    code = _text(ROWS)
    assert not re.search(r"\bgp\.|garden_zones|gh_zones|board_relay|sprinkler", code)
    keys = {k for d in _walk(data) for k in d if isinstance(k, str) and "." in k}
    assert keys <= {
        "script.execute", "lvgl.page.show", "lvgl.widget.show", "lvgl.widget.hide", "lvgl.widget.update",
        "lvgl.label.update",
    }, keys
    for needle in ("switch.turn", "datetime.", "text.set", "number.set", "garden_schedule.", "make_call", "publish_state"):
        assert needle not in code, needle
    # the editor buttons: one draft lambda (or the page change) and the refresh
    for _t, props in _widgets(edit):
        for step in props.get("on_click") or []:
            assert isinstance(step, dict)


def test_editor_writes_only_on_save() -> None:
    data = _rows_data()
    code = _text(ROWS)
    callers = [p["id"] for _t, p in _widgets(data["lvgl"]) if "save_edit" in str(p.get("on_click"))]
    assert callers == ["gh_sed_btn_save"], callers
    save = _by_id(_edit_page(data), "gh_sed_btn_save")
    first = save["on_click"][0]
    assert "if" in first and first["if"]["condition"]["lambda"] == "return id(gh_schedule)->can_save();"
    then = first["if"]["then"]
    assert then[0]["lambda"] == "id(gh_schedule)->save_edit();"
    assert {"script.execute": "gh_sched_list_refresh"} in then and {"lvgl.page.show": "schedules_page"} in then
    cancel = _by_id(_edit_page(data), "gh_sed_btn_cancel")
    assert cancel["on_click"] == [{"lambda": "id(gh_schedule)->cancel_edit();"}, {"lvgl.page.show": "schedules_page"}]
    # every other editor click edits the draft and redraws
    for wid in ("gh_sed_btn_hour_dec", "gh_sed_btn_hour_inc", "gh_sed_btn_min_dec", "gh_sed_btn_min_inc",
                "gh_sed_btn_pct_dec", "gh_sed_btn_pct_inc", "gh_sed_btn_enable"):
        click = _by_id(_edit_page(data), wid)["on_click"]
        assert len(click) == 2 and click[0]["lambda"].startswith("id(gh_schedule)->draft().")
        assert click[1] == {"script.execute": "gh_sed_refresh"}
    assert "make_call" not in code and "publish_state" not in code
    # the zone duration provider is set once at boot and only reads the gp read model
    assert code.count("set_zone_seconds(") == 1 and "->zone(z).run_duration" in code


def test_nav_bars_target_the_right_pages() -> None:
    for rel, page_id, prefix in ((HOME, "home_page", "nav_btn_"), (SETUP, "setup_page", "setup_nav_btn_"),
                                 (SHELL, "schedules_page", "sched_nav_btn_")):
        page = _page(rel, page_id)
        for name, target in NAV.items():
            assert _show_targets(_by_id(page, prefix + name)) == [target], (rel, name)


@pytest.mark.parametrize("entry", ["garden-pilot.yaml", "garden-pilot-sim.yaml"])
def test_entries_include_the_schedule_screens(entry: str) -> None:
    keys = list(load_esphome_yaml(REPO_ROOT / entry)["packages"])
    assert keys.index("lvgl_page_lawn") < keys.index("lvgl_page_schedules") < keys.index("lvgl_dialog_confirm")
    slots = [k for k in keys if k.startswith("gh_schedule_slot_")]
    assert slots == [f"gh_schedule_slot_{n}" for n in range(1, 5)]
    assert keys.index(slots[-1]) < keys.index("gh_lvgl_schedules")
    files = _entry_files(entry)
    assert SHELL in files and ROWS in files


def test_lawn_page_is_untouched_but_unreachable() -> None:
    """The nav opens Schedule now; lawn_page stays included (decided default, SPEC 8)."""
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
    data = _rows_data()
    assert len(data["interval"]) == 1
    for item in data["interval"]:
        first = item["then"][0]
        assert "if" in first and "changed_since" in str(first["if"]["condition"]), item
        assert "lvgl." not in str(item["then"]), "the poller only runs the refresh script"
    for d in _walk(data):  # LVGL is never touched from a hub trigger
        for key in ("on_run", "on_value", "on_state"):
            assert key not in d, key
    lambdas = _lambdas(data)
    assert lambdas and all(len([ln for ln in text.splitlines() if ln.strip()]) <= 1 for text in lambdas)
    assert data["globals"] and all(g["restore_value"] is False for g in data["globals"])
    # the header clock of the editor page: one action on the shared poller
    scripts = [s for s in data["script"] if isinstance(s.get("id"), dict)]
    assert len(scripts) == 1 and scripts[0]["id"]["value"] == "gp_header_clock_update"
    assert len(scripts[0]["then"]) == 1 and scripts[0]["then"][0]["lvgl.label.update"]["id"] == "gh_sed_clock_label"
    ids = [s["id"] for s in data["script"] if isinstance(s.get("id"), str)]
    assert len(ids) == len(set(ids)) and {"gh_sched_list_refresh", "gh_sed_refresh"} <= set(ids)
    for n in range(1, 5):
        assert f"gh_sched_row{n}_refresh" in ids
    for kind, count in (("day", 7), ("zone", 6)):
        for n in range(1, count + 1):
            assert f"gh_sed_{kind}{n}_refresh" in ids


def test_refresh_scripts_cover_every_widget() -> None:
    """Every widget id a refresh script updates exists, and every list / editor label is refreshed."""
    data = _rows_data()
    known = {p["id"] for _t, p in _widgets(data["lvgl"]) if isinstance(p.get("id"), str)}
    known |= {p["id"] for p in _walk(_load(SHELL)["lvgl"]) if isinstance(p.get("id"), str)}
    known |= {"gh_home_next_label"}
    updates = []
    for d in _walk(data["script"]):
        for key in ("lvgl.label.update", "lvgl.widget.update"):
            if isinstance(d.get(key), dict):
                updates.append(d[key]["id"])
        for key in ("lvgl.widget.show", "lvgl.widget.hide"):
            if isinstance(d.get(key), str):
                updates.append(d[key])
    assert updates and all(u in known or u in {"gh_home_next_label"} for u in updates), sorted(set(updates) - known)
    for n in range(1, 5):
        for k in ("time", "label", "caption", "status", "countdown"):
            assert f"gh_sched_row{n}_{k}" in updates
    assert {"gh_sched_sum_label", "gh_sched_sum_in"} <= set(updates)


def test_text_lambdas_return_strings() -> None:
    """A `? "x" : "y"` ternary of string literals returns const char*, which LVGL text updates reject on ESP32."""
    texts = []
    for rel in [ROWS, *HELPERS]:
        for d in _walk(load_esphome_yaml(REPO_ROOT / rel)):
            for key in ("text", "title"):
                val = d.get(key)
                if isinstance(val, dict) and val.get("__tag__") == "lambda":
                    texts.append((rel, val["value"]))
    assert texts
    for rel, code in texts:
        if re.search(r'[?]\s*"[^"]*"\s*:\s*"', code):
            assert "std::string(" in code, f"{rel}: wrap the literal ternary in std::string(): {code}"


def test_toggle_slot_removed() -> None:
    for path in list((REPO_ROOT / "components" / "garden_schedule").rglob("*")) + list((REPO_ROOT / "packages").rglob("*")):
        if path.is_file() and path.suffix in {".h", ".py", ".md", ".yaml"}:
            text = path.read_text(encoding="utf-8")
            assert "toggle_slot" not in text and "ToggleSlot" not in text, path
            assert "pager_text" not in text and "page_step" not in text, path


def _token_colors() -> set[str]:
    tokens = json.loads((REPO_ROOT / "design/tokens.json").read_text(encoding="utf-8"))
    return {entry["value"].lower().lstrip("#") for entry in tokens["color"]["tokens"]}


def test_schedule_ui_colours_are_tokens() -> None:
    text = (COMPONENT / "schedule_ui.h").read_text(encoding="utf-8")
    used = {c.lower() for c in re.findall(r"\b0x([0-9a-fA-F]{6})\b", text)}
    assert used and used <= _token_colors(), sorted(used - _token_colors())
    names = {e["name"]: e["value"].lower().lstrip("#")
             for e in json.loads((REPO_ROOT / "design/tokens.json").read_text(encoding="utf-8"))["color"]["tokens"]}
    for const, token in (("TONE_TEXT", "text"), ("TONE_DIM", "text-dim"), ("TONE_GREEN", "green"), ("TONE_AMBER", "amber")):
        assert re.search(rf"{const} = 0x{names[token]};", text), const


def test_helper_files_use_tokens_and_ascii() -> None:
    for rel in HELPERS + [ROWS, SHELL]:
        raw = (REPO_ROOT / rel).read_text(encoding="utf-8")
        code = _strip_comments(raw)
        assert {c.lower() for c in re.findall(r"\b0x([0-9a-fA-F]{6})\b", code)} <= _token_colors(), rel
        assert set(re.findall(r"\b(?:montserrat_\d+|gp_font_\w+)\b", code)) <= {
            "montserrat_10", "montserrat_12", "montserrat_14", "montserrat_16", "gp_font_button_md", "gp_font_button_sm"}, rel
        assert "montserrat_8" not in code and "gp_font_clock" not in code
        bad = [c for c in code if ord(c) > 0x7E]
        assert not bad, f"{rel}: non-ASCII characters {bad!r}"
    for _t, props in _widgets(_rows_data()["lvgl"]):
        if props.get("text_font") in BUTTON_FONTS_IDS:
            assert set(props["text"]) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 +-./:%"), props
