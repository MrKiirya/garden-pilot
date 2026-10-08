"""components/garden_zones: fork hygiene, C++ unit tests, config on pinned + minimum ESPHome, host scenario."""

from __future__ import annotations

import difflib
import importlib.util
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest

from conftest import REPO_ROOT, load_esphome_yaml

COMPONENT = REPO_ROOT / "components" / "garden_zones"
ZONE_COMPONENT = REPO_ROOT / "components" / "garden_zone"
CONFIGS = REPO_ROOT / "tests" / "configs"
SIM_CONFIG = CONFIGS / "garden_zones_sim.yaml"
GROUPS_CONFIG = CONFIGS / "garden_zones_groups_sim.yaml"
ZONE_ENTRY = CONFIGS / "garden_zone_entry.yaml"
FORKED = ["__init__.py", "automation.h", "sprinkler.h", "sprinkler.cpp"]
NEW_FILES = ["groups.py", "lane_plan.py", "lanes.h", "group.h"]
ALL_FILES = [*FORKED, "queue_ops.h", *NEW_FILES, "LICENSE", "PATCHES.md", "README.md"]
BASE_TAG = "2026.9.1"
VERSIONS = ["pinned", "minimum"]


def _upstream_dir() -> Path:
    spec = importlib.util.find_spec("esphome")
    assert spec is not None and spec.submodule_search_locations, "esphome is not installed (run script/setup)"
    return Path(next(iter(spec.submodule_search_locations))) / "components" / "sprinkler"


def _patch_ids(text: str) -> list[str]:
    return re.findall(r"GZ-PATCH-BEGIN\(([A-Za-z0-9_-]+)\)", text)


# ---------------------------------------------------------------------------------------------- unit


@pytest.mark.unit
def test_fork_files_present() -> None:
    for name in ALL_FILES:
        assert (COMPONENT / name).is_file(), f"components/garden_zones/{name} is missing"
    licence = (COMPONENT / "LICENSE").read_text(encoding="utf-8")
    assert licence.lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    assert "Version 3, 29 June 2007" in licence
    for path in COMPONENT.rglob("*"):
        if path.suffix in {".h", ".cpp", ".c", ".hpp"}:
            assert not re.search(r"\bint\s+main\s*\(", path.read_text(encoding="utf-8")), f"main() in {path}"


@pytest.mark.unit
def test_fork_headers() -> None:
    for name in FORKED:
        head = "\n".join((COMPONENT / name).read_text(encoding="utf-8").splitlines()[:8])
        assert "esphome/components/sprinkler" in head, name
        assert BASE_TAG in head, name
        assert "PATCHES.md" in head, name
        assert "General Public License v3" in head or "GPLv3" in head, name
    assert "MIT" in "\n".join((COMPONENT / "__init__.py").read_text(encoding="utf-8").splitlines()[:8])
    helper_head = "\n".join((COMPONENT / "queue_ops.h").read_text(encoding="utf-8").splitlines()[:6])
    assert "General Public License v3" in helper_head


@pytest.mark.unit
def test_renamed_for_coexistence() -> None:
    forbidden = [
        r"namespace esphome::sprinkler",
        r'namespace\("sprinkler"\)',
        r'"sprinkler\.(?!h")',  # action strings; the file name sprinkler.h is kept on purpose
        r'TAG = "sprinkler"',
    ]
    for name in FORKED:
        text = (COMPONENT / name).read_text(encoding="utf-8")
        for pattern in forbidden:
            assert not re.search(pattern, text), f"{name}: {pattern}"
    assert 'namespace("garden_zones")' in (COMPONENT / "__init__.py").read_text(encoding="utf-8")


def _leading_comment_header(lines: list[str], marker: str) -> int:
    n = 0
    while n < len(lines) and lines[n].startswith(marker):
        n += 1
    if n and n < len(lines) and lines[n].strip() == "":
        n += 1
    return n


