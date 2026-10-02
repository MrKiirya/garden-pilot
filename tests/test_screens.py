"""Generic screens (task 009): Setup, Network, the confirm dialog and their wiring."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import REPO_ROOT, load_esphome_yaml
from test_layout import _package_files, _strip_comments, _yaml_files

pytestmark = pytest.mark.unit

ENTRIES = ["garden-pilot.yaml", "garden-pilot-sim.yaml"]
DIALOG = "packages/lvgl/dialog_confirm.yaml"
SETUP = "packages/lvgl/page_setup.yaml"
NETWORK = "packages/lvgl/page_network.yaml"
DIAG = "packages/core/diagnostics.yaml"
WIFI = "packages/lvgl/network_wifi_status.yaml"
BOOT = "packages/lvgl/page_boot.yaml"
BOOT_WIFI = "packages/lvgl/boot_wifi.yaml"
HOME = "packages/lvgl/page_home.yaml"
GH_PAGE = "packages/greenhouse/lvgl_page.yaml"
NAV_NAMES = ["dash", "zones", "water", "setup"]
SYMBOLS = {"", "", "", "", "", ""}  # LVGL symbols used in text


def _load(rel: str) -> dict:
    data = load_esphome_yaml(REPO_ROOT / rel)
    assert isinstance(data, dict), rel
    return data


def _walk(node: object):
    """Yield every dict in a nested structure."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _widgets(node: object):
    """Yield (widget_type, props) for every widget in a structure (page/top_layer/widgets lists)."""
    for d in _walk(node):
        for item in d.get("widgets") or []:
            if isinstance(item, dict):
                for wtype, props in item.items():
                    if isinstance(props, dict):
                        yield wtype, props


def _by_id(node: object, wid: str) -> dict:
    for _t, props in _widgets(node):
        if props.get("id") == wid:
            return props
    raise AssertionError(f"widget {wid} not found")


def _page(rel: str, page_id: str) -> dict:
    for page in _load(rel)["lvgl"]["pages"]:
        if page["id"] == page_id:
            return page
    raise AssertionError(f"page {page_id} not in {rel}")


def _show_targets(node: object) -> list[str]:
    return [d["lvgl.page.show"] for d in _walk(node) if isinstance(d.get("lvgl.page.show"), str)]


def _entry_files(entry: str) -> list[str]:
    data = load_esphome_yaml(REPO_ROOT / entry)
    assert isinstance(data, dict)
    return list(_package_files(data).values())


def _page_ids(files: list[str]) -> set[str]:
    ids: set[str] = set()
    for f in files:
        d = load_esphome_yaml(REPO_ROOT / f)
        if isinstance(d, dict) and isinstance(d.get("lvgl"), dict):
            ids |= {p["id"] for p in d["lvgl"].get("pages") or []}
    return ids


@pytest.mark.parametrize("entry", ENTRIES)
def test_nav_targets_exist(entry: str) -> None:
    files = _entry_files(entry)
    ids = _page_ids(files)
    assert {"setup_page", "network_page", "boot_page", "valve_test_page"} <= ids
    for f in files:
        d = load_esphome_yaml(REPO_ROOT / f)
        for target in _show_targets(d):
            assert target in ids, f"{f}: lvgl.page.show -> {target} is not a page of {entry}"


def test_page_ids_unique() -> None:
    seen: dict[str, str] = {}
    for path in _yaml_files("packages"):
        data = load_esphome_yaml(path)
        if not isinstance(data, dict):
            continue
        ids: list[str] = []
        lv = data.get("lvgl")
        if isinstance(lv, dict):
            ids += [p["id"] for p in lv.get("pages") or []]
            ids += [p["id"] for _t, p in _widgets(lv) if isinstance(p.get("id"), str)]
        for wid in ids:
            rel = str(path.relative_to(REPO_ROOT))
            assert wid not in seen, f"id {wid} defined in {seen[wid]} and {rel}"
            seen[wid] = rel


