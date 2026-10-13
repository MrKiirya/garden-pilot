"""Task 018: the gp_* layer. Shape checks of the packages and the component, codegen on the device entry, and a host
scenario over the real packages (tests/configs/gp_layer_sim.yaml)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from conftest import REPO_ROOT, load_esphome_yaml
from test_garden_zones import _need_compiler, _resolve, _run_program
from test_greenhouse_zones import VERSIONS, _esphome, _generate
from test_layout import _strip_comments, _yaml_files
from test_screens import _walk

COMPONENT = REPO_ROOT / "components" / "gp"
ZONE_COMPONENT = REPO_ROOT / "components" / "gp_zone"
ADAPTER = REPO_ROOT / "components" / "garden_zones" / "gp_engine.h"
CORE_GP = "packages/core/gp.yaml"
CORE_GP_API = "packages/core/gp_api.yaml"
GH_GP = "packages/greenhouse/gp.yaml"
CALLERS = [
    "packages/greenhouse/lvgl_page.yaml",
    "packages/greenhouse/gp_lvgl_status.yaml",
    "packages/greenhouse/lvgl_valve_test.yaml",
    "packages/greenhouse/screensaver_status.yaml",
    "packages/greenhouse/lvgl_history.yaml",
]
ENGINE_FILES = {
    "packages/greenhouse/irrigation.yaml",
    "packages/greenhouse/irrigation_pump.yaml",
    "packages/greenhouse/bed.yaml",
    "packages/greenhouse/bed_soil_skip.yaml",
    GH_GP,
    "packages/lawn/irrigation.yaml",
    "packages/lawn/zone.yaml",
    "packages/lawn/gp.yaml",
    "packages/sim/fault.yaml",
}
API_ACTIONS = ["gp_run_zone", "gp_enqueue_zone", "gp_start_queue", "gp_full_cycle", "gp_stop_all", "gp_reset_watchdog"]
SCENARIO = REPO_ROOT / "tests" / "configs" / "gp_layer_sim.yaml"
SCENARIO_NAME = "gp-layer"


def _text(rel: str) -> str:
    return _strip_comments((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _load(rel: str) -> dict:
    data = load_esphome_yaml(REPO_ROOT / rel)
    assert isinstance(data, dict), rel
    return data


def _lambdas(node: object):
    """Yield the text of every lambda (`!lambda` values and `lambda:` keys)."""
    for d in _walk(node):
        if d.get("__tag__") == "lambda":
            yield d["value"]
        if "lambda" in d and isinstance(d["lambda"], str):
            yield d["lambda"]
        if isinstance(d.get("lambda"), dict) and d["lambda"].get("__tag__") == "lambda":
            yield d["lambda"]["value"]


# ------------------------------------------------------------------------------------------------------------- unit


@pytest.mark.unit
def test_no_engine_outside_adapter() -> None:
    entries = [REPO_ROOT / "garden-pilot.yaml", REPO_ROOT / "garden-pilot-sim.yaml"]
    paths = entries + [p for p in (REPO_ROOT / "packages").rglob("*.yaml") if p.is_file()]
    for path in paths:
        rel = path.relative_to(REPO_ROOT).as_posix()
        code = _strip_comments(path.read_text(encoding="utf-8"))
        assert not re.search(r"^sprinkler:|\bsprinkler\.\w+|gh_sprinkler", code, re.MULTILINE), rel
        if rel in ENGINE_FILES:
            continue
        assert not re.search(r"garden_zones\.|id\(gh_zones\)|\bgh_zones\b|\blawn_zones\b", code), f"{rel} names the engine"


@pytest.mark.unit
def test_callers_use_gp() -> None:
    for rel in CALLERS:
        code = _text(rel)
        data = _load(rel)
        keys = {k for d in _walk(data) for k in d if isinstance(k, str) and k.startswith(("gp.", "garden_zones.", "sprinkler."))}
        assert all(k.startswith("gp.") for k in keys), (rel, keys)
        assert not re.search(r"id\(gh_zones|gh_zones|board_relay|sprinkler", code), rel
        for target in (d["gp.run_zone"] for d in _walk(data) if "gp.run_zone" in d):
            assert target["id"] == "gp_greenhouse", rel
        reads = re.findall(r"id\((gp_\w+)\)", code)
        assert set(reads) <= {"gp_greenhouse", "gp_gh_seen", "gp_vt_seen", "gp_hist_seen", "gp_service_mode", "gp_confirm_result"}, (rel, reads)


@pytest.mark.unit
def test_lambdas_are_small() -> None:
    """Principle 1: no logic in lambdas. Irrigation lambdas are one-liners calling the model or gp::fmt."""
    for rel in CALLERS:
        for text in _lambdas(_load(rel)):
            lines = [line for line in text.splitlines() if line.strip()]
            if rel.endswith("screensaver_status.yaml") and "gp_greenhouse" not in text:
                continue  # the air/soil text line is not irrigation and predates this rule
            assert len(lines) <= 3, f"{rel}: lambda with {len(lines)} lines:\n{text}"
    for rel in (CORE_GP, CORE_GP_API, GH_GP):
        for text in _lambdas(_load(rel)):
            assert len([ln for ln in text.splitlines() if ln.strip()]) <= 1, f"{rel}: {text}"


@pytest.mark.unit
def test_lvgl_only_from_pollers() -> None:
    """LVGL is never touched from a gp trigger, an on_value / on_state callback or an API action (it can fire before
    LVGL is ready; see CLAUDE.md)."""
    # sensors_air_dht.yaml / sensors_soil.yaml predate this rule (on_value updating LVGL): follow-up in the task notes
    irrigation_files = {"irrigation.yaml", "irrigation_pump.yaml", "bed.yaml", "zone.yaml", "bed_soil.yaml", "bed_soil_skip.yaml", "gp.yaml", "gp_api.yaml"}
    for path in _yaml_files("packages"):
        data = load_esphome_yaml(path)
        for d in _walk(data):
            for key in ("on_alert_change", "on_watchdog_trip", "on_value", "on_state", "on_press", "on_turn_on", "on_turn_off"):
                if key in d and (key in ("on_alert_change", "on_watchdog_trip") or path.name in irrigation_files):
                    assert "lvgl." not in str(d[key]), f"{path.name}: lvgl.* under {key}"
            if isinstance(d.get("action"), str) and "then" in d:
                assert "lvgl." not in str(d["then"]), f"{path.name}: lvgl.* in the API action {d['action']}"
    # the pollers are the only gp readers of LVGL labels: each is an interval
    status = _load("packages/greenhouse/gp_lvgl_status.yaml")
    assert status["interval"] and all("lvgl." in str(i["then"]) for i in status["interval"])


@pytest.mark.unit
def test_gp_yaml_shape() -> None:
    config = _load(GH_GP)
    group, = config["gp"]["groups"]
    # on_zone_finished / on_stop are the hooks for the schedule (done marks, STOP settles the slots; task 019)
    assert {k: v for k, v in group.items() if k not in ("on_zone_finished", "on_stop")} == {
        "id": "gp_greenhouse", "name": "Greenhouse", "key": "greenhouse", "garden_zones_id": "gh_zones"
    }
    assert "gp_gh_zone_done" in str(group["on_zone_finished"])
    assert group["on_stop"] == [{"script.execute": "gp_gh_stopped"}]
    assert config["binary_sensor"][0]["condition"] == {"gp.watchdog_tripped": "gp_greenhouse"}
    assert config["binary_sensor"][0]["name"] == "Greenhouse watchdog" and config["binary_sensor"][0]["device_class"] == "problem"
    button = config["button"][0]
    assert button["name"] == "Greenhouse watchdog reset" and button["entity_category"] == "config"
    assert button["on_press"] == [{"gp.reset_watchdog": "gp_greenhouse"}]
    status = config["text_sensor"][0]
    assert status["id"] == "gp_greenhouse_status" and status["name"] == "Greenhouse status"
    # the group's generated watchdog component is gh_zones_watchdog: the template sensor needs another id
    assert config["binary_sensor"][0]["id"] != "gh_zones_watchdog"
    assert not re.search(r"!secret|GPIO\d+", (REPO_ROOT / GH_GP).read_text(encoding="utf-8"))

    core = _load(CORE_GP)
    assert core["gp"]["id"] == "gp_hub"
    assert core["external_components"] == [{"source": "${gp_root}/components", "components": ["gp", "gp_zone"]}]
    alert = core["text_sensor"][0]
    assert alert["id"] == "gp_alert_text" and alert["name"] == "Alert"
    assert not re.search(r"!secret|GPIO\d+", (REPO_ROOT / CORE_GP).read_text(encoding="utf-8"))

    # one generic action set for every group: `group` + 1-based `zone`
    api = _load(CORE_GP_API)["api"]["actions"]
    assert [a["action"] for a in api] == API_ACTIONS
    for action in api:
        assert action["variables"]["group"] == "string"
        assert len(action["then"]) == 1, "each body is one gp.* action"
        (name, body), = action["then"][0].items()
        assert name.startswith("gp.") and body["hub"] == "gp_hub"
        if "zone" in action["variables"]:
            assert action["variables"]["zone"] == "int" and action["variables"]["minutes"] == "int"
            assert body["zone"]["value"] == "return zone - 1;", "HA zones are 1-based"
    assert not re.search(r"!secret|GPIO\d+", (REPO_ROOT / CORE_GP_API).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_zone_switches_replace_engine_switches() -> None:
    """HA sees one switch per bed from the gp layer; the engine's own zone switch is internal."""
    bed = _load("packages/greenhouse/bed.yaml")
    assert bed["garden_zone"][0]["valve_switch"]["internal"] is True
    assert bed["gp_zone"][0]["name"] == bed["garden_zone"][0]["valve_switch"]["name"] == "${bed_name}"
    # settings entities are in the HA "Configuration" section
    stock = (REPO_ROOT / "components" / "garden_zones" / "__init__.py").read_text(encoding="utf-8")
    assert stock.count("entity_category=ENTITY_CATEGORY_CONFIG") >= 3  # enable switch, run duration number, auto advance
    irrigation = _load("packages/greenhouse/irrigation.yaml")
    assert "main_switch" not in irrigation["garden_zones"]["groups"][0]  # the gp-owned switch replaces it (task 021)


