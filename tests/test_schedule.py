"""Task 019: device-side watering schedules. Shape checks of the packages and the components, codegen on the device
entry, and a host scenario over the real packages (tests/configs/schedule_sim.yaml, three runs on one preferences
directory: the persisted per-zone done marks are the point)."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import time
import types
from pathlib import Path

import pytest

import conftest
from conftest import REPO_ROOT, load_esphome_yaml, require_faketime_or_none
from test_garden_zones import _need_compiler, _resolve, _run_program
from test_greenhouse_zones import VERSIONS, _esphome, _generate
from test_layout import _strip_comments
from test_screens import _walk

HUB = REPO_ROOT / "components" / "garden_schedule"
SLOT = REPO_ROOT / "components" / "garden_schedule_slot"
SCHEDULE_PKG = "packages/greenhouse/schedule.yaml"
SLOT_PKG = "packages/greenhouse/schedule_slot.yaml"
SCENARIO = REPO_ROOT / "tests" / "configs" / "schedule_sim.yaml"
SCENARIO_NAME = "schedule-test"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _load(rel: str) -> dict:
    data = load_esphome_yaml(REPO_ROOT / rel)
    assert isinstance(data, dict), rel
    return data


def _text(rel: str) -> str:
    return _strip_comments((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


# ------------------------------------------------------------------------------------------------------------- unit


@pytest.mark.unit
def test_slot_package_shape() -> None:
    config = _load(SLOT_PKG)
    raw = (REPO_ROOT / SLOT_PKG).read_text(encoding="utf-8")
    assert not re.search(r"lambda|!secret|GPIO\d+", _strip_comments(raw))

    switches = _by_id(config["switch"])
    assert set(switches) == {"gh_sched${slot}_enabled", *(f"gh_sched${{slot}}_day_{d}" for d in DAYS)}
    enabled = switches["gh_sched${slot}_enabled"]
    assert enabled["restore_mode"] == "RESTORE_DEFAULT_OFF" and enabled["name"] == "Greenhouse schedule ${slot}"
    for day in DAYS:  # days are 7 switches, default ON (a new slot runs daily)
        sw = switches[f"gh_sched${{slot}}_day_{day}"]
        assert sw["restore_mode"] == "RESTORE_DEFAULT_ON" and sw["name"] == f"Greenhouse schedule ${{slot}} {day.capitalize()}"
    start, = config["datetime"]
    assert start["id"] == "gh_sched${slot}_start" and start["type"] == "time" and start["restore_value"] is True
    assert start["initial_value"] == "${start}"
    zones, = config["text"]
    assert zones["id"] == "gh_sched${slot}_zones" and zones["initial_value"] == "all" and zones["restore_value"] is True
    assert zones["pattern"] == "^(all|[1-9][0-9]?( [1-9][0-9]?)*)$" and zones["max_length"] == 47
    mult, = config["number"]
    assert mult["id"] == "gh_sched${slot}_multiplier" and mult["initial_value"] == 100 and mult["restore_value"] is True
    assert (mult["min_value"], mult["max_value"], mult["step"]) == (10, 200, 10)

    # every slot setting is in the HA "Configuration" section and restored
    everything = [*config["switch"], *config["datetime"], *config["text"], *config["number"]]
    assert len(everything) == 11
    assert all(item["entity_category"] == "config" and item["optimistic"] is True for item in everything)

    items = config["garden_schedule_slot"]
    assert isinstance(items, list) and len(items) == 1, "a list item (dict entries of two slots would merge)"
    item = items[0]
    assert item["schedule"] == "gh_schedule" and item["slot"] == "${slot}"
    assert item["days_ids"] == [f"gh_sched${{slot}}_day_{d}" for d in DAYS]
    declared = {*switches, start["id"], zones["id"], mult["id"]}
    referenced = {item[k] for k in ("enabled_id", "start_id", "zones_id", "multiplier_id")} | set(item["days_ids"])
    assert referenced == declared


@pytest.mark.unit
def test_schedule_package_shape() -> None:
    config = _load(SCHEDULE_PKG)
    raw = (REPO_ROOT / SCHEDULE_PKG).read_text(encoding="utf-8")
    assert not re.search(r"!secret|GPIO\d+", _strip_comments(raw))
    assert config["substitutions"] == {"gh_schedule_catch_up_window": "60min"}
    assert config["external_components"] == [
        {"source": "components", "components": ["garden_schedule", "garden_schedule_slot"]}
    ]
    hub, = config["garden_schedule"]
    assert hub["id"] == "gh_schedule" and hub["catch_up_window"] == "${gh_schedule_catch_up_window}"
    assert hub["master_switch_id"] == "gh_schedules_on"
    assert hub["skip_if"] == [{"condition": {"gp.inhibited": "gp_greenhouse"}, "reason": "service mode"}]
    # on_run talks to the gp_* layer only
    names = [next(iter(step)) for step in hub["on_run"]]
    assert names == ["gp.enqueue_zones", "gp.start_queue"]
    for node in _walk(hub["on_run"]):
        for value in node.values():
            if isinstance(value, dict) and value.get("__tag__") == "lambda":
                assert value["value"] in ("return zone_mask;", "return multiplier_pct;"), value
    # entities
    master, = config["switch"]
    assert master["id"] == "gh_schedules_on" and master["name"] == "Greenhouse schedules"
    assert master["restore_mode"] == "RESTORE_DEFAULT_ON"  # the slots themselves default OFF
    sensors = {s["id"]: s for s in config["text_sensor"]}
    assert sensors["gh_next_run"]["device_class"] == "timestamp" and sensors["gh_next_run"]["name"] == "Greenhouse next run"
    assert sensors["gh_next_run_text"]["name"] == "Greenhouse next run text"
    assert sensors["gh_last_schedule"]["name"] == "Greenhouse last schedule"
    # the done mark comes from the gp hook script (extended here)
    scripts = {item["id"]["value"]: item for item in config["script"]}
    assert set(scripts) == {"gp_gh_zone_done", "gp_gh_stopped"}
    assert all(item["id"]["__tag__"] == "extend" for item in scripts.values())
    assert "garden_schedule.zone_done" in str(scripts["gp_gh_zone_done"]["then"])
    # a user STOP / service mode settles the slots and clears the engine queue (decision 1, 2026-10-11)
    assert [next(iter(step)) for step in scripts["gp_gh_stopped"]["then"]] == ["garden_schedule.cancel_pending", "gp.clear_queue"]


@pytest.mark.unit
def test_no_engine_and_no_cron_in_schedules() -> None:
    """Principle 2: schedules reach irrigation through gp_* only; no compile-time cron triggers for watering."""
    files = [SCHEDULE_PKG, SLOT_PKG, *(p.relative_to(REPO_ROOT).as_posix() for p in [*HUB.glob("*"), *SLOT.glob("*")]
                                       if p.suffix in {".h", ".py", ".md"})]
    for rel in files:
        code = _text(rel) if rel.endswith(".yaml") else (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"garden_zones\.|sprinkler\.|garden_zones::|gh_zones|board_relay", code), rel
    for path in (REPO_ROOT / "packages").rglob("*.yaml"):
        assert not re.search(r"^\s*(-\s+)?on_time:", _strip_comments(path.read_text(encoding="utf-8")), re.MULTILINE), path.name


@pytest.mark.unit
def test_entry_includes_schedule() -> None:
    for entry in ("garden-pilot.yaml", "garden-pilot-sim.yaml"):
        packages = _load(entry)["packages"]
        keys = list(packages)
        assert packages["gh_schedule"]["value"] == SCHEDULE_PKG
        slots = [k for k in keys if k.startswith("gh_schedule_slot_")]
        assert slots == ["gh_schedule_slot_1", "gh_schedule_slot_2"], entry
        numbers = [packages[k]["value"]["vars"]["slot"] for k in slots]
        assert numbers == ["1", "2"] and len(set(numbers)) == len(numbers)
        for k in slots:
            assert packages[k]["value"]["file"] == SLOT_PKG
        # after the gp_* layer, before the optional touch overlay; the slots follow the hub in order
        assert keys.index("gh_gp") < keys.index("gh_schedule") < keys.index("gh_schedule_slot_1") < keys.index("gh_schedule_slot_2")
        assert keys.index("gh_valve_test") < keys.index("gh_schedule")


def _load_hub():
    spec = importlib.util.spec_from_file_location("gs_hub_under_test", HUB / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_schedule_component_python() -> None:
    import esphome.config_validation as cv

    hub = _load_hub()
    slot = lambda hub_id, n: {hub.CONF_SCHEDULE: types.SimpleNamespace(id=hub_id), hub.CONF_SLOT: n}  # noqa: E731
    assert hub.check_slots("h", [slot("h", 1), slot("h", 2), slot("other", 1)]) == [1, 2]
    with pytest.raises(cv.Invalid, match="at most 8"):
        hub.check_slots("h", [slot("h", n) for n in range(1, 10)])
    assert hub.check_slots("h", [slot("h", n) for n in range(1, 9)]) == list(range(1, 9))
    with pytest.raises(cv.Invalid, match="duplicate"):
        hub.check_slots("h", [slot("h", 1), slot("h", 1)])
    # catch-up window: 0 .. 6 h
    assert hub._catch_up_window("60min").total_minutes == 60
    assert hub._catch_up_window("6h").total_minutes == 360
    assert hub._catch_up_window("0s").total_minutes == 0
    with pytest.raises(cv.Invalid):
        hub._catch_up_window("7h")
    # the slot schema: 1..8, exactly seven day switches
    source = (SLOT / "__init__.py").read_text(encoding="utf-8")
    assert "cv.int_range(min=1, max=MAX_SLOTS)" in source and "cv.Length(min=7, max=7)" in source
    assert hub.MAX_SLOTS == 8 and "MULTI_CONF = True" in source


@pytest.mark.unit
def test_pure_core_and_licences() -> None:
    core = (HUB / "schedule_core.h").read_text(encoding="utf-8")
    assert not re.search(r'#include\s+"esphome/', core), "schedule_core.h must stay free of ESPHome includes"
    for path in [*HUB.glob("*"), *SLOT.glob("*")]:
        if path.suffix in {".h", ".py"}:
            head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:6])
            assert "MIT licence" in head, f"{path.name}: MIT notice missing"
    assert (REPO_ROOT / "tests" / "cpp" / "test_schedule.cpp").is_file()


@pytest.mark.unit
def test_ui_texts_are_ascii() -> None:
    """The next-run text goes to 26 px LVGL labels: built-in fonts have ASCII only."""
    for name in ("garden_schedule.h", "schedule_core.h"):
        text = (HUB / name).read_text(encoding="utf-8")
        for literal in re.findall(r'"([^"]*)"', text):
            assert literal.isascii(), (name, literal)
    assert '"--:--"' in (HUB / "garden_schedule.h").read_text(encoding="utf-8")
    assert '"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"' in (HUB / "schedule_core.h").read_text(encoding="utf-8")


@pytest.mark.unit
def test_schedule_scenario_config_shape() -> None:
    text = SCENARIO.read_text(encoding="utf-8")
    code = _strip_comments(text)
    assert "!secret" not in text
    assert not re.search(r"^(api|wifi|ota):|GPIO\d+", code, re.MULTILINE)
    config = load_esphome_yaml(SCENARIO)
    assert isinstance(config, dict)
    packages = config["packages"]
    for key, path in (("gh_schedule", SCHEDULE_PKG), ("core_gp", "packages/core/gp.yaml"), ("gh_gp", "packages/greenhouse/gp.yaml")):
        assert packages[key]["value"] == path
    assert [k for k in packages if k.startswith("gh_schedule_slot_")] == [
        "gh_schedule_slot_1",
        "gh_schedule_slot_2",
        "gh_schedule_slot_3",
    ]


# --------------------------------------------------------------------------------------------------- config / codegen


@pytest.mark.config
@pytest.mark.parametrize("version", VERSIONS)
def test_schedule_codegen(version: str, tmp_path: Path) -> None:
    main_cpp = _generate(version, tmp_path)
    assert len(re.findall(r"garden_schedule::GardenSchedule\(", main_cpp)) == 1
    assert len(re.findall(r"gh_schedule->add_slot\(", main_cpp)) == 2
    assert "garden_schedule::RunTrigger(" in main_cpp
    assert "gp::EnqueueZonesAction" in main_cpp and "gp::InhibitedCondition" in main_cpp
    assert "garden_schedule::ZoneDoneAction" in main_cpp
    assert "garden_schedule::CancelPendingAction" in main_cpp and "gp::StopTrigger(" in main_cpp
    assert "gp::ClearQueueAction" in main_cpp
    assert "gh_schedule->set_catch_up_window(60)" in main_cpp
    # the schedule header never names the engine
    assert "garden_zones" not in (HUB / "garden_schedule.h").read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------- host


def _align_offset(now_epoch: float, target_second: int, previous: int) -> int:
    """Smallest clock offset (whole seconds) >= `previous` that puts `now_epoch + offset` in second `target_second` of
    a minute. Offsets never decrease, so the faked clock stays continuous between the phases of the scenario."""
    offset = previous
    while int(now_epoch + offset) % 60 != target_second:
        offset += 1
    return offset


@pytest.mark.unit
def test_align_offset() -> None:
    for now in (1_700_000_000.0, 1_700_000_017.9, 1_700_000_059.99, 1_700_000_060.0):
        for target in (0, 24, 40, 59):
            for previous in (0, 5, 61, 125):
                result = _align_offset(now, target, previous)
                assert previous <= result < previous + 60
                assert int(now + result) % 60 == target
    # a larger previous offset keeps monotonicity: it wraps to the next minute instead of going back
    natural = _align_offset(1_700_000_000.0, 24, 0)
    assert _align_offset(1_700_000_000.0, 24, natural + 1) == natural + 60


@pytest.mark.unit
def test_faketime_required_in_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conftest, "FAKETIME_GLOBS", ["/nonexistent/faketime/libfaketime.so.1"])
    monkeypatch.delenv("GP_REQUIRE_FAKETIME", raising=False)
    monkeypatch.delenv("GP_FAKETIME_LIB", raising=False)
    assert require_faketime_or_none() is None
    monkeypatch.setenv("GP_REQUIRE_FAKETIME", "1")
    with pytest.raises(pytest.fail.Exception, match="libfaketime not found"):
        require_faketime_or_none()


def _host_dir() -> Path:
    return REPO_ROOT / ".esphome" / "schedule-host" / _resolve("pinned")


@pytest.fixture(scope="module")
def schedule_program() -> Path:
    _need_compiler()
    dest = _host_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for folder in ("hardware", "components"):
        shutil.copytree(REPO_ROOT / folder, dest / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (dest / "packages" / "core").mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "packages" / "greenhouse", dest / "packages" / "greenhouse", dirs_exist_ok=True)
    for name in ("gp.yaml", "time_host.yaml"):
        shutil.copy(REPO_ROOT / "packages" / "core" / name, dest / "packages" / "core" / name)
    config = dest / f"{SCENARIO_NAME}.yaml"
    shutil.copy(SCENARIO, config)
    result = _esphome("pinned", "compile", str(config), timeout=1800)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    program = dest / ".esphome" / "build" / SCENARIO_NAME / ".pioenvs" / SCENARIO_NAME / "program"
    assert program.is_file(), f"host program not found at {program}"
    return program


_REL = re.compile(r"^rel t=(\d+) sec=(\d+) r1=(\d) r2=(\d) r3=(\d)$")


def _relays(messages: list[str]) -> list[tuple[int, int, int, int, int]]:
    return [tuple(int(g) for g in m.groups()) for m in map(_REL.match, messages) if m]  # (t, sec, r1, r2, r3)


def _value(messages: list[str], key: str) -> str:
    return next(m.split("=", 1)[1] for m in messages if m.startswith(key + "="))


class _Clock:
    """Starts the host program at a chosen second of the minute through libfaketime (relative offset, monotonic clock
    left real, offsets never decrease). The scenario waits for minute boundaries (the slot granularity is one minute):
    aligned, those waits are short and the same every time. Without libfaketime it returns no env and the scenario runs
    on the real clock exactly as before (slow, random waits, same assertions)."""

    def __init__(self) -> None:
        self.library = require_faketime_or_none()
        self.offset = 0

    def check_shifted(self, first_on_ms: int, launched: float) -> None:
        """Started at second 22, the slot (next minute boundary) opens its first valve ~38 s after the start; on the
        real clock it would be a random 33-93 s. Under GP_REQUIRE_FAKETIME=1 (CI) a library that does not shift the
        program's clock must not pass silently."""
        # `t` is the program's CLOCK_MONOTONIC in ms (kept real), `launched` is time.monotonic() before the start.
        if self.library is not None and os.environ.get("GP_REQUIRE_FAKETIME") == "1":
            elapsed = first_on_ms / 1000 - launched
            assert 30 <= elapsed <= 50, f"first valve {elapsed:.1f} s after the start: libfaketime did not shift the clock?"

    def env(self, target_second: int | None = None) -> dict[str, str] | None:
        if self.library is None:
            return None
        if target_second is not None:
            self.offset = _align_offset(time.time(), target_second, self.offset)
        return {
            "LD_PRELOAD": self.library,
            "FAKETIME": f"+{self.offset}",
            "FAKETIME_DONT_FAKE_MONOTONIC": "1",
        }