def test_setup_nav() -> None:
    home = _page(HOME, "home_page")
    assert _show_targets(_by_id(home, "nav_btn_setup")) == ["setup_page"]
    setup = _page(SETUP, "setup_page")
    assert _show_targets(_by_id(setup, "setup_tile_network")) == ["network_page"]
    assert _show_targets(_by_id(setup, "setup_tile_display")) == ["touch_test_page"]
    network = _page(NETWORK, "network_page")
    assert _show_targets(_by_id(network, "network_btn_back")) == ["setup_page"]
    for name in NAV_NAMES:
        assert _show_targets(_by_id(setup, f"setup_nav_btn_{name}")) == _show_targets(_by_id(home, f"nav_btn_{name}")) or (
            name == "setup"
        )
    assert _show_targets(_by_id(setup, "setup_nav_btn_setup")) == ["setup_page"]


def test_confirm_dialog_shape() -> None:
    data = _load(DIALOG)
    assert set(data) <= {"globals", "lvgl", "script"}
    assert set(data["lvgl"]) == {"top_layer"}
    root = data["lvgl"]["top_layer"]["widgets"][0]["obj"]
    assert root["id"] == "gp_confirm_layer"
    assert root["hidden"] is True
    assert (root["x"], root["y"], root["width"], root["height"]) == (0, 0, 320, 240)
    for wid in ("gp_confirm_title", "gp_confirm_body", "gp_confirm_cancel", "gp_confirm_ok_danger",
                "gp_confirm_ok_primary", "gp_confirm_ok_danger_label", "gp_confirm_ok_primary_label"):
        _by_id(data["lvgl"], wid)
    scripts = {s["id"]: s for s in data["script"]}
    s = scripts["gp_confirm"]
    assert set(s["parameters"]) == {"title", "body", "action", "danger"}
    waits = [d for d in _walk(s["then"]) if "wait_until" in d]
    assert waits and 0 < len(waits)
    wu = waits[0]["wait_until"]
    assert isinstance(wu, dict) and re.fullmatch(r"\d+s", str(wu["timeout"]))
    assert int(str(wu["timeout"]).rstrip("s")) <= 60
    globs = {g["id"]: g for g in data["globals"]}
    assert set(globs) == {"gp_confirm_open", "gp_confirm_result"}
    assert all(g["restore_value"] is False for g in globs.values())
    steps = s["then"]
    sets = [(i, d["globals.set"]) for i, d in enumerate(steps) if "globals.set" in d]
    wait_idx = next(i for i, d in enumerate(steps) if "wait_until" in d)
    assert any(g["id"] == "gp_confirm_result" and str(g["value"]).lower() == "false" and i < wait_idx
               for i, g in sets), "result must be reset to false before wait_until"
    assert any(g["id"] == "gp_confirm_open" and str(g["value"]).lower() == "true" and i < wait_idx for i, g in sets)
    tail = steps[wait_idx + 1:]
    assert {"lvgl.widget.hide": "gp_confirm_layer"} in tail, "dialog must be hidden at the end"
    assert any(d.get("globals.set", {}).get("id") == "gp_confirm_open"
               and str(d["globals.set"]["value"]).lower() == "false" for d in tail)
    assert "gp_confirm_result" not in str(tail), "nothing after the wait may touch the result"
    cancel = _by_id(data["lvgl"], "gp_confirm_cancel")
    assert "gp_confirm_result" not in str(cancel["on_click"]), "CANCEL must never set the result"
    for wid in ("gp_confirm_ok_danger", "gp_confirm_ok_primary"):
        clicks = _by_id(data["lvgl"], wid)["on_click"]
        assert any(c["globals.set"]["id"] == "gp_confirm_result" and str(c["globals.set"]["value"]).lower() == "true"
                   for c in clicks)
    base = _load("packages/lvgl/base.yaml")
    own = set(globs) | {s["id"] for s in data["script"]} | {
        p["id"] for _t, p in _widgets(data["lvgl"]) if "id" in p
    }
    text = _strip_comments((REPO_ROOT / DIALOG).read_text(encoding="utf-8"))
    refs = set(re.findall(r"id\(\s*(\w+)\s*\)", text))
    refs |= set(re.findall(r"(?:id|script\.wait|script\.execute):\s*(?:\{id:\s*)?(\w+)", text))
    refs -= {"id", "title", "body", "action", "danger"}
    assert refs <= own | set(base["lvgl"].get("displays", [])), sorted(refs - own)