@pytest.mark.unit
def test_main_switch_through_gp() -> None:
    """The HA main switch is a template switch whose only actions are gp.* (task 021)."""
    config = _load("packages/greenhouse/gp.yaml")
    switches = [s for s in config["switch"] if s.get("name") == "Greenhouse irrigation"]
    assert len(switches) == 1
    sw = switches[0]
    assert sw["platform"] == "template" and sw["id"] == "gp_greenhouse_main_switch"
    assert sw["restore_mode"] == "DISABLED", "ALWAYS_OFF would run the OFF action (a STOP) at every boot"
    assert not sw.get("optimistic", False)
    assert sw["turn_on_action"] == [{"gp.full_cycle": "gp_greenhouse"}]
    assert sw["turn_off_action"] == [{"gp.stop_all": "gp_greenhouse"}]
    assert "gp_greenhouse" in sw["lambda"]


@pytest.mark.unit
def test_api_minutes_use_helper() -> None:
    api = _load("packages/core/gp_api.yaml")
    lambdas = [a["then"][0][k]["duration"] for a in api["api"]["actions"] for k in a["then"][0] if "duration" in a["then"][0][k]]
    assert len(lambdas) == 2
    for lam in lambdas:
        assert lam["value"].strip() == "return gp::api_seconds(minutes);"