def _diff_problems(name: str) -> list[str]:
    upstream = (_upstream_dir() / name).read_text(encoding="utf-8").splitlines()
    fork = (COMPONENT / name).read_text(encoding="utf-8").splitlines()
    skip = _leading_comment_header(fork, "#" if name.endswith(".py") else "//")
    fork = fork[skip:]
    in_region: list[bool] = []
    inside = False
    for line in fork:
        if "GZ-PATCH-BEGIN(" in line:
            inside = True
            in_region.append(True)
        elif "GZ-PATCH-END(" in line:
            in_region.append(True)
            inside = False
        else:
            in_region.append(inside)
    normalised = [line.replace("garden_zones", "sprinkler") for line in fork]
    problems = []
    matcher = difflib.SequenceMatcher(None, upstream, normalised, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            near = in_region[j1 - 1] if j1 > 0 else False
            near = near or (in_region[j1] if j1 < len(in_region) else False)
            if not near:
                problems.append(f"{name}: upstream lines {i1 + 1}-{i2} removed outside a patch region")
            continue
        for j in range(j1, j2):
            if not in_region[j] and normalised[j].strip():
                problems.append(f"{name}: fork line {j + skip + 1} differs from upstream outside a patch region")
        if tag == "replace" and not any(in_region[j] for j in range(j1, j2)):
            problems.append(f"{name}: upstream lines {i1 + 1}-{i2} replaced outside a patch region")
    return problems


@pytest.mark.unit
def test_fork_diff_is_documented() -> None:
    patches = (COMPONENT / "PATCHES.md").read_text(encoding="utf-8")
    problems = []
    for name in FORKED:
        problems += _diff_problems(name)
    if problems:
        base = re.search(r"tag `([0-9.]+)`", patches)
        hint = ""
        if base and base.group(1) != BASE_TAG:
            hint = " (PATCHES.md and the tests disagree about the base tag)"
        pytest.fail(
            f"fork differs from the installed ESPHome sprinkler sources outside GZ-PATCH regions{hint}; "
            f"if ESPHome was bumped, re-port per PATCHES.md:\n" + "\n".join(problems[:40])
        )


@pytest.mark.unit
def test_patch_ids_documented() -> None:
    ids_in_code: set[str] = set()
    for name in FORKED:
        stack: list[str] = []
        for number, line in enumerate((COMPONENT / name).read_text(encoding="utf-8").splitlines(), start=1):
            begin = re.search(r"GZ-PATCH-BEGIN\(([A-Za-z0-9_-]+)\)", line)
            end = re.search(r"GZ-PATCH-END\(([A-Za-z0-9_-]+)\)", line)
            if begin:
                assert not stack, f"{name}:{number}: nested GZ-PATCH region"
                stack.append(begin.group(1))
                ids_in_code.add(begin.group(1))
            elif end:
                assert stack == [end.group(1)], f"{name}:{number}: GZ-PATCH-END without matching BEGIN"
                stack.pop()
        assert not stack, f"{name}: unterminated GZ-PATCH region {stack}"
    patches = (COMPONENT / "PATCHES.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^## ([A-Za-z0-9_-]+)\s*$", patches, flags=re.MULTILINE))
    assert ids_in_code == documented
    assert BASE_TAG in patches
    assert re.search(r"\b[0-9a-f]{40}\b", patches), "PATCHES.md must name the upstream commit SHA"


@pytest.mark.unit
def test_queue_ops_is_esphome_free() -> None:
    includes = re.findall(r"^\s*#\s*include\s+(.+)$", (COMPONENT / "queue_ops.h").read_text(encoding="utf-8"), re.M)
    assert includes
    for include in includes:
        assert include.strip().startswith("<") and "esphome" not in include, include


@pytest.mark.unit
def test_lanes_header_is_esphome_free() -> None:
    includes = re.findall(r"^\s*#\s*include\s+(.+)$", (COMPONENT / "lanes.h").read_text(encoding="utf-8"), re.M)
    assert includes
    for include in includes:
        assert include.strip().startswith("<") and "esphome" not in include, include