def _stop_click() -> list:
    for _t, p in _widgets(_load(GH_PAGE)["lvgl"]):
        if p.get("id") == "gh_btn_stop":
            return p["on_click"]
    raise AssertionError("gh_btn_stop not found")


def _assert_guarded_confirm(click: list, action_key: str, action_val: str) -> dict:
    """on_click = one `if not script.is_running: gp_confirm` -> execute, wait, `if` result -> action."""
    assert len(click) == 1, "the whole confirm sequence sits behind the is_running guard"
    guard = click[0]["if"]
    assert guard["condition"] == {"not": {"script.is_running": "gp_confirm"}}
    first, second, third = guard["then"]
    assert first["script.execute"]["id"] == "gp_confirm"
    assert second == {"script.wait": "gp_confirm"}
    assert "gp_confirm_result" in str(third["if"]["condition"])
    assert {action_key: action_val} in third["if"]["then"]
    assert len(third["if"]["then"]) == 1
    return first["script.execute"]


def test_stop_asks_for_confirmation() -> None:
    call = _assert_guarded_confirm(_stop_click(), "sprinkler.shutdown", "gh_sprinkler")
    assert call["danger"] is True


def test_restart_is_confirmed() -> None:
    total = guarded = 0
    for path in _yaml_files("packages"):
        data = load_esphome_yaml(path)
        total += sum(1 for d in _walk(data) if d.get("button.press") == "gp_restart_button")
        for d in _walk(data):
            cond = d.get("if")
            if isinstance(cond, dict) and "gp_confirm_result" in str(cond.get("condition")):
                guarded += sum(1 for x in _walk(cond.get("then")) if x.get("button.press") == "gp_restart_button")
    assert total == 1 and guarded == 1, (total, guarded)
    buttons = {b["id"]: b for b in _load(DIAG)["button"]}
    assert buttons["gp_restart_button"]["platform"] == "restart"
    assert buttons["gp_restart_button"]["internal"] is True


def test_new_diagnostics_are_internal() -> None:
    for rel in (DIAG, WIFI):
        data = _load(rel)
        checked = 0
        for domain in ("sensor", "text_sensor", "button"):
            for item in data.get(domain) or []:
                checked += 1
                subs = [v for v in item.values() if isinstance(v, dict) and "id" in v]
                for entity in subs or [item]:  # wifi_info nests its sensors (ssid:, ip_address:)
                    assert entity.get("internal") is True, f"{rel}: {domain} {item.get('platform')} must be internal"
        assert checked, rel


def test_device_only_packages_not_in_sim() -> None:
    sim_files = _entry_files("garden-pilot-sim.yaml")
    for f in sim_files:
        text = _strip_comments((REPO_ROOT / f).read_text(encoding="utf-8"))
        assert not re.search(r"wifi_info|wifi_signal|wifi\.connected", text), f
    assert WIFI in _entry_files("garden-pilot.yaml")
    assert WIFI not in sim_files


TOKENIZED_TEXT_FILES = [SETUP, NETWORK, DIALOG, WIFI, BOOT, "packages/greenhouse/lvgl_valve_test.yaml",
                        "packages/lvgl/screensaver.yaml", "packages/greenhouse/screensaver_status.yaml"]