@pytest.mark.unit
def test_stop_and_deferred_start_are_documented_and_wired() -> None:
    readme = (COMPONENT / "README.md").read_text(encoding="utf-8")
    for needle in ("gp.clear_queue", "on_stop", "deferred", "held back"):
        assert needle in readme, needle
    source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert '"gp.clear_queue"' in source and 'CONF_ON_STOP = "on_stop"' in source
    gp_yaml = (REPO_ROOT / GH_GP).read_text(encoding="utf-8")
    assert "on_stop:" in gp_yaml and "gp_gh_stopped" in gp_yaml
    assert (REPO_ROOT / "tests" / "cpp" / "test_gp_deferred_start.cpp").is_file()


@pytest.mark.unit
def test_pure_headers() -> None:
    for name in ("zone_model.h", "alerts.h", "format.h", "history.h", "engine.h", "deferred_start.h", "format_history.h"):
        text = (COMPONENT / name).read_text(encoding="utf-8")
        assert "esphome/" not in re.sub(r"namespace esphome::", "", text), f"{name} must stay free of ESPHome includes"
        assert not re.search(r'#include\s+"esphome/', text), name
    for path in [*COMPONENT.glob("*"), *ZONE_COMPONENT.glob("*")]:
        if path.suffix in {".h", ".py"}:
            head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:6])
            assert "MIT licence" in head, f"{path.name}: MIT notice missing"
            assert "garden_zones/" not in "\n".join(
                line for line in path.read_text(encoding="utf-8").splitlines() if line.lstrip().startswith("#include")
            ), path.name
    adapter = ADAPTER.read_text(encoding="utf-8")
    assert "General Public License v3" in adapter
    assert 'esphome/components/gp/engine.h' in adapter and "__has_include" in adapter