def _load_lane_plan():
    spec = importlib.util.spec_from_file_location("gz_lane_plan", COMPONENT / "lane_plan.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_lane_plan_is_esphome_free() -> None:
    import ast
    import sys

    tree = ast.parse((COMPONENT / "lane_plan.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in lane_plan.py"
            names = [node.module or ""]
        for name in names:
            assert name.split(".")[0] in sys.stdlib_module_names, f"lane_plan.py imports {name}"


@pytest.mark.unit
def test_lane_plan_modes() -> None:
    plan = _load_lane_plan().plan_lanes
    assert plan("g", 1, [None] * 4) == [[0, 1, 2, 3]]
    assert plan("g", "all", [None] * 3) == [[0], [1], [2]]
    assert plan("g", "ALL", [None] * 2) == [[0], [1]]
    assert plan("g", 2, [None] * 5) == [[0, 2, 4], [1, 3]]
    assert plan("g", 3, [None] * 2) == [[0], [1]]
    assert plan("g", 2, [None] * 2) == [[0], [1]]
    assert plan("g", 1, [None]) == [[0]]


@pytest.mark.unit
def test_lane_plan_pins() -> None:
    module = _load_lane_plan()
    plan, error = module.plan_lanes, module.LanePlanError
    assert plan("g", 3, [1, 0, 1, 0]) == [[1, 3], [0, 2]]  # order kept inside a lane
    assert plan("g", 3, [2, 0, 2]) == [[1], [0, 2]]  # an empty pinned lane is dropped (lanes renumbered)
    with pytest.raises(error, match="lawn.*all-or-none"):
        plan("lawn", 2, [0, None, 1])
    with pytest.raises(error, match="lawn.*lane 2"):
        plan("lawn", 2, [0, 2])
    with pytest.raises(error, match="lawn.*'lane'"):
        plan("lawn", 1, [0, 0])
    with pytest.raises(error, match="lawn.*'lane'"):
        plan("lawn", "all", [0, 1])
    with pytest.raises(error, match="lawn"):
        plan("lawn", 0, [None])
    with pytest.raises(error, match="lawn"):
        plan("lawn", 2, [])


@pytest.mark.unit
def test_new_files_headers() -> None:
    for name in NEW_FILES:
        head = "\n".join((COMPONENT / name).read_text(encoding="utf-8").splitlines()[:6])
        assert "General Public License v3" in head, name
        assert "Copyright (c) GardenPilot contributors" in head, name
        assert "modified copy" not in head.lower(), name
        assert "GZ-PATCH" not in (COMPONENT / name).read_text(encoding="utf-8"), name
    head = "\n".join((ZONE_COMPONENT / "__init__.py").read_text(encoding="utf-8").splitlines()[:4])
    assert "MIT" in head and "GardenPilot contributors" in head
    assert "General Public" not in (ZONE_COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert not (ZONE_COMPONENT / "LICENSE").exists()


@pytest.mark.unit
def test_garden_zone_entries_are_lists() -> None:
    paths = [*CONFIGS.rglob("*.yaml"), *(REPO_ROOT / "packages").rglob("*.yaml")]
    assert ZONE_ENTRY in paths
    for path in paths:
        config = load_esphome_yaml(path)
        if isinstance(config, dict) and "garden_zone" in config:
            assert isinstance(config["garden_zone"], list), f"{path}: write garden_zone: as a list item (- group: ...)"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("garden_zone:"):
                assert line.strip() == "garden_zone:", f"{path}: garden_zone: must be followed by a list"


@pytest.mark.unit
def test_groups_test_config_shape() -> None:
    text = GROUPS_CONFIG.read_text(encoding="utf-8")
    assert "!secret" not in text
    assert not re.search(r"GPIO\d+", text)
    config = load_esphome_yaml(GROUPS_CONFIG)
    assert isinstance(config, dict)
    for forbidden in ("api", "wifi", "ota"):
        assert forbidden not in config
    assert config["packages"]["hardware"] == {"__tag__": "include", "value": "hardware/sim.yaml"}
    includes = [v for v in config["packages"].values() if v != config["packages"]["hardware"]]
    assert len(includes) == 2
    for include in includes:
        assert include["__tag__"] == "include"
        assert include["value"]["file"] == "garden_zone_entry.yaml"
    assert config["external_components"] == [{"source": "components", "components": ["garden_zones", "garden_zone"]}]
    groups = {g["id"]: g for g in config["garden_zones"]["groups"]}
    assert groups["beds"]["max_parallel"] == "all"
    assert groups["lawn"]["max_parallel"] == 2 and groups["lawn"]["pump_switch_id"] == "gz_pump"
    assert groups["solo"]["max_parallel"] == 1
    assert "garden_zone" not in config  # the beds zones come from the two includes
    entry = load_esphome_yaml(ZONE_ENTRY)
    assert isinstance(entry, dict) and isinstance(entry["garden_zone"], list)


@pytest.mark.unit
def test_device_unchanged() -> None:
    paths = [REPO_ROOT / "garden-pilot.yaml"]
    for folder in ("packages", "hardware"):
        paths += [p for p in (REPO_ROOT / folder).rglob("*.yaml") if p.is_file()]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "garden_zones" not in text, f"{path.relative_to(REPO_ROOT)} must not use garden_zones yet"
        assert "external_components" not in text, f"{path.relative_to(REPO_ROOT)} must not use external_components"


@pytest.mark.unit
def test_sim_test_config_shape() -> None:
    text = SIM_CONFIG.read_text(encoding="utf-8")
    assert "!secret" not in text
    assert not re.search(r"GPIO\d+", text)
    config = load_esphome_yaml(SIM_CONFIG)
    assert isinstance(config, dict)
    for forbidden in ("api", "wifi", "ota"):
        assert forbidden not in config
    assert config["packages"]["hardware"] == {"__tag__": "include", "value": "hardware/sim.yaml"}
    assert config["external_components"] == [{"source": "components", "components": ["garden_zones"]}]
    controllers = config["garden_zones"]
    assert len(controllers) == 1
    relays = [valve["valve_switch_id"] for valve in controllers[0]["valves"]]
    assert relays == ["board_relay_1", "board_relay_2", "board_relay_3"]


# ---------------------------------------------------------------------------------------------- cpp


def _compiler() -> str | None:
    return shutil.which(os.environ.get("CXX", "g++"))


def _need_compiler() -> None:
    """Skip without a C++ compiler, but fail where one is required (devcontainer / CI: GP_REQUIRE_CXX=1)."""
    if _compiler() is not None:
        return
    reason = "no C++ compiler (set CXX or install build-essential)"
    if os.environ.get("GP_REQUIRE_CXX") == "1":
        pytest.fail(reason + "; GP_REQUIRE_CXX=1 forbids skipping")
    pytest.skip(reason)


@pytest.mark.unit
def test_devcontainers_require_a_compiler() -> None:
    import json

    for path in (
        REPO_ROOT / ".devcontainer" / "devcontainer.json",
        REPO_ROOT / ".devcontainer" / "sdl" / "devcontainer.json",
    ):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        assert cfg["containerEnv"].get("GP_REQUIRE_CXX") == "1", path


@pytest.mark.cpp
def test_cpp_unit_tests() -> None:
    _need_compiler()
    result = subprocess.run(
        ["sh", "script/test-cpp"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=600, check=False
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]


# ---------------------------------------------------------------------------------------------- esphome


def _resolve(version: str) -> str:
    out = subprocess.run(
        ["sh", "script/_esphome", "--resolve"],
        cwd=REPO_ROOT,
        env={**os.environ, "GP_ESPHOME": version},
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _stage(dest: Path, source: Path = SIM_CONFIG, name: str = "garden-zones-sim.yaml") -> Path:
    """Copy a test config and everything it includes to `dest` (the config expects to sit at the root)."""
    dest.mkdir(parents=True, exist_ok=True)
    for folder in ("hardware", "components"):
        shutil.copytree(
            REPO_ROOT / folder, dest / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__")
        )
    config = dest / name
    shutil.copy(source, config)
    if source == GROUPS_CONFIG:
        shutil.copy(ZONE_ENTRY, dest / ZONE_ENTRY.name)
    return config


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


@pytest.mark.config
@pytest.mark.parametrize("version", VERSIONS)
def test_sim_config(version: str, tmp_path: Path) -> None:
    config = _stage(tmp_path)
    result = _esphome(version, "config", str(config), timeout=600)
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]


def _host_dir(version: str) -> Path:
    return REPO_ROOT / ".esphome" / "gz-host" / _resolve(version)


def _program(version: str) -> Path:
    return _host_dir(version) / ".esphome" / "build" / "garden-zones-sim" / ".pioenvs" / "garden-zones-sim" / "program"


_BUILT: dict[str, Path] = {}


def _build(version: str) -> Path:
    _need_compiler()
    if version not in _BUILT:
        config = _stage(_host_dir(version))  # fixed directory per version: incremental rebuilds
        result = _esphome(version, "compile", str(config), timeout=1800)
        assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
        program = _program(version)
        assert program.is_file(), f"host program not found at {program}"
        _BUILT[version] = program
    return _BUILT[version]


@pytest.fixture(scope="module", params=VERSIONS)
def host_build(request: pytest.FixtureRequest) -> Path:
    return _build(request.param)


@pytest.fixture(scope="module")
def host_build_pinned() -> Path:
    return _build("pinned")


@pytest.mark.host
def test_host_compile(host_build: Path) -> None:
    assert host_build.is_file()


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_GZTEST = re.compile(r"\[GZTEST:\d+\]: (.*)$")


def _run_program(program: Path, prefdir: Path, timeout: float = 90.0) -> list[str]:
    """Run the host program until it logs `done` (or the timeout), return the GZTEST messages."""
    env = {**os.environ, "ESPHOME_PREFDIR": str(prefdir)}
    proc = subprocess.Popen(
        [str(program)], cwd=prefdir, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    messages: list[str] = []
    finished = threading.Event()

    def reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            match = _GZTEST.search(_ANSI.sub("", raw).rstrip())
            if match:
                messages.append(match.group(1))
                if match.group(1) == "done":
                    finished.set()
        finished.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    finished.wait(timeout)
    time.sleep(0.5)
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    thread.join(5)
    return messages


def _active_between(messages: list[str], start: str, end: str | None) -> list[str]:
    begin = messages.index(start)
    stop = messages.index(end) if end else len(messages)
    values = [m.split("=", 1)[1] for m in messages[begin:stop] if m.startswith("active=")]
    return [v for i, v in enumerate(values) if i == 0 or v != values[i - 1]]


@pytest.mark.host
def test_host_scenario(host_build_pinned: Path, tmp_path: Path) -> None:
    program = host_build_pinned
    assert program.is_file()
    prefdir = tmp_path / "prefs"
    prefdir.mkdir()

    first = _run_program(program, prefdir)
    assert "done" in first, first
    restored = [m for m in first if m.startswith("restored=")]
    assert restored == ["restored="], "first boot must start with an empty queue"
    assert "boot_queue=" in first
    step2 = first[first.index("step=2") : first.index("step=3")]
    assert [m for m in step2 if m.startswith(("queue=", "queued"))] == [
        "queue=0,1,2",
        "queued1=1 queued2=1",
        "queue=0,1",
        "queued1=1 queued2=0",
        "queue=0,1,2",
    ]

    # manual run in the middle of a queue run: 0, then manual 2, then 0 resumes, 1 is skipped, 2 from the queue
    step3 = first[first.index("step=3") : first.index("step=3b")]
    switches = [m.split(" ", 2)[2] for m in step3 if m.startswith("switches ")]
    assert len(switches) == 2 and switches[0] == switches[1] == "auto=0 queue=1"
    seen = _active_between(first, "step=3", "step=3b")
    sequence = [v for v in seen if v != "none"]
    assert sequence == ["0", "2", "0", "2"], sequence
    assert "1" not in sequence, "disabled valve 1 must never run"
    assert seen[-1] == "none"
    assert "queue_after_run=" in step3

    # stale user pause (valve 0) + running valve 1 + run_valve 2: 1 is paused and resumed, 0 is dropped, not resumed
    step3b = first[first.index("step=3b") : first.index("step=4")]
    seen = _active_between(first, "step=3b", "step=4")
    assert [v for v in seen if v != "none"] == ["0", "1", "2", "1"], seen
    assert seen[-1] == "none"
    assert "paused_stale=0" in step3b and "paused_end=none" in step3b

    # manual run while idle: only that valve runs, the queue stays and is not started
    step4 = first[first.index("step=4") :]
    seen = _active_between(first, "step=4", None)
    assert [v for v in seen if v != "none"] == ["2"], seen
    assert seen[-1] == "none"
    assert "queue=0,1" in step4 and "queue_end=0,1" in step4
    idle = [m.split(" ", 2)[2] for m in step4 if m.startswith("switches idle_")]
    assert len(idle) == 2 and idle[0] == idle[1]

    # second boot with the same preference directory: the queue comes back and does not start by itself
    second = _run_program(program, prefdir)
    assert "restored=0,1" in second, second[:6]
    before_scenario = second[: second.index("step=2")]
    assert "boot_queue=0,1" in before_scenario, "restored queue must still be listed after the idle period"
    started = [m for m in before_scenario if m.startswith("active=") and m != "active=none"]
    assert not started, f"restored queue started by itself: {started}"


# ---------------------------------------------------------------------------------------------- groups (task 012)

GROUPS_NAME = "garden-zones-groups"
_GZTEST_STATE = re.compile(r"state=([01]{7}) pump=([01])$")


def _stage_groups(dest: Path) -> Path:
    return _stage(dest, GROUPS_CONFIG, f"{GROUPS_NAME}.yaml")


@pytest.mark.config
@pytest.mark.parametrize("version", VERSIONS)
def test_groups_config(version: str, tmp_path: Path) -> None:
    config = _stage_groups(tmp_path)
    result = _esphome(version, "config", str(config), timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-4000:]
    section = output[output.index("\ngarden_zone:") :]
    section = section[: section.index("\nlogger:")]
    assert section.index("name: GZ bed 1") < section.index("name: GZ bed 2")
    assert section.count("- group: beds") == 2
    assert section.index("valve_switch_id: board_relay_1") < section.index("valve_switch_id: board_relay_2")


_ERROR_HEAD = """\
esphome:
  name: gz-error
packages:
  hardware: !include hardware/sim.yaml
logger:
  level: INFO
external_components:
  - source: components
    components: [garden_zones, garden_zone]
switch:
  - {platform: template, id: gz_pump, internal: true, optimistic: true}
  - {platform: template, id: gz_pump_2, internal: true, optimistic: true}
"""


def _zone(group: str, relay: str, extra: str = "", name: str | None = None) -> str:
    return (
        f"    - group: {group}\n      valve_switch: {name or f'Zone {relay}'}\n      valve_switch_id: board_relay_{relay}\n"
        f"      run_duration: 2s\n{extra}"
    )


_ERROR_CASES = {
    "unknown-group": (
        "garden_zones:\n  groups:\n    - {id: g, max_parallel: all}\n  zones:\n" + _zone("nope", "1"),
        "nope",
    ),
    "mixed-pins": (
        "garden_zones:\n  groups:\n    - {id: g, max_parallel: 2}\n  zones:\n"
        + _zone("g", "1", "      lane: 0\n")
        + _zone("g", "2"),
        "all-or-none",
    ),
    "lane-with-all": (
        "garden_zones:\n  groups:\n    - {id: g, max_parallel: all}\n  zones:\n" + _zone("g", "1", "      lane: 0\n"),
        "'lane' needs an integer max_parallel",
    ),
    "pump-in-two-groups": (
        "garden_zones:\n  groups:\n    - {id: a, max_parallel: all, pump_switch_id: gz_pump}\n"
        "    - {id: b, max_parallel: all, pump_switch_id: gz_pump}\n  zones:\n" + _zone("a", "1") + _zone("b", "2"),
        "a pump can belong to one group only",
    ),
    "valve-twice": (
        "garden_zones:\n  groups:\n    - {id: g, max_parallel: all}\n  zones:\n" + _zone("g", "1") + _zone("g", "1", name="Zone again"),
        "is used by two zones",
    ),
    "pump-is-a-valve": (
        "garden_zones:\n  groups:\n    - {id: g, max_parallel: all, pump_switch_id: board_relay_1}\n  zones:\n"
        + _zone("g", "1"),
        "is also the valve switch",
    ),
    "group-without-zones": (
        "garden_zones:\n  groups:\n    - {id: g, max_parallel: all}\n    - {id: h, max_parallel: 1}\n  zones:\n"
        + _zone("g", "1"),
        "has no zones",
    ),
    "lane-id-clash": (
        "sensor:\n  - {platform: template, id: g_lane_0}\n"
        "garden_zones:\n  groups:\n    - {id: g, max_parallel: all}\n  zones:\n" + _zone("g", "1"),
        "generated lane id 'g_lane_0'",
    ),
    "list-form-plus-entry": (
        "garden_zones:\n  - id: gz\n    main_switch: Main\n    auto_advance_switch: Auto\n    valves:\n"
        "      - {valve_switch: V1, valve_switch_id: board_relay_1, run_duration: 2s}\n"
        "      - {valve_switch: V2, valve_switch_id: board_relay_2, run_duration: 2s}\n"
        "garden_zone:\n  - group: gz\n    valve_switch: Z\n    valve_switch_id: board_relay_3\n    run_duration: 2s\n",
        # the id check of `group:` fires before the final validation (which has its own "cannot be mixed" message)
        "doesn't inherit from garden_zones::GardenZonesGroup",
    ),
}


@pytest.mark.config
@pytest.mark.parametrize("case", sorted(_ERROR_CASES))
def test_groups_config_errors(case: str, tmp_path: Path) -> None:
    body, expected = _ERROR_CASES[case]
    config = _stage_groups(tmp_path)  # stages hardware/ and components/
    config.unlink()
    (tmp_path / ZONE_ENTRY.name).unlink()
    config = tmp_path / "gz-error.yaml"
    config.write_text(_ERROR_HEAD + body, encoding="utf-8")
    result = _esphome("pinned", "config", str(config), timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output[-2000:]
    assert expected in output, output[-3000:]


@pytest.mark.config
def test_garden_zone_dict_form_collapses(tmp_path: Path) -> None:
    config = _stage_groups(tmp_path)
    config.unlink()
    (tmp_path / ZONE_ENTRY.name).unlink()
    config = tmp_path / "gz-dict.yaml"
    config.write_text(
        """\
esphome:
  name: gz-dict
packages:
  hardware: !include hardware/sim.yaml
  zone_a:
    garden_zone:
      group: g
      valve_switch: Zone A
      valve_switch_id: board_relay_1
      run_duration: 2s
  zone_b:
    garden_zone:
      group: g
      valve_switch: Zone B
      valve_switch_id: board_relay_2
      run_duration: 2s
logger:
  level: INFO
external_components:
  - source: components
    components: [garden_zones, garden_zone]
garden_zones:
  groups:
    - {id: g, max_parallel: all}
""",
        encoding="utf-8",
    )
    result = _esphome("pinned", "config", str(config), timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-3000:]
    section = output[output.index("\ngarden_zone:") :]
    section = section[: section.index("\nlogger:")]
    assert section.count("- group: g") == 1, "two dict-form entries must collapse into one zone (merge behaviour)"
    assert "valve_switch_id: board_relay_2" in section and "valve_switch_id: board_relay_1" not in section


@pytest.fixture(scope="module", params=VERSIONS)
def groups_generated(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build directory of `esphome compile --only-generate` for the staged groups config (once per version)."""
    tmp_path = tmp_path_factory.mktemp(f"groups-gen-{request.param}")
    config = _stage_groups(tmp_path)
    result = _esphome(request.param, "compile", "--only-generate", str(config), timeout=900)
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    return tmp_path / ".esphome" / "build" / GROUPS_NAME


@pytest.mark.config
def test_groups_component_count(groups_generated: Path) -> None:
    defines = (groups_generated / "src" / "esphome" / "core" / "defines.h").read_text(encoding="utf-8")
    count = int(re.search(r"#define ESPHOME_COMPONENT_COUNT (\d+)", defines).group(1))
    main_cpp = (groups_generated / "src" / "main.cpp").read_text(encoding="utf-8")
    registered = main_cpp.count("App.register_component_(")
    assert count >= registered, f"ESPHOME_COMPONENT_COUNT {count} < {registered} registered components"


@pytest.mark.config
def test_groups_codegen(groups_generated: Path) -> None:
    main_cpp = (groups_generated / "src" / "main.cpp").read_text(encoding="utf-8")
    for lane in ("beds_lane_0", "beds_lane_1", "lawn_lane_0", "lawn_lane_1", "solo_lane_0"):
        assert re.search(rf"\b{lane}->set_lane_mode\(true\);", main_cpp), lane
    assert "solo_lane_1" not in main_cpp and "lawn_lane_2" not in main_cpp and "beds_lane_2" not in main_cpp
    assert main_cpp.count("set_lane_mode(true)") == 5
    assert main_cpp.count("->add_controller(") == 5 * 4
    pumps = re.findall(r"(\w+)->configure_valve_pump_switch\(\d+, gz_pump\);", main_cpp)
    assert sorted(pumps) == ["lawn_lane_0", "lawn_lane_0", "lawn_lane_1"]
    assert main_cpp.count("configure_valve_pump_switch") == 3
    assert len(re.findall(r"new\(\w+\) garden_zones::GardenZonesGroup\(", main_cpp)) == 3


def _groups_host_dir() -> Path:
    return REPO_ROOT / ".esphome" / "gz-groups-host" / _resolve("pinned")


@pytest.fixture(scope="module")
def groups_program() -> Path:
    _need_compiler()
    config = _stage_groups(_groups_host_dir())
    result = _esphome("pinned", "compile", str(config), timeout=1800)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    program = (
        _groups_host_dir() / ".esphome" / "build" / GROUPS_NAME / ".pioenvs" / GROUPS_NAME / "program"
    )
    assert program.is_file(), f"host program not found at {program}"
    return program


@pytest.mark.host
def test_groups_host_compile(groups_program: Path) -> None:
    assert groups_program.is_file()


def _states(messages: list[str], start: str, end: str | None) -> list[tuple[str, int]]:
    begin = messages.index(start)
    stop = messages.index(end) if end else len(messages)
    found = [_GZTEST_STATE.match(m) for m in messages[begin:stop]]
    return [(m.group(1), int(m.group(2))) for m in found if m]


def _on(state: str, *valves: int) -> bool:
    """True when every given valve (1-based) is on in the 7-character state."""
    return all(state[v - 1] == "1" for v in valves)


def _rising(states: list[tuple[str, int]], valve: int) -> int:
    count, previous = 0, False
    for state, _ in states:
        now = _on(state, valve)
        count += int(now and not previous)
        previous = now
    return count


@pytest.mark.host
def test_groups_host_scenario(groups_program: Path, tmp_path: Path) -> None:
    prefdir = tmp_path / "prefs"
    prefdir.mkdir()
    first = _run_program(groups_program, prefdir, timeout=300)
    assert "done" in first, first[-15:]

    assert "restored beds= lawn= solo=" in first and "boot beds= lawn= solo=" in first
    assert not [s for s in _states(first, "restored beds= lawn= solo=", "step=2") if "1" in s[0] or s[1]]

    # 2. beds: both lanes run together, then everything is off
    step2 = _states(first, "step=2", "step=3")
    assert "queue beds=0,1 lawn= solo=" in first[first.index("step=2") : first.index("step=3")]
    assert any(_on(s, 1, 2) for s, _ in step2), step2
    assert step2[-1][0][:2] == "00"

    # 3. lawn: lanes [[0,2],[1]] and the shared pump
    step3_msgs = first[first.index("step=3") : first.index("step=4")]
    assert [m for m in step3_msgs if m.startswith(("queue ", "queued2="))] == [
        "queue beds= lawn=0,1,2 solo=",
        "queued2=1",
        "queue beds= lawn=0,1 solo=",
        "queued2=0",
        "queue beds= lawn=0,1,2 solo=",
    ]
    step3 = _states(first, "step=3", "step=4")
    assert any(_on(s, 3, 4) for s, _ in step3), "zone 0 and zone 1 (different lanes) must run together"
    assert not any(_on(s, 3, 5) for s, _ in step3), "zones 0 and 2 share a lane"
    assert all(s[0] == "0" and s[1] == "0" and s[5] == "0" and s[6] == "0" for s, _ in step3)
    assert all(pump == 1 for s, pump in step3 if "1" in s[2:5]), "the pump must be on while any lawn valve is on"
    assert any(_on(a, 3, 4) and _on(b, 3) and not _on(b, 4) and pb == 1 for (a, _), (b, pb) in zip(step3, step3[1:])), (
        "the pump must stay on when one lane finishes while the other still runs"
    )
    assert _on(step3[-1][0], 3) is False and step3[-1][1] == 0, "pump off after the queue drained"
    assert _rising(step3, 5) == 1 and _rising(step3, 3) == 1 and _rising(step3, 4) == 1

    # 4. solo: max_parallel 1
    step4 = _states(first, "step=4", "step=4b")
    assert not any(_on(s, 6, 7) for s, _ in step4)
    assert _rising(step4, 6) == 1 and _rising(step4, 7) == 1, step4
    assert step4[-1][0] == "0000000"
    step4b = _states(first, "step=4b", "step=5")
    assert _rising(step4b, 6) == 1 and _rising(step4b, 7) == 0, step4b
    assert step4b[-1][0] == "0000000", "solo must be idle (every valve off) at the end of step 4b"

    # 5. a manual run keeps the other lane
    step5 = _states(first, "step=5", "step=6")
    assert not any(_on(s, 3, 5) for s, _ in step5)
    start4 = next(i for i, (s, _) in enumerate(step5) if _on(s, 4))
    manual = next(i for i, (s, _) in enumerate(step5) if _on(s, 5))
    end_manual = next(i for i in range(manual, len(step5)) if not _on(step5[i][0], 5))
    assert all(_on(s, 4) for s, _ in step5[start4 : end_manual + 1]), "zone 1 (lane 1) must not be interrupted"
    resumed = next(i for i in range(end_manual, len(step5)) if _on(step5[i][0], 3))
    assert all(pump == 1 for _, pump in step5[start4 : resumed + 1]), "pump must stay on throughout"

    # 6. shutdown of one group does not touch the others
    step6 = first[first.index("step=6") :]
    assert "before_shutdown v1=1 v4=1 pump=1" in step6
    assert "after_shutdown v1=1 v4=0 pump=0" in step6
    assert "all_off v1=0 v4=0 pump=0" in step6
    assert "end beds= lawn=2,1 solo=" in step6

    # second boot, same preference directory: the per-lane queues come back and do not start by themselves
    second = _run_program(groups_program, prefdir, timeout=300)
    assert "restored beds= lawn=2,1 solo=" in second, second[:6]
    before = second[: second.index("step=2")]
    assert "boot beds= lawn=2,1 solo=" in before, "restored queue must still be listed after the idle period"
    assert not [s for s in _states(second, "restored beds= lawn=2,1 solo=", "step=2") if "1" in s[0] or s[1]], before