@pytest.mark.parametrize("rel", TOKENIZED_TEXT_FILES)
def test_screen_text_is_ascii(rel: str) -> None:
    data = _load(rel)
    for d in _walk(data):
        for key in ("text", "title", "body"):
            val = d.get(key)
            if isinstance(val, str):
                bad = [c for c in val if (ord(c) > 0x7E or ord(c) < 0x20) and c not in SYMBOLS]
                assert not bad, f"{rel}: non-ASCII {bad!r} in {key}: {val!r}"
    text = _strip_comments((REPO_ROOT / rel).read_text(encoding="utf-8"))
    bad = [c for c in text if ord(c) > 0x7E and c not in SYMBOLS]
    assert not bad, f"{rel}: non-ASCII characters {bad!r}"


@pytest.mark.parametrize("rel", [GH_PAGE, NETWORK])
def test_confirm_call_texts_are_ascii(rel: str) -> None:
    calls = [d["script.execute"] for d in _walk(_load(rel)) if isinstance(d.get("script.execute"), dict)
             and d["script.execute"].get("id") == "gp_confirm"]
    assert calls, rel
    for call in calls:
        for key in ("title", "body", "action"):
            assert call[key].isascii() and call[key].isprintable(), f"{rel}: non-ASCII {key}: {call[key]!r}"
            assert len(call[key]) > 0



@pytest.mark.parametrize("entry", ENTRIES)
def test_boot_page_first(entry: str) -> None:
    keys = list(load_esphome_yaml(REPO_ROOT / entry)["packages"])
    assert [k for k in keys if k.startswith("lvgl_page_")][0] == "lvgl_page_boot"
    assert keys.index("lvgl_base") < keys.index("lvgl_page_boot") < keys.index("lvgl_page_home")
    files = _entry_files(entry)
    assert files[keys.index("lvgl_page_boot")] == BOOT
    data = _load(BOOT)
    assert _page(BOOT, "boot_page")
    text = _strip_comments((REPO_ROOT / BOOT).read_text(encoding="utf-8"))
    assert not re.search(r"sprinkler\.|switch\.|board_relay|valve", text.replace("Valves closed", "")), "no actuator action"
    assert set(data) <= {"substitutions", "esphome", "globals", "script", "lvgl"}
    assert data["substitutions"]["boot_offline_timeout"]
    globs = {g["id"]: g for g in data["globals"]}
    assert set(globs) == {"gp_boot_net_ready", "gp_boot_done"}
    assert all(g["restore_value"] is False for g in globs.values())
    boot = data["esphome"]["on_boot"]
    assert boot[0]["priority"] == -100
    assert {"script.execute": "gp_boot_sequence"} in boot[0]["then"]
    seq = {s["id"]: s for s in data["script"]}["gp_boot_sequence"]
    assert seq["mode"] == "single"
    steps = seq["then"]
    wait = next(d for d in steps if "wait_until" in d)["wait_until"]
    assert wait["timeout"] == "${boot_offline_timeout}"
    assert "gp_boot_net_ready" in str(wait["condition"])
    assert steps[-1] == {"lvgl.page.show": "home_page"}


def test_boot_wifi_device_only() -> None:
    data = _load(BOOT_WIFI)
    assert set(data) == {"wifi"} and set(data["wifi"]) == {"on_connect"}
    assert data["wifi"]["on_connect"] == [{"globals.set": {"id": "gp_boot_net_ready", "value": "true"}}]
    keys = list(load_esphome_yaml(REPO_ROOT / "garden-pilot.yaml")["packages"])
    files = _entry_files("garden-pilot.yaml")
    assert BOOT_WIFI in files
    assert keys.index("lvgl_boot_wifi") > keys.index("lvgl_network_wifi")
    assert BOOT_WIFI not in _entry_files("garden-pilot-sim.yaml")
    sim = load_esphome_yaml(REPO_ROOT / "garden-pilot-sim.yaml")
    assert sim["substitutions"]["boot_offline_timeout"] == "3s"
    dev = load_esphome_yaml(REPO_ROOT / "garden-pilot.yaml")
    assert "boot_offline_timeout" not in dev["substitutions"]