@pytest.mark.unit
def test_gp_zone_entries_are_lists() -> None:
    for path in _yaml_files("packages"):
        data = load_esphome_yaml(path)
        if isinstance(data, dict) and "gp_zone" in data:
            assert isinstance(data["gp_zone"], list), f"{path.name}: gp_zone must be a list item (dict entries merge)"
    assert "MULTI_CONF = True" in (ZONE_COMPONENT / "__init__.py").read_text(encoding="utf-8")


@pytest.mark.unit
def test_ha_disconnected_is_not_an_alert() -> None:
    """Human decision 2026-10-11: a quiet header icon, not an alert."""
    header = (COMPONENT / "gp.h").read_text(encoding="utf-8")
    assert "Home Assistant disconnected" not in header and "api_alert" not in header
    home = _load("packages/lvgl/page_home.yaml")
    icon = next(p for d in _walk(home) for item in d.get("widgets") or [] if isinstance(item, dict)
                for p in item.values() if isinstance(p, dict) and p.get("id") == "home_ha_icon")
    assert icon["hidden"] is True
    assert "is_connected" in _text("packages/greenhouse/gp_lvgl_status.yaml")


@pytest.mark.unit
def test_history_is_persisted() -> None:
    history = (COMPONENT / "history.h").read_text(encoding="utf-8")
    assert "HISTORY_LENGTH = 100" in history
    glue = (COMPONENT / "gp.h").read_text(encoding="utf-8")
    assert "make_preference<PersistBlob>" in glue and "pref_.save(" in glue and "pref_.load(" in glue


@pytest.mark.unit
def test_entries_have_gp_packages_in_order() -> None:
    for entry in ("garden-pilot.yaml", "garden-pilot-sim.yaml"):
        text = (REPO_ROOT / entry).read_text(encoding="utf-8")
        keys = re.findall(r"^  ([a-z0-9_]+): !include", text, re.MULTILINE)
        order = ["gh_irrigation", "gh_bed_3", "core_gp", "core_gp_api", "gh_gp", "gh_lvgl_page"]
        positions = [keys.index(k) for k in order]
        assert positions == sorted(positions), (entry, order)
        assert "gh_sprinkler_lvgl" not in text


@pytest.mark.unit
def test_no_stale_sprinkler_lvgl_name() -> None:
    for path in [*(REPO_ROOT / "packages").rglob("*.yaml"), REPO_ROOT / "garden-pilot.yaml", REPO_ROOT / "garden-pilot-sim.yaml",
                 REPO_ROOT / "CLAUDE.md", REPO_ROOT / "docs" / "SPEC.md", REPO_ROOT / "README.md", REPO_ROOT / "README.ru.md"]:
        assert "sprinkler_lvgl" not in path.read_text(encoding="utf-8"), path


@pytest.mark.unit
def test_scenario_config_shape() -> None:
    text = SCENARIO.read_text(encoding="utf-8")
    code = _strip_comments(text)
    assert "!secret" not in text
    assert not re.search(r"^(api|wifi|ota):|GPIO\d+", code, re.MULTILINE)
    config = load_esphome_yaml(SCENARIO)
    assert isinstance(config, dict)
    assert config["substitutions"] == {"gh_max_on_time": "125s", "gh_bed_run_max": "2", "gh_bed_run_initial": "1"}
    packages = config["packages"]
    assert packages["hardware"]["value"] == "hardware/sim.yaml"
    for key, path in (("gh_irrigation", "packages/greenhouse/irrigation.yaml"), ("core_gp", CORE_GP), ("gh_gp", GH_GP)):
        assert packages[key]["value"] == path
    assert "core_gp_api" not in packages
    assert len([k for k in packages if k.startswith("gh_bed_")]) == 3


# --------------------------------------------------------------------------------------------------- config / codegen


@pytest.mark.config
@pytest.mark.parametrize("version", VERSIONS)
def test_gp_codegen(version: str, tmp_path: Path) -> None:
    main_cpp = _generate(version, tmp_path)
    assert len(re.findall(r"gp::GpHub\(", main_cpp)) == 1
    assert len(re.findall(r"gp::GpGroup\(", main_cpp)) == 1
    assert len(re.findall(r"garden_zones::GardenZonesEngine\(", main_cpp)) == 1
    assert len(re.findall(r"gp::GpZoneSwitch\(", main_cpp)) == 3
    for action in API_ACTIONS:
        assert f'"{action}"' in main_cpp, action
    assert "esphome::gp::GpHub" in main_cpp or "gp::GpHub" in main_cpp
    # the zone maximum reaches gp (the 55 min default of gh_bed_run_max) and the engine has no main switch
    assert "gh_zones->set_zone_max_run(0, 3300)" in main_cpp
    assert "->set_main_switch(" not in main_cpp