@pytest.mark.host
def test_schedule_host_scenario(schedule_program: Path, tmp_path: Path) -> None:
    prefs = tmp_path / "prefs"
    prefs.mkdir()
    clock = _Clock()
    # Phases 1 and 4 compute `now + 90 s` ~3 s after the start; at second 22 that is ~25 s, so the slot starts ~35 s
    # later. Phase 5 waits for second 20 after ~35 s of other steps, hence a start at second 42 (headroom for slower runners). Phases 2 and 3 keep
    # the offset of phase 1.

    # phase 1: configure slot 1, wait for the fire, kill the program in the middle of zone 2
    launched = time.monotonic()
    one = _run_program(schedule_program, prefs, timeout=240, env_extra=clock.env(22))
    assert "done" in one, one[-20:]
    assert "phase=1" in one
    start = _value(one, "start")
    next_line = next(m for m in one if m.startswith("next_before="))
    before, expect = re.match(r"next_before=(.*) expect=(.*)$", next_line).groups()
    assert before == expect and re.match(r"^[A-Z][a-z]{2} \d\d:\d\d$", before), next_line
    assert before.endswith(start)
    assert re.match(r"^\d{4}-\d\d-\d\dT" + re.escape(start) + r":00[+-]\d\d:\d\d$", _value(one, "next_iso")), one
    assert "idle_before=1" in one
    rel = _relays(one)
    first_on = next(row for row in rel if row[2] == 1)
    clock.check_shifted(first_on[0], launched)
    assert first_on[1] <= 6, f"slot 1 fired {first_on[1]} s after the start minute"
    assert all(row[4] == 0 for row in rel), "slot 2 is disabled: zone 3 never runs"
    assert _value(one, "last").endswith("#1 ran")
    after, expect_tomorrow = re.match(r"next_after=(.*) expect=(.*)$", next(m for m in one if m.startswith("next_after="))).groups()
    assert after == expect_tomorrow, "after the run the next run is tomorrow's"
    assert "mid_zone2=1" in one, "zone 1 completed (relay off) before zone 2 started"
    # zone 1 ran once for about the 10 % duration, then zone 2 (cut by the kill)
    zone1_on = [row for row in rel if row[2] == 1]
    assert len(zone1_on) == 1

    # phase 2: restart inside the catch-up window: only the interrupted zone 2 runs again
    two = _run_program(schedule_program, prefs, timeout=120, env_extra=clock.env())
    assert "done" in two, two[-20:]
    assert "phase=2" in two
    rel2 = _relays(two)
    assert any(row[3] == 1 for row in rel2), "the interrupted zone 2 runs again"
    assert all(row[2] == 0 for row in rel2), "zone 1 completed before the kill and must not run again"
    assert all(row[4] == 0 for row in rel2)
    assert _value(two, "last").endswith("ran (catch-up)"), two

    # phase 3: both zones are done: nothing runs
    three = _run_program(schedule_program, prefs, timeout=120, env_extra=clock.env())
    assert "done" in three, three[-20:]
    assert "phase=3" in three
    assert _relays(three) == [] and "quiet=1" in three

    # phase 4: STOP in the middle of slot 2 settles the slot ("stopped"), nothing stays queued
    launched = time.monotonic()
    four = _run_program(schedule_program, prefs, timeout=240, env_extra=clock.env(22))
    assert "done" in four, four[-20:]
    assert "phase=4" in four
    rel4 = _relays(four)
    clock.check_shifted(next(row for row in rel4 if row[2] == 1)[0], launched)
    assert any(row[2] == 1 for row in rel4) and any(row[3] == 1 for row in rel4), "slot 2 ran zones 1 and 2"
    assert all(row[4] == 0 for row in rel4)
    assert "stopped_idle=1 queue=0" in four, four[-10:]
    assert _value(four, "last").endswith("#2 stopped"), four

    # phase 5: restart inside the window: the stopped slot does not resume (decision 1)
    five = _run_program(schedule_program, prefs, timeout=420, env_extra=clock.env(42))
    assert "done" in five, five[-30:]
    assert "phase=5" in five
    assert "quiet=1 queue=0" in five, "a STOP settles the slot: nothing runs after a restart"
    # (a) a deferred queue start is cancelled by STOP
    assert "deferred=1 enq=1 queue=0" in five, "enqueue + start during a manual cycle are held back, nothing is queued"
    assert "cycle_stop_quiet=1 queue=0 deferred=0 enq=0" in five, five
    # (b) a slot firing during a manual full cycle is queued after it (decision 2)
    at_fire = next(m for m in five if m.startswith("at_fire "))
    assert "r2=1" in at_fire and "deferred=1 enq=1 queue=0" in at_fire, at_fire
    cycle_t = int(re.match(r"cycle_start t=(\d+)", next(m for m in five if m.startswith("cycle_start "))).group(1))
    rel5 = [row for row in _relays(five) if row[0] >= cycle_t]
    # relay changes after the cycle started: cycle bed 1, cycle bed 2, then the slot's bed 1 and bed 2
    seq = [(i, row) for i, row in enumerate(rel5)]
    events = []
    previous = (0, 0, 0)
    for t, _sec, r1, r2, r3 in rel5:
        for number, (old, new) in enumerate(zip(previous, (r1, r2, r3)), start=1):
            if old != new:
                events.append((number, new, t))
        previous = (r1, r2, r3)
    # the engine hands over between zones with a brief overlap (next valve opens before the previous closes):
    # check each valve's on/off sequence and the run order, not a strict global interleaving
    handover = 500
    runs = {}
    for number in (1, 2):
        values = [(v, t) for n, v, t in events if n == number]
        assert [v for v, _t in values] == [1, 0, 1, 0], (number, events, seq)
        runs[number] = [(values[0][1], values[1][1]), (values[2][1], values[3][1])]
    assert {n for n, _v, _t in events} == {1, 2}, (events, seq)
    order = [runs[1][0], runs[2][0], runs[1][1], runs[2][1]]  # cycle bed 1, cycle bed 2, slot bed 1, slot bed 2
    for (_on, off), (next_on, _next_off) in zip(order, order[1:]):
        assert next_on >= off - handover, ("runs overlap more than the handover", events, seq)
    assert [r[0] for r in order] == sorted(r[0] for r in order), (events, seq)
    cycle_bed1, cycle_bed2, queued_bed1, queued_bed2 = (off - on for on, off in order)
    assert cycle_bed1 >= 55000 and cycle_bed2 >= 55000, "the cycle runs to its end undisturbed"
    assert 3000 <= queued_bed1 <= 12000 and 3000 <= queued_bed2 <= 12000, "the slot's beds run at 10 %"
    assert order[2][0] >= order[1][1] + 4000 - handover, "the slot's zones start only after the cycle ended"
    assert "end_quiet=1 queue=0 deferred=0" in five, five
    assert _value(five, "last").endswith("#3 ran"), five
