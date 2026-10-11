"""Task 014: the greenhouse runs on garden_zones (device + emulator). Shape checks, config matrix helpers, codegen and a
host scenario over the real packages (tests/configs/greenhouse_zones_sim.yaml)."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_ROOT, load_esphome_yaml
from test_garden_zones import _need_compiler, _resolve, _run_program
from test_layout import _strip_comments

COMPONENT = REPO_ROOT / "components" / "garden_zones"
IRRIGATION = REPO_ROOT / "packages" / "greenhouse" / "irrigation.yaml"
BED = REPO_ROOT / "packages" / "greenhouse" / "bed.yaml"
FAULT = REPO_ROOT / "packages" / "sim" / "fault.yaml"
SCENARIO = REPO_ROOT / "tests" / "configs" / "greenhouse_zones_sim.yaml"
SCENARIO_NAME = "greenhouse-zones"
VERSIONS = ["pinned", "minimum"]


def _rules():
    spec = importlib.util.spec_from_file_location("gz_safety_rules_014", COMPONENT / "safety_rules.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _code(path: Path) -> str:
    return _strip_comments(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------------------- unit


@pytest.mark.unit
def test_irrigation_shape() -> None:
    config = load_esphome_yaml(IRRIGATION)
    assert isinstance(config, dict)
    assert "sprinkler" not in config
    assert config["external_components"] == [{"source": "components", "components": ["garden_zones", "garden_zone"]}]
    assert config["substitutions"] == {
        "gh_max_parallel": "1",
        "gh_max_on_time": "60min",
        "gh_bed_run_max": "55",
        "gh_bed_run_initial": "5",
    }
    groups = config["garden_zones"]["groups"]
    assert len(groups) == 1
    group = groups[0]
    assert group["id"] == "gh_zones" and group["name"] == "Greenhouse"
    assert group["max_parallel"] == "${gh_max_parallel}" and group["max_on_time"] == "${gh_max_on_time}"
    assert group["main_switch"]["name"] == "Greenhouse irrigation"
    assert group["main_switch"]["id"] == "gh_zones_main_switch"
    assert group["auto_advance_switch"]["name"] == "Greenhouse auto advance"
    assert group["on_watchdog_trip"], "a trip must be logged"
    assert "pump_switch_id" not in group, "gravity-fed greenhouse: no pump"
    # the watchdog sensor and reset button moved to the gp layer (packages/greenhouse/gp.yaml, task 018)
    assert "binary_sensor" not in config and "button" not in config


@pytest.mark.unit
def test_bed_max_fits_watchdog() -> None:
    rules = _rules()
    subs = load_esphome_yaml(IRRIGATION)["substitutions"]
    run_ms = rules.longest_run_ms(None, int(subs["gh_bed_run_max"]), "min")
    limit_ms = 60 * 60 * 1000
    assert subs["gh_max_on_time"] == "60min"
    assert rules.zone_limit_error("bed", run_ms, 0, limit_ms, from_number=True) is None
    assert int(subs["gh_bed_run_initial"]) <= int(subs["gh_bed_run_max"])
    assert rules.zone_limit_error("bed", rules.longest_run_ms(None, 60, "min"), 0, limit_ms, from_number=True) is not None


@pytest.mark.unit
def test_no_stock_sprinkler_in_device_files() -> None:
    paths = [REPO_ROOT / "garden-pilot.yaml", REPO_ROOT / "garden-pilot-sim.yaml"]
    for folder in ("packages", "hardware"):
        paths += sorted((REPO_ROOT / folder).rglob("*.yaml"))
    for path in paths:
        code = _code(path)
        where = path.relative_to(REPO_ROOT)
        assert not re.search(r"^sprinkler:", code, re.MULTILINE), where
        assert not re.search(r"\bsprinkler\.\w+", code), where
        assert "gh_sprinkler" not in code.replace("gh_sprinkler_lvgl", ""), where


@pytest.mark.unit
def test_sim_fault_is_sim_only() -> None:
    assert "fault injection" in FAULT.read_text(encoding="utf-8").lower()
    config = load_esphome_yaml(FAULT)
    assert isinstance(config, dict)
    switches = config["switch"]
    assert [sw["id"] for sw in switches] == ["sim_rogue_relay_1"]
    assert switches[0]["turn_on_action"] == [{"switch.turn_on": "board_relay_1"}]
    included = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in [REPO_ROOT / "garden-pilot.yaml", REPO_ROOT / "garden-pilot-sim.yaml", *REPO_ROOT.glob("packages/**/*.yaml")]
        if "packages/sim/fault.yaml" in path.read_text(encoding="utf-8")
    ]
    assert included == ["garden-pilot-sim.yaml"], included


@pytest.mark.unit
def test_sim_subst_parsing(tmp_path: Path) -> None:
    """script/sim turns GP_SIM_SUBST into `-s key value` pairs (checked with a stub `script/_esphome`)."""
    stage = tmp_path / "repo"
    (stage / "script").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "script" / "sim", stage / "script" / "sim")
    (stage / "script" / "_esphome").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$STUB_OUT"\n', encoding="utf-8")
    (stage / "garden-pilot-sim.yaml").write_text("x: 1\n", encoding="utf-8")
    (stage / "secrets.example.yaml").write_text("y: 1\n", encoding="utf-8")
    out = tmp_path / "args.txt"
    env = {**os.environ, "DISPLAY": ":99", "GP_SIM_SUBST": "a=1 b=2s", "STUB_OUT": str(out)}
    result = subprocess.run(["sh", "script/sim"], cwd=stage, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    args = out.read_text(encoding="utf-8").split()
    assert args[:6] == ["-s", "a", "1", "-s", "b", "2s"], args
    assert args[6] == "run"
    env["GP_SIM_SUBST"] = "oops"
    bad = subprocess.run(["sh", "script/sim"], cwd=stage, env=env, capture_output=True, text=True, check=False)
    assert bad.returncode == 2


@pytest.mark.unit
def test_greenhouse_zones_config_shape() -> None:
    text = SCENARIO.read_text(encoding="utf-8")
    code = _strip_comments(text)
    assert "!secret" not in text
    assert not re.search(r"^(api|wifi|ota):|GPIO\d+", code, re.MULTILINE)
    config = load_esphome_yaml(SCENARIO)
    assert isinstance(config, dict)
    assert config["substitutions"] == {"gh_max_on_time": "125s", "gh_bed_run_max": "2", "gh_bed_run_initial": "1"}
    packages = config["packages"]
    assert packages["hardware"] == {"__tag__": "include", "value": "hardware/sim.yaml"}
    assert packages["gh_irrigation"] == {"__tag__": "include", "value": "packages/greenhouse/irrigation.yaml"}
    beds = [v["value"] for k, v in packages.items() if k.startswith("gh_bed_")]
    assert [b["file"] for b in beds] == ["packages/greenhouse/bed.yaml"] * 3
    assert [b["vars"]["relay"] for b in beds] == ["1", "2", "3"]


# --------------------------------------------------------------------------------------------------- config / codegen


def _stage_device(dest: Path, entry: str = "garden-pilot.yaml") -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for name in (entry, "packages", "hardware", "components"):
        source = REPO_ROOT / name
        if source.is_dir():
            shutil.copytree(source, dest / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy(source, dest / name)
    shutil.copy(REPO_ROOT / "secrets.example.yaml", dest / "secrets.yaml")
    return dest / entry


def _esphome(version: str, *args: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "script/_esphome", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "GP_ESPHOME": version},
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _generate(version: str, tmp_path: Path, *subst: str) -> str:
    config = _stage_device(tmp_path)
    args = [a for i in range(0, len(subst), 2) for a in ("-s", subst[i], subst[i + 1])]
    result = _esphome(version, *args, "compile", "--only-generate", str(config), timeout=900)
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    return (tmp_path / ".esphome" / "build" / "garden-pilot" / "src" / "main.cpp").read_text(encoding="utf-8")


@pytest.mark.config
@pytest.mark.parametrize("version", VERSIONS)
def test_greenhouse_zones_codegen(version: str, tmp_path: Path) -> None:
    main_cpp = _generate(version, tmp_path)
    assert "gh_zones_lane_0 = new" in main_cpp or "gh_zones_lane_0" in main_cpp
    assert "gh_zones_lane_1" not in main_cpp, "max_parallel 1: one lane"
    assert len(re.findall(r"garden_zones::GardenZonesGroup\(", main_cpp)) == 1
    assert len(re.findall(r"garden_zones::GroupWatchdog\(", main_cpp)) == 1
    assert len(re.findall(r"gh_zones_watchdog->add_zone\([^;]*, 3600000\);", main_cpp)) == 3
    assert main_cpp.count("->set_main_switch(") == 1 and main_cpp.count("->set_auto_advance_switch(") == 1
    assert "sprinkler::Sprinkler" not in main_cpp


@pytest.mark.config
def test_greenhouse_zones_codegen_parallel(tmp_path: Path) -> None:
    main_cpp = _generate("pinned", tmp_path, "gh_max_parallel", "all")
    for lane in ("gh_zones_lane_0", "gh_zones_lane_1", "gh_zones_lane_2"):
        assert lane in main_cpp
    assert "gh_zones_lane_3" not in main_cpp


@pytest.mark.config
def test_entity_names_kept(tmp_path: Path) -> None:
    config = _stage_device(tmp_path)
    result = _esphome("pinned", "config", str(config), timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-4000:]
    names = {m.strip().strip("'\"") for m in re.findall(r"^\s*name: (.+)$", output, re.MULTILINE)}
    expected = {
        "Greenhouse irrigation",
        "Greenhouse auto advance",
        *(f"Greenhouse bed {n}" for n in (1, 2, 3)),
        *(f"Greenhouse bed {n} enable" for n in (1, 2, 3)),
        *(f"Greenhouse bed {n} run duration" for n in (1, 2, 3)),
        "Greenhouse watchdog",
        "Greenhouse watchdog reset",
    }
    assert expected <= names, sorted(expected - names)
    irrigation_like = {
        n for n in names if n.startswith("Greenhouse") and re.search(r"irrigation|advance|bed|watchdog|valve|zone", n, re.I)
    }
    assert irrigation_like == expected, sorted(irrigation_like ^ expected)


# --------------------------------------------------------------------------------------------------------------- host


def _host_dir() -> Path:
    return REPO_ROOT / ".esphome" / "gh-zones-host" / _resolve("pinned")


@pytest.fixture(scope="module")
def scenario_program() -> Path:
    _need_compiler()
    dest = _host_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for folder in ("hardware", "components"):
        shutil.copytree(REPO_ROOT / folder, dest / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (dest / "packages").mkdir(exist_ok=True)
    shutil.copytree(REPO_ROOT / "packages" / "greenhouse", dest / "packages" / "greenhouse", dirs_exist_ok=True)
    (dest / "packages" / "core").mkdir(exist_ok=True)
    shutil.copy(REPO_ROOT / "packages" / "core" / "gp.yaml", dest / "packages" / "core" / "gp.yaml")
    config = dest / f"{SCENARIO_NAME}.yaml"
    shutil.copy(SCENARIO, config)
    result = _esphome("pinned", "compile", str(config), timeout=1800)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    program = dest / ".esphome" / "build" / SCENARIO_NAME / ".pioenvs" / SCENARIO_NAME / "program"
    assert program.is_file(), f"host program not found at {program}"
    return program


@pytest.mark.host
def test_greenhouse_zones_host_compile(scenario_program: Path) -> None:
    assert scenario_program.is_file()


_STATE = re.compile(r"t=(\d+) state=([01]{6})$")
_MARK = re.compile(r"mark=(\w+) t=(\d+)$")
_R1, _R2, _R3, _MAIN, _AA, _WD = range(6)


class _Timeline:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.marks = {m.group(1): int(m.group(2)) for m in map(_MARK.match, messages) if m}
        self.states = [(int(m.group(1)), m.group(2)) for m in map(_STATE.match, messages) if m]

    def window(self, start: str, end: str) -> list[tuple[int, str]]:
        """The state entries inside two marks, preceded by the state at the start (a state holds until the next entry)."""
        low, high = self.marks[start], self.marks[end]
        before = [s for s in self.states if s[0] <= low]
        first = [(low, before[-1][1])] if before else []
        return first + [s for s in self.states if low < s[0] <= high]

    def spans(self, bit: int, start: str, end: str) -> list[tuple[int, int]]:
        found, begin = [], None
        entries = self.window(start, end)
        for t, state in entries:
            if state[bit] == "1" and begin is None:
                begin = t
            elif state[bit] != "1" and begin is not None:
                found.append((begin, t))
                begin = None
        if begin is not None:
            found.append((begin, self.marks[end]))
        return found

    def rising(self, start: str, end: str) -> list[int]:
        order, previous = [], "000"
        for _, state in self.window(start, end):
            for bit in (_R1, _R2, _R3):
                if state[bit] == "1" and previous[bit] != "1":
                    order.append(bit)
            previous = state[:3]
        return order

    def ever(self, bit: int, start: str, end: str) -> bool:
        return any(state[bit] == "1" for _, state in self.window(start, end))


def _brief_overlap_only(timeline: _Timeline, start: str, end: str) -> bool:
    """Two relays on together are accepted stock behaviour for one loop pass: a single log entry, never two in a row."""
    run = 0
    for _, state in timeline.window(start, end):
        if state[:3].count("1") > 1:
            run += 1
            if run > 1:
                return False
        else:
            run = 0
    return True


@pytest.mark.host
def test_greenhouse_zones_host_scenario(scenario_program: Path, tmp_path: Path) -> None:
    messages = _run_program(scenario_program, tmp_path, timeout=420)
    assert "done" in messages, messages[-15:]
    line = _Timeline(messages)

    # 1. initial state
    assert "numbers 1 1 1" in messages and "tripped=0" in messages
    assert line.states[0][1] == "000000", line.states[0]

    # 2. main switch: bed 1 first, one valve at a time, main switch state follows; off closes everything
    assert line.rising("s2_a", "s2_b")[:1] == [_R1], line.rising("s2_a", "s2_b")
    assert not line.ever(_R2, "s2_a", "s2_b") and not line.ever(_R3, "s2_a", "s2_b")
    assert _brief_overlap_only(line, "s2_a", "s2_c")
    assert line.window("s2_a", "s2_b")[-1][1][_MAIN] == "1", "main switch state is on while running"
    last = line.window("s2_b", "s2_c")[-1][1]
    assert last[:3] == "000" and last[_MAIN] == "0", last

    # 3. auto advance off: the cycle stops after the current zone
    assert line.rising("s3_a", "s3_b")[:1] == [_R1]
    after = line.window("s3_b", "s3_c")
    assert all(state[:3] == "000" for _, state in after[1:]), after
    assert not line.ever(_R2, "s3_a", "s3_c") and not line.ever(_R3, "s3_a", "s3_c")
    assert line.window("s3_b", "s3_c")[-1][1][_AA] == "0"

    # 4. queue + manual run
    assert line.rising("s4_a", "s4_b") == [_R1, _R3], (line.rising("s4_a", "s4_b"), line.window("s3_c", "s4_b"), messages[-40:])
    assert not line.ever(_R2, "s4_a", "s4_b")
    assert line.rising("s4_b", "s4_c") == [_R1, _R2, _R1], line.rising("s4_b", "s4_c")
    assert "queue queued=1" in messages and "queue cleared=" in messages

    # 5. watchdog on the real bed package: a raw relay turn-on is cut at 125 s
    (span,) = line.spans(_R2, "s5_a", "s5_b")
    assert 124_800 < span[1] - span[0] <= 126_300, span
    assert line.window("s5_a", "s5_b")[-1][1][_WD] == "1"
    assert not line.ever(_R2, "s5_b", "s5_c"), "a locked bed is refused"
    assert line.window("s5_c", "s5_d")[-1][1][_WD] == "0", "the reset button clears the latch"
    (run,) = line.spans(_R2, "s5_d", "s5_e")
    assert 1_500 <= run[1] - run[0] <= 3_000, run

    # 6. valve-test-like sequence: shutdown, then a 10 s manual run without a trip
    (test_run,) = line.spans(_R3, "s6_a", "s6_b")
    assert 9_000 <= test_run[1] - test_run[0] <= 10_400, test_run
    assert not any(state[_WD] == "1" for _, state in line.window("s6_a", "s6_b"))

    # global: never two relays together (beyond a single brief entry), no relay on longer than the watchdog limit + margin
    first, last_mark = min(line.marks.values()), max(line.marks.values())
    assert _brief_overlap_only(line, "s2_a", "s6_b")
    for bit in (_R1, _R2, _R3):
        for begin, end in line.spans(bit, "s2_a", "s6_b"):
            assert end - begin <= 126_300, (bit, begin, end)
    assert first < last_mark