@pytest.mark.config
def test_entity_names_with_gp(tmp_path: Path) -> None:
    from test_greenhouse_zones import _stage_device

    config = _stage_device(tmp_path)
    result = _esphome("pinned", "config", str(config), timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-4000:]
    # the engine's zone switch keeps the name but is internal; the gp switch is the visible one
    assert len(re.findall(r"name: Greenhouse bed 1\n", output)) >= 2
    assert "Greenhouse status" in output and "name: Alert" in output


# --------------------------------------------------------------------------------------------------------------- host


def _host_dir() -> Path:
    return REPO_ROOT / ".esphome" / "gp-layer-host" / _resolve("pinned")


@pytest.fixture(scope="module")
def gp_program() -> Path:
    _need_compiler()
    dest = _host_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for folder in ("hardware", "components"):
        shutil.copytree(REPO_ROOT / folder, dest / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (dest / "packages" / "core").mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "packages" / "greenhouse", dest / "packages" / "greenhouse", dirs_exist_ok=True)
    shutil.copy(REPO_ROOT / "packages" / "core" / "gp.yaml", dest / "packages" / "core" / "gp.yaml")
    config = dest / f"{SCENARIO_NAME}.yaml"
    shutil.copy(SCENARIO, config)
    result = _esphome("pinned", "compile", str(config), timeout=1800)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    program = dest / ".esphome" / "build" / SCENARIO_NAME / ".pioenvs" / SCENARIO_NAME / "program"
    assert program.is_file(), f"host program not found at {program}"
    return program


_LINE = re.compile(r"^t=(\d+) (.*)$")
_MARK = re.compile(r"^mark=(\w+) t=(\d+)$")


def _lines_between(messages: list[str], a: str, b: str) -> list[str]:
    """Texts of the `t=` lines logged between two marks; cut by log order, since lines share a millisecond."""
    pos = {m.group(1): i for i, m in enumerate(map(_MARK.match, messages)) if m}
    found = (_LINE.match(m) for m in messages[pos[a] + 1 : pos[b]])
    return [m.group(2) for m in found if m]


@pytest.mark.unit
def test_gp_layer_between_cuts_by_log_order() -> None:
    messages = ["t=5 early", "mark=a t=5", "t=5 in", "mark=b t=9", "t=9 late"]
    assert _lines_between(messages, "a", "b") == ["in"]


@pytest.mark.host
def test_gp_layer_host_scenario(gp_program: Path, tmp_path: Path) -> None:
    messages = _run_program(gp_program, tmp_path, timeout=420)
    assert "done" in messages, messages[-20:]
    lines = [(int(m.group(1)), m.group(2)) for m in map(_LINE.match, messages) if m]
    marks = {m.group(1): int(m.group(2)) for m in map(_MARK.match, messages) if m}

    def between(a: str, b: str) -> list[str]:
        return _lines_between(messages, a, b)

    def first_with(a: str, b: str, needle: str) -> bool:
        return any(needle in text for text in between(a, b))

    # 1. initial state: all idle, nothing queued, no alert, zone 4 absent
    assert any(t.startswith("B1:IDLE B2:IDLE B3:IDLE q=0 a=-") for t in between("s1_a", "s2_a")) or any(
        t.startswith("B1:IDLE B2:IDLE B3:IDLE q=0 a=-") for _, t in lines if _ < marks["s1_a"]
    ), lines[:3]
    assert "absent=1" in messages
    # the main switch (restore_mode DISABLED) must not run its OFF action, a gp STOP, at boot
    boot = messages[: next(i for i, m in enumerate(messages) if m.startswith("mark=s1_a "))]
    assert "stop_hook" not in boot, boot

    # 2. enqueue 0 and 2, start the queue: B1 then B3 run, never B2; the last duration of B1 is about 3 s
    queued = between("s2_a", "s2_b")
    assert any(t.startswith("B1:QUEUED(0) B2:IDLE B3:QUEUED(1)") for t in queued), queued
    assert "next=0" in messages
    runs = [t for t in between("s2_b", "s2_c") if "RUN(" in t]
    assert runs and all("B2:RUN" not in t for t in runs)
    assert first_with("s2_b", "s2_c", "B1:RUN(") and first_with("s2_b", "s2_c", "B3:RUN(")
    first_b1 = next(i for i, t in enumerate(between("s2_b", "s2_c")) if "B1:RUN(" in t)
    first_b3 = next(i for i, t in enumerate(between("s2_b", "s2_c")) if "B3:RUN(" in t)
    assert first_b1 < first_b3
    duration = next(int(m.split("=")[1]) for m in messages if m.startswith("last_duration_b1="))
    assert 2 <= duration <= 4, duration

    # 3. a manual run interrupts the queue run: B1 PAUSED, B2 runs, B1 runs again
    s3 = between("s3_a", "s3_b")
    paused = next(i for i, t in enumerate(s3) if "B1:PAUSED" in t and "B2:RUN" in t)
    resumed = next(i for i, t in enumerate(s3) if i > paused and "B1:RUN(" in t)
    assert paused < resumed

    # 4. a disabled bed shows OFF, also while queued
    assert first_with("s4_a", "s4_b", "B2:OFF"), between("s4_a", "s4_b")
    assert any("B2:OFF" in t and "q=" in t for t in between("s4_b", "s4_c"))
    assert first_with("s4_b", "s5_a", "B2:IDLE")

    # 5. the watchdog: B2 LOCKED, the wd alert on top, a run is refused, the reset clears everything
    s5 = between("s5_a", "s5_c")
    assert any("B2:LOCKED" in t and "a=wd:greenhouse" in t for t in s5), s5[-3:]
    assert "top_alert=Greenhouse: watchdog - B2 locked" in messages
    assert not first_with("s5_b", "s5_c", "B2:RUN"), "a locked bed refuses the run"
    assert any("B2:IDLE" in t and "a=-" in t for t in between("s5_c", "s6_a"))
    assert "relay2_off=1" in messages

    # 6. alerts: one entry per key, severity change, clear
    assert "alert_count=1" in messages and "alert_count_after_update=1" in messages and "alert_count_cleared=0" in messages
    assert "top_after_warn=warn text" in messages and "top_after_info=info text" in messages

    # 7. stop_all with clear_queue during a run: idle within 1.5 s, queue empty
    assert "stop_idle=1 stop_queue=0" in messages
    assert "history_ok=1" in messages

    # HA zone switch (gp_zone): boot state, ON follows the model, OFF stops, refused when locked or inhibited,
    # an immediate / delayed OFF never lets the valve open
    for needle in ("sw_boot_off=1", "locked_switch=1", "sw_on=1", "sw_off=1", "quick_off=1", "delay_off=1",
                   "inhibit_refused=1", "inhibit_service_ok=1", "inhibit_all_refused=1"):
        assert needle in messages, (needle, messages[-25:])

    # 9. when a zone counts as "done" (on_zone_finished `completed`, the schedule's per-zone mark)
    def fins(a: str, b: str) -> list[str]:
        ia = next(i for i, m in enumerate(messages) if m.startswith(f"mark={a} "))
        ib = next(i for i, m in enumerate(messages) if m.startswith(f"mark={b} "))
        return [m for m in messages[ia:ib] if m.startswith("fin ")]

    # a queue run that ends by itself is done
    assert fins("s9_a", "s9_b") == ["fin zone=0 completed=1"], fins("s9_a", "s9_b")
    # stop_all (even with clear_queue) is not a done mark; the schedule settles the slots on the group's on_stop
    assert fins("s9_b", "s9_c") == ["fin zone=1 completed=0"], fins("s9_b", "s9_c")
    # a manual run is never a done mark
    assert fins("s9_c", "s9_d") == ["fin zone=2 completed=0"], fins("s9_c", "s9_d")
    # Home Assistant turning off the main switch is a gp STOP (task 021): not a done mark, and the stop hook ran
    assert fins("s9_d", "s9_e") == ["fin zone=0 completed=0"], fins("s9_d", "s9_e")

    ia = next(i for i, m in enumerate(messages) if m.startswith("mark=s9_d "))
    ib = next(i for i, m in enumerate(messages) if m.startswith("mark=s9_e "))
    assert "stop_hook" in messages[ia:ib], "the main switch OFF is a full gp STOP"
    # 10. the cap on a long run, starts right after a stop, a single enqueue during a manual run
    for needle in ("clamp_ok=1", "start_after_stop=1", "cycle_after_stop=1", "enq_held=1", "enq_queued=1"):
        assert needle in messages, (needle, messages[-25:])
