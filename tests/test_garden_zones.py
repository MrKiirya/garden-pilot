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
SAFETY_CONFIG = CONFIGS / "garden_zones_safety_sim.yaml"
FORKED = ["__init__.py", "automation.h", "sprinkler.h", "sprinkler.cpp"]
NEW_FILES = [
    "groups.py",
    "lane_plan.py",
    "lanes.h",
    "group.h",
    "safety_rules.py",
    "watchdog_core.h",
    "watchdog.h",
    "soil_skip.h",
]
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
    assert ids_in_code == {
        "includes", "queue-api", "queue-persist", "queue-skip-disabled", "manual-run", "groups", "lanes", "zone-skip",
    }
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


def _load_safety_rules():
    spec = importlib.util.spec_from_file_location("gz_safety_rules", COMPONENT / "safety_rules.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_safety_rules_zone_limit() -> None:
    rules = _load_safety_rules()
    assert rules.zone_limit_error("zone 1", 1000, 0, 3000) is None
    error = rules.zone_limit_error("zone 1", 2000, 0, 3000)
    assert error is not None and "zone 1" in error and "max_on_time" in error  # 2 + 0 + 2 > 3
    assert rules.zone_limit_error("zone 1", 1000, 2000, 3000) is not None  # the start delay is part of the run
    assert rules.zone_limit_error("zone 1", 1000, 1000, 4000) is None
    # pump_stop_valve_delay keeps the valve open after the run: the groups code adds it to the delays
    assert rules.zone_limit_error("zone 1", 2000, 2000, 5000) is not None
    assert rules.zone_limit_error("zone 1", 2000, 2000, 6000) is None
    default = rules.longest_run_ms(None, 120, "min")
    assert default == 7_200_000
    error = rules.zone_limit_error("zone 1", default, 0, 3_600_000, from_number=True)
    assert error is not None and "max_value" in error and "max_on_time" in error
    assert rules.zone_limit_error("zone 1", rules.longest_run_ms(None, 50, "min"), 0, 3_600_000, from_number=True) is None
    assert rules.longest_run_ms(None, 86400, "s") == 86_400_000
    assert rules.longest_run_ms(900_000, None, None) == 900_000


@pytest.mark.unit
def test_safety_rules_pump() -> None:
    rules = _load_safety_rules()
    assert rules.pump_limit_error("lawn", 5000, {"zone 1": 3000, "zone 2": 5000}) is None
    error = rules.pump_limit_error("lawn", 4000, {"zone 1": 3000, "zone 2": 5000})
    assert error is not None and "pump_max_on_time" in error and "zone 2" in error
    # arguments: idle timeout, pump_start_valve_delay (pump on, valve not open yet), pump_stop_pump_delay
    assert rules.pump_idle_error("lawn", 3000, 2000, 0) is not None  # 3 s < 2 s + 2 s
    assert rules.pump_idle_error("lawn", 4000, 2000, 0) is None
    assert rules.pump_idle_error("lawn", 4000, 0, 2000) is None
    assert rules.pump_idle_error("lawn", 1000, 0, 0) is not None  # 1 s < 0 + 2 s
    assert rules.pump_keys_error("lawn", False, ["pump_max_on_time"]) is not None
    assert rules.pump_keys_error("lawn", False, []) is None
    assert rules.pump_keys_error("lawn", True, ["pump_max_on_time"]) is None


@pytest.mark.unit
def test_safety_rules_restore_mode() -> None:
    rules = _load_safety_rules()
    for ok in ("ALWAYS_OFF", "RESTORE_DEFAULT_OFF", "switch_::SWITCH_ALWAYS_OFF", "switch_::SWITCH_RESTORE_DEFAULT_OFF"):
        assert rules.restore_mode_error("lawn_valve_1", "valve", ok) is None, ok
    for bad in (
        "ALWAYS_ON",
        "RESTORE_DEFAULT_ON",
        "RESTORE_INVERTED_DEFAULT_OFF",
        "RESTORE_INVERTED_DEFAULT_ON",
        "DISABLED",
        "switch_::SWITCH_RESTORE_DISABLED",
        "switch_::SWITCH_ALWAYS_ON",
    ):
        error = rules.restore_mode_error("lawn_valve_1", "valve", bad)
        assert error is not None and "lawn_valve_1" in error and "OFF after boot" in error, bad


@pytest.mark.unit
def test_safety_files_are_esphome_free() -> None:
    import ast
    import sys

    tree = ast.parse((COMPONENT / "safety_rules.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in safety_rules.py"
            names = [node.module or ""]
        for name in names:
            assert name.split(".")[0] in sys.stdlib_module_names, f"safety_rules.py imports {name}"
    for header in ("watchdog_core.h", "soil_skip.h"):
        includes = re.findall(r"^\s*#\s*include\s+(.+)$", (COMPONENT / header).read_text(encoding="utf-8"), re.M)
        assert includes, header
        for include in includes:
            assert include.strip().startswith("<") and "esphome" not in include, f"{header}: {include}"


@pytest.mark.unit
def test_watchdog_not_persisted() -> None:
    for name in ("watchdog_core.h", "watchdog.h"):
        text = (COMPONENT / name).read_text(encoding="utf-8").lower()
        assert "preference" not in text, name
    cpp = COMPONENT / "watchdog.cpp"
    if cpp.exists():
        assert "preference" not in cpp.read_text(encoding="utf-8").lower()


@pytest.mark.unit
def test_safety_test_config_shape() -> None:
    text = SAFETY_CONFIG.read_text(encoding="utf-8")
    assert "!secret" not in text
    assert not re.search(r"GPIO\d+", text)
    config = load_esphome_yaml(SAFETY_CONFIG)
    assert isinstance(config, dict)
    for forbidden in ("api", "wifi", "ota"):
        assert forbidden not in config
    assert config["packages"]["hardware"] == {"__tag__": "include", "value": "hardware/sim.yaml"}
    assert config["external_components"] == [{"source": "components", "components": ["garden_zones", "garden_zone"]}]
    groups = {g["id"]: g for g in config["garden_zones"]["groups"]}
    assert sorted(groups) == ["beds", "lawn", "pair", "stuck"]
    assert groups["lawn"]["pump_switch_id"] == "gz_pump"
    for switch in config["switch"]:
        if switch.get("platform") == "template":
            assert switch.get("restore_mode") == "ALWAYS_OFF", switch.get("id")
    for group in groups.values():
        assert "on_watchdog_trip" in group, group["id"]


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


def _brief_overlap_only(states: list[tuple[str, int]], *valves: int) -> bool:
    """Two valves of one lane may be on together only for the brief stock handover (accepted by design, task 013
    round 3): the state log has an entry on every change, so a both-on sample must be a single entry between
    'first only' and 'second only'; two such entries in a row would be a real overlap."""
    run = 0
    for state, _ in states:
        run = run + 1 if _on(state, *valves) else 0
        if run > 1:
            return False
    return True


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
    assert _brief_overlap_only(step3, 3, 5), "zones 0 and 2 share a lane"
    assert all(s[0] == "0" and s[1] == "0" and s[5] == "0" and s[6] == "0" for s, _ in step3)
    assert all(pump == 1 for s, pump in step3 if "1" in s[2:5]), "the pump must be on while any lawn valve is on"
    assert any(_on(a, 3, 4) and _on(b, 3) and not _on(b, 4) and pb == 1 for (a, _), (b, pb) in zip(step3, step3[1:])), (
        "the pump must stay on when one lane finishes while the other still runs"
    )
    assert _on(step3[-1][0], 3) is False and step3[-1][1] == 0, "pump off after the queue drained"
    assert _rising(step3, 5) == 1 and _rising(step3, 3) == 1 and _rising(step3, 4) == 1

    # 4. solo: max_parallel 1
    step4 = _states(first, "step=4", "step=4b")
    assert _brief_overlap_only(step4, 6, 7)
    assert _rising(step4, 6) == 1 and _rising(step4, 7) == 1, step4
    assert step4[-1][0] == "0000000"
    step4b = _states(first, "step=4b", "step=5")
    assert _rising(step4b, 6) == 1 and _rising(step4b, 7) == 0, step4b
    assert step4b[-1][0] == "0000000", "solo must be idle (every valve off) at the end of step 4b"

    # 5. a manual run keeps the other lane
    step5 = _states(first, "step=5", "step=6")
    assert _brief_overlap_only(step5, 3, 5)
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


# ---------------------------------------------------------------------------------------------- safety (task 013)

SAFETY_NAME = "garden-zones-safety"


def _stage_safety(dest: Path) -> Path:
    return _stage(dest, SAFETY_CONFIG, f"{SAFETY_NAME}.yaml")


@pytest.mark.config
@pytest.mark.parametrize("version", VERSIONS)
def test_safety_config(version: str, tmp_path: Path) -> None:
    config = _stage_safety(tmp_path)
    result = _esphome(version, "config", str(config), timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-4000:]
    section = output[output.index("\ngarden_zones:") :]
    section = section[: section.index("\nlogger:")] if "\nlogger:" in section else section
    zone1 = section[section.index("name: GZ bed 2") :] if "name: GZ bed 2" in section else section
    zone1 = zone1[: zone1.index("name: GZ bed 3")]
    assert "max_age: 30min" in zone1 and "when_unavailable: water" in zone1, zone1


@pytest.mark.config
def test_safety_defaults(tmp_path: Path) -> None:
    config = _stage_groups(tmp_path)  # the 012 groups config has no safety keys at all
    result = _esphome("pinned", "config", str(config), timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-4000:]
    groups = output[output.index("\ngarden_zones:") :]
    groups = groups[: groups.index("\n  zones:")]
    assert groups.count("max_on_time: 60min") == 3, groups
    assert groups.count("pump_max_on_time: 2h") == 1 and groups.count("pump_idle_timeout: 10s") == 1, groups
    lawn = groups[groups.index("id: lawn") : groups.index("id: solo")]
    assert "pump_max_on_time: 2h" in lawn and "pump_idle_timeout: 10s" in lawn


_SAFETY_HEAD = _ERROR_HEAD + "  - {platform: template, id: gz_pump_bad, internal: true, optimistic: true, restore_mode: RESTORE_DEFAULT_ON}\n"
_SAFETY_HEAD += "  - {platform: template, id: gz_valve_bad, internal: true, optimistic: true, restore_mode: ALWAYS_ON}\n"
_SAFETY_HEAD += "sensor:\n  - {platform: template, id: gz_soil, update_interval: never}\n"


def _safety_group(group_extra: str = "", zone_extra: str = "", relay: str = "1", pump: bool = False) -> str:
    pump_line = ", pump_switch_id: gz_pump" if pump else ""
    return (
        f"garden_zones:\n  groups:\n    - {{id: g, max_parallel: all{pump_line}{group_extra}}}\n  zones:\n"
        + _zone("g", relay, zone_extra)
    )


_SAFETY_ERRORS = {
    "run-too-close": (_safety_group(", max_on_time: 3s", ""), "exceeds max_on_time (3 s)"),
    "default-number-max": (
        "garden_zones:\n  groups:\n    - {id: g, max_parallel: all}\n  zones:\n"
        "    - group: g\n      valve_switch: Z\n      valve_switch_id: board_relay_1\n      run_duration_number: Z time\n",
        "run duration number's max_value allows",
    ),
    "max-on-time-zero": (_safety_group(", max_on_time: 0s"), "value must be at least 1000ms"),
    # there is no 4 h cap any more; only what a 32-bit millisecond timer tracks wrap-safely (30 days) is accepted
    "max-on-time-over-30-days": (_safety_group(", max_on_time: 31d"), "value must be at most 2592000000ms"),
    "pump-key-without-pump": (_safety_group(", pump_max_on_time: 1h"), "need pump_switch_id"),
    "pump-below-zone": (
        _safety_group(", max_on_time: 1h, pump_max_on_time: 30min", pump=True),
        "is below max_on_time of",
    ),
    # only the zone override makes the zone limit (30 min) exceed the pump limit (10 min); the group value is 10 min
    "pump-below-zone-override": (
        _safety_group(", max_on_time: 10min, pump_max_on_time: 10min", "      max_on_time: 30min\n", pump=True),
        "is below max_on_time of",
    ),
    # only the zone override makes the run too long (the group value is 1 h)
    "zone-override-too-short": (
        _safety_group(", max_on_time: 1h", "      max_on_time: 3s\n"),
        "exceeds max_on_time (3 s)",
    ),
    # 2 s run + 2 s margin fit under 5 s; the pump stops first and the valve stays open 2 s more
    "stop-valve-delay": (
        _safety_group(", max_on_time: 5s, pump_stop_valve_delay: 2s", pump=True),
        "pump delays 2 s",
    ),
    # pump_start_valve_delay is the "pump on, valve not open yet" phase
    "idle-too-short": (
        _safety_group(", pump_start_valve_delay: 5s, pump_idle_timeout: 5s", pump=True),
        "must be at least 7 s",
    ),
    "unknown-soil-sensor": (
        _safety_group("", "      soil_moisture: {sensor_id: nope, skip_above: 50}\n"),
        "Couldn't find ID 'nope'",
    ),
    "bad-when-unavailable": (
        _safety_group("", "      soil_moisture: {sensor_id: gz_soil, skip_above: 50, when_unavailable: maybe}\n"),
        "valid options are 'water', 'skip'",
    ),
    "valve-restore-always-on": (
        "garden_zones:\n  groups:\n    - {id: g, max_parallel: all}\n  zones:\n"
        "    - {group: g, valve_switch: Z, valve_switch_id: gz_valve_bad, run_duration: 2s}\n",
        "OFF after boot",
    ),
    "pump-restore-default-on": (
        _safety_group(pump=True).replace("pump_switch_id: gz_pump", "pump_switch_id: gz_pump_bad"),
        "OFF after boot",
    ),
}


@pytest.mark.config
@pytest.mark.parametrize("case", sorted(_SAFETY_ERRORS))
def test_safety_config_errors(case: str, tmp_path: Path) -> None:
    body, expected = _SAFETY_ERRORS[case]
    config = _stage_groups(tmp_path)
    config.unlink()
    (tmp_path / ZONE_ENTRY.name).unlink()
    config = tmp_path / "gz-error.yaml"
    config.write_text(_SAFETY_HEAD + body, encoding="utf-8")
    result = _esphome("pinned", "config", str(config), timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output[-2000:]
    assert expected in output, output[-3000:]


@pytest.fixture(scope="module", params=VERSIONS)
def safety_generated(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp(f"safety-gen-{request.param}")
    config = _stage_safety(tmp_path)
    result = _esphome(request.param, "compile", "--only-generate", str(config), timeout=900)
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    return tmp_path / ".esphome" / "build" / SAFETY_NAME


@pytest.mark.config
def test_safety_codegen(safety_generated: Path) -> None:
    main_cpp = (safety_generated / "src" / "main.cpp").read_text(encoding="utf-8")
    assert len(re.findall(r"new\(\w+\) garden_zones::GroupWatchdog\(", main_cpp)) == 4
    assert len(re.findall(r"->set_valve_skip_check\(", main_cpp)) == main_cpp.count("set_lane_mode(true)")
    assert main_cpp.count("->set_zone_soil(") == 2
    # beds / stuck: max_on_time 3 s; lawn pump limits 5 s / 2 s
    assert re.search(r"lawn_watchdog->set_pump\(gz_pump, 5000, 2000\);", main_cpp), "pump limits"
    assert len(re.findall(r"_watchdog->add_zone\([^;]*, 3000\);", main_cpp)) == 7
    # the per-zone override of the "pair" group (group value 3 s) is what the watchdog gets
    assert len(re.findall(r"pair_watchdog->add_zone\([^;]*, 5000\);", main_cpp)) == 1
    count = int(
        re.search(
            r"#define ESPHOME_COMPONENT_COUNT (\d+)",
            (safety_generated / "src" / "esphome" / "core" / "defines.h").read_text(encoding="utf-8"),
        ).group(1)
    )
    assert count >= main_cpp.count("App.register_component_(")


def _safety_host_dir() -> Path:
    return REPO_ROOT / ".esphome" / "gz-safety-host" / _resolve("pinned")


@pytest.fixture(scope="module")
def safety_program() -> Path:
    _need_compiler()
    config = _stage_safety(_safety_host_dir())
    result = _esphome("pinned", "compile", str(config), timeout=1800)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    program = _safety_host_dir() / ".esphome" / "build" / SAFETY_NAME / ".pioenvs" / SAFETY_NAME / "program"
    assert program.is_file(), f"host program not found at {program}"
    return program


@pytest.mark.host
def test_safety_host_compile(safety_program: Path) -> None:
    assert safety_program.is_file()


_SAFETY_STATE = re.compile(r"t=(\d+) state=([01]{6}) pump=([01])$")
_MARK = re.compile(r"mark=(\w+) t=(\d+)$")
_TRIP = re.compile(r"trip group=(\w+) zone=(-?\d+) reason=(\w+) t=(\d+)$")
# actuator index in the state string; 6 is the pump
_RELAY1, _RELAY2, _RELAY3, _V4, _V5, _STUCK, _PUMP = range(7)


class _Timeline:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.marks = {m.group(1): int(m.group(2)) for m in map(_MARK.match, messages) if m}
        self.trips = [(m.group(1), int(m.group(2)), m.group(3), int(m.group(4))) for m in map(_TRIP.match, messages) if m]
        self.states = []
        for m in map(_SAFETY_STATE.match, messages):
            if m:
                self.states.append((int(m.group(1)), m.group(2) + m.group(3)))

    def intervals(self, actuator: int, start: str, end: str) -> list[tuple[int, int]]:
        """(on, off) times of an actuator inside the window of two marks; an open interval ends at the window end."""
        low, high = self.marks[start], self.marks[end]
        found, begin, previous = [], None, "0"
        for t, state in self.states:
            if t < low or t > high:
                continue
            now = state[actuator]
            if now == "1" and previous != "1":
                begin = t
            if now != "1" and begin is not None:
                found.append((begin, t))
                begin = None
            previous = now
        if begin is not None:
            found.append((begin, high))
        return found

    def trips_between(self, start: str, end: str) -> list[tuple[str, int, str, int]]:
        return [trip for trip in self.trips if self.marks[start] <= trip[3] <= self.marks[end]]

    def after(self, text: str, start: str) -> list[str]:
        """Messages that start with `text`, from the position of the mark `start` on."""
        index = self.messages.index(f"mark={start} t={self.marks[start]}")
        return [m for m in self.messages[index:] if m.startswith(text)]


def _duration(spans: list[tuple[int, int]]) -> int:
    assert len(spans) == 1, spans
    return spans[0][1] - spans[0][0]


@pytest.mark.host
def test_safety_host_scenario(safety_program: Path, tmp_path: Path) -> None:
    prefdir = tmp_path / "prefs"
    prefdir.mkdir()
    messages = _run_program(safety_program, prefdir, timeout=240)
    assert "done" in messages, messages[-15:]
    tl = _Timeline(messages)
    # durations come from a 50 ms state log, so a lower bound of `limit` is relaxed by 100 ms

    # 1. clean start
    assert "tripped start beds=0 lawn=0 stuck=0" in messages and "cond beds=0" in messages
    assert not [s for s in tl.states if s[0] < tl.marks["s2_a"] and "1" in s[1]]

    # 2. valve limit through the sprinkler
    assert 2900 < _duration(tl.intervals(_RELAY1, "s2_a", "s2_b")) <= 4000
    assert [(g, z, r) for g, z, r, _ in tl.trips_between("s2_a", "s2_b")] == [("beds", 0, "max_on_time")]
    assert "active_after=0" in messages
    assert tl.intervals(_RELAY1, "s2_b", "s2_c") == []
    assert "tripped after_trip beds=1 lawn=0 stuck=0" in messages

    # 3. lockout, then reset
    assert tl.trips_between("s3_a", "s3_b") == [], "no second trip line for the locked zone"
    assert tl.intervals(_RELAY1, "s3_a", "s3_raw") == []
    assert "queue locked_after beds=" in messages, "the locked zone is dropped from the queue"
    assert "raw_on state=1" in messages and "raw_after state=0" in messages, "a raw turn-on is forced off within 500 ms"
    assert all(end - begin <= 500 for begin, end in tl.intervals(_RELAY1, "s3_raw", "s3_b"))
    assert "cond_after_reset beds=0" in messages
    run = _duration(tl.intervals(_RELAY1, "s3_run", "s3_c"))
    assert 500 <= run <= 2500, run
    assert tl.trips_between("s3_run", "s3_c") == []

    # 4. a raw turn-on without the sprinkler
    assert 2900 < _duration(tl.intervals(_RELAY3, "s4_a", "s4_b")) <= 4000
    assert [(g, z, r) for g, z, r, _ in tl.trips_between("s4_a", "s4_b")] == [("beds", 2, "max_on_time")]

    # 5. normal pump use
    for actuator in (_V4, _V5, _PUMP):
        assert tl.intervals(actuator, "s5_a", "s5_b"), actuator
    assert tl.trips_between("s5_a", "s5_b") == []
    assert "tripped after_pump_run beds=0 lawn=0 stuck=0" in messages

    # 6. pump idle
    assert 1900 < _duration(tl.intervals(_PUMP, "s6_a", "s6_b")) <= 3000
    assert [(g, z, r) for g, z, r, _ in tl.trips_between("s6_a", "s6_c")] == [("lawn", -1, "pump_idle")]
    assert tl.intervals(_V4, "s6_b", "s6_c") == [], "a locked group refuses run_zone"

    # 7. pump session limit
    assert 4900 < _duration(tl.intervals(_PUMP, "s7_a", "s7_b")) <= 6000
    assert [(g, z, r) for g, z, r, _ in tl.trips_between("s7_a", "s7_b")] == [("lawn", -1, "pump_max_on_time")]
    last = [state for t, state in tl.states if t <= tl.marks["s7_b"]][-1]
    assert last[_V4] == last[_V5] == last[_PUMP] == "0"

    # 8. soil skip
    for label in ("s8a", "s8e", "s8g"):  # wet / unavailable with skip / stale with skip: queued, dropped, never run
        relay = _RELAY3 if label != "s8a" else _RELAY2
        assert tl.intervals(relay, f"{label}_a", f"{label}_b") == [], label
        assert f"queue {label}_after beds=" in messages, label
    for label in ("s8b", "s8d"):  # dry / unavailable with the default policy: runs
        assert len(tl.intervals(_RELAY2, f"{label}_a", f"{label}_b")) == 1, label
    assert len(tl.intervals(_RELAY3, "s8f_a", "s8f_b")) == 1
    assert len(tl.intervals(_RELAY2, "s8c_a", "s8c_b")) == 1, "a manual run ignores the soil"
    assert tl.intervals(_RELAY2, "s8h_a", "s8h_b") == []
    assert len(tl.intervals(_RELAY1, "s8h_a", "s8h_b")) == 1 and len(tl.intervals(_RELAY3, "s8h_a", "s8h_b")) == 1
    assert tl.trips_between("s8a_a", "s8h_b") == []

    # handover: queued runs of one lane overlap only for the brief stock handover (state callbacks, not polled)
    handover = next(m for m in messages if m.startswith("handover starts="))
    assert handover.startswith("handover starts=4 ") and int(handover.rsplit("max_ms=", 1)[1]) < 100, handover
    assert not [trip for trip in tl.trips if trip[0] == "pair"]

    # 9. a stuck relay
    trips = [trip for trip in tl.trips if trip[0] == "stuck"]
    assert [(z, r) for _, z, r, _ in trips] == [(0, "max_on_time")]
    on_at = next(t for t, state in tl.states if t >= tl.marks["s9_a"] and state[_STUCK] == "1")
    assert 2900 < trips[0][3] - on_at <= 4000  # the 50 ms state log lags the actuator
    counts = {m.split("=")[0]: int(m.split("=")[1].split()[0]) for m in messages if m.startswith("stuck_count_")}
    assert "state=1" in next(m for m in messages if m.startswith("stuck_count_1"))
    assert "state=1" in next(m for m in messages if m.startswith("stuck_count_2"))
    assert 3 <= counts["stuck_count_2"] - counts["stuck_count_1"] <= 6, counts
    assert "state=0" in next(m for m in messages if m.startswith("stuck_count_3"))
    assert "tripped stuck_latched beds=0 lawn=0 stuck=1" in messages
    assert "tripped stuck_reset beds=0 lawn=0 stuck=0" in messages

    # whole run: no valve on for longer than its limit + 1 s (the stuck relay excepted), the pump never above 6 s
    for actuator, limit in ((_RELAY1, 4000), (_RELAY2, 4000), (_RELAY3, 4000), (_V4, 4000), (_V5, 4000), (_PUMP, 6000)):
        begin = None
        for t, state in tl.states:
            if state[actuator] == "1" and begin is None:
                begin = t
            elif state[actuator] != "1" and begin is not None:
                assert t - begin <= limit + 100, f"actuator {actuator} on for {t - begin} ms"
                begin = None


# ------------------------------------------------------------------------ stock handover overlap (task 013, round 3)

OVERLAP_CONFIG = CONFIGS / "garden_zones_overlap_sim.yaml"
OVERLAP_NAME = "garden-zones-overlap"


@pytest.mark.unit
def test_overlap_test_config_shape() -> None:
    text = OVERLAP_CONFIG.read_text(encoding="utf-8")
    assert "!secret" not in text
    assert not re.search(r"GPIO\d+", text)
    config = load_esphome_yaml(OVERLAP_CONFIG)
    assert isinstance(config, dict)
    for forbidden in ("api", "wifi", "ota"):
        assert forbidden not in config
    controllers = {c["id"]: c for c in config["garden_zones"]}
    assert "valve_overlap" not in controllers["plain"] and controllers["ovl"]["valve_overlap"] == "1s"
    for switch in config["switch"]:
        assert switch.get("restore_mode") == "ALWAYS_OFF", switch.get("id")


def _overlap_host_dir() -> Path:
    return REPO_ROOT / ".esphome" / "gz-overlap-host" / _resolve("pinned")


@pytest.fixture(scope="module")
def overlap_program() -> Path:
    _need_compiler()
    config = _stage(_overlap_host_dir(), OVERLAP_CONFIG, f"{OVERLAP_NAME}.yaml")
    result = _esphome("pinned", "compile", str(config), timeout=1800)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    program = _overlap_host_dir() / ".esphome" / "build" / OVERLAP_NAME / ".pioenvs" / OVERLAP_NAME / "program"
    assert program.is_file(), f"host program not found at {program}"
    return program


@pytest.mark.host
def test_valve_handover_host_scenario(overlap_program: Path, tmp_path: Path) -> None:
    """The stock handover may keep two valves of a controller on together for one main-loop pass (accepted by design:
    the pump must never run against closed valves), never longer; with valve_overlap the deliberate overlap of ~1 s
    happens. Measured in the switches' own state callbacks, not polled."""
    prefdir = tmp_path / "prefs"
    prefdir.mkdir()
    messages = _run_program(overlap_program, prefdir, timeout=120)
    assert "done" in messages, messages[-15:]
    plain = next(m for m in messages if m.startswith("plain starts="))
    starts, _, longest = (int(part.split("=")[1]) for part in plain.split()[1:])
    assert starts == 4 and longest < 100, plain
    ovl = next(m for m in messages if m.startswith("ovl starts="))
    starts, overlaps, longest = (int(part.split("=")[1]) for part in ovl.split()[1:])
    assert starts == 4 and overlaps >= 3 and 900 <= longest <= 1300, ovl  # valve_overlap: 1s


# ----------------------------------------------------------------------------- pump start delays (task 013, round 3)

PUMP_CONFIG = CONFIGS / "garden_zones_pump_sim.yaml"
PUMP_NAME = "garden-zones-pump"


@pytest.mark.unit
def test_pump_test_config_shape() -> None:
    text = PUMP_CONFIG.read_text(encoding="utf-8")
    assert "!secret" not in text
    assert not re.search(r"GPIO\d+", text)
    config = load_esphome_yaml(PUMP_CONFIG)
    assert isinstance(config, dict)
    for forbidden in ("api", "wifi", "ota"):
        assert forbidden not in config
    groups = {g["id"]: g for g in config["garden_zones"]["groups"]}
    assert groups["pa"]["pump_start_pump_delay"] == "1s" and groups["vb"]["pump_start_valve_delay"] == "1s"
    for switch in config["switch"]:
        assert switch.get("restore_mode") == "ALWAYS_OFF", switch.get("id")


def _pump_host_dir() -> Path:
    return REPO_ROOT / ".esphome" / "gz-pump-host" / _resolve("pinned")


@pytest.fixture(scope="module")
def pump_program() -> Path:
    _need_compiler()
    config = _stage(_pump_host_dir(), PUMP_CONFIG, f"{PUMP_NAME}.yaml")
    result = _esphome("pinned", "compile", str(config), timeout=1800)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    program = _pump_host_dir() / ".esphome" / "build" / PUMP_NAME / ".pioenvs" / PUMP_NAME / "program"
    assert program.is_file(), f"host program not found at {program}"
    return program


_EVENT = re.compile(r"ev (\w+) (\d) t=(\d+)$")


@pytest.mark.host
def test_pump_start_delays_host_scenario(pump_program: Path, tmp_path: Path) -> None:
    """With either pump start delay: every zone is open for its full 3 s run, and the pump never runs with no valve
    open except in the start phase before the first valve of a cycle (events come from the switches' callbacks)."""
    prefdir = tmp_path / "prefs"
    prefdir.mkdir()
    messages = _run_program(pump_program, prefdir, timeout=120)
    assert "done" in messages, messages[-15:]
    events = [(m.group(1), int(m.group(2)), int(m.group(3))) for m in map(_EVENT.match, messages) if m]
    for group in ("pa", "vb"):
        mine = [e for e in events if e[0].startswith(group + "_")]
        spans: dict[str, list[tuple[int, int]]] = {}
        open_since: dict[str, int] = {}
        for name, state, t in mine:
            if state:
                open_since.setdefault(name, t)
            elif name in open_since:  # repeated "off" publishes (boot, idempotent turn_off) are not edges
                spans.setdefault(name, []).append((open_since.pop(name), t))
        assert not open_since, f"{group}: an actuator is still on at the end"
        for valve in (f"{group}_v1", f"{group}_v2"):
            assert len(spans[valve]) == 1, (valve, spans)
            length = spans[valve][0][1] - spans[valve][0][0]
            assert 2900 <= length <= 4500, f"{valve} open {length} ms"  # 3 s run (+ a start delay at most)
        # a stock handover may switch the pump off and on again within the same millisecond: that is one session
        sessions: list[list[int]] = []
        for begin, end in spans[f"{group}_pump"]:
            if sessions and begin - sessions[-1][1] < 50:
                sessions[-1][1] = end
            else:
                sessions.append([begin, end])
        assert len(sessions) == 1, spans
        pump_on, pump_off = sessions[0]
        valves = sorted(span for v in (f"{group}_v1", f"{group}_v2") for span in spans[v])
        first_on, last_off = valves[0][0], max(end for _, end in valves)
        # no gap between the zones in which the pump runs with no valve open
        gap_start = valves[0][1]
        gap_end = valves[1][0]
        assert gap_end - gap_start < 100 or gap_end < gap_start, f"{group}: pump idle {gap_end - gap_start} ms between zones"
        # the only allowed idle phase is the start phase before the first valve
        assert first_on - pump_on <= 1300, f"{group}: pump ran {first_on - pump_on} ms before the first valve"
        assert pump_off - last_off <= 300, f"{group}: pump ran {pump_off - last_off} ms after the last valve"


# ------------------------------------------------------------------------- `never` and long limits (task 013, round 3)

_NEVER_BODY = """\
garden_zones:
  groups:
    - {id: g, max_parallel: all, pump_switch_id: gz_pump, max_on_time: never, pump_max_on_time: never,
       pump_idle_timeout: never}
    - {id: h, max_parallel: all, max_on_time: 6h}
  zones:
    - {group: g, valve_switch: Z1, valve_switch_id: board_relay_1, run_duration: 2s}
    - {group: h, valve_switch: Z2, valve_switch_id: board_relay_2, run_duration_number: Z time, max_on_time: never}
    - {group: h, valve_switch: Z3, valve_switch_id: board_relay_3, run_duration: 5h}
"""


def _write_never_config(tmp_path: Path, body: str) -> Path:
    _stage_groups(tmp_path).unlink()
    (tmp_path / ZONE_ENTRY.name).unlink()
    config = tmp_path / "gz-error.yaml"
    config.write_text(_SAFETY_HEAD + body, encoding="utf-8")
    return config


@pytest.mark.config
def test_safety_never_and_long_limits_config(tmp_path: Path) -> None:
    """`never` is accepted at every level (group, zone override, pump limits), 6 h and a 5 h run are fine, and the
    run-vs-limit checks are skipped for a `never` zone (its run_duration_number keeps the stock 86400 s max_value)."""
    config = _write_never_config(tmp_path, _NEVER_BODY)
    result = _esphome("pinned", "config", str(config), timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-3000:]
    assert output.count("max_on_time: never") == 3 and "pump_max_on_time: never" in output  # group, zone, pump
    assert "pump_idle_timeout: never" in output and "max_on_time: 6h" in output


@pytest.mark.config
def test_safety_never_codegen(tmp_path: Path) -> None:
    config = _write_never_config(tmp_path, _NEVER_BODY)
    result = _esphome("pinned", "compile", "--only-generate", str(config), timeout=900)
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    main_cpp = (tmp_path / ".esphome" / "build" / "gz-error" / "src" / "main.cpp").read_text(encoding="utf-8")
    # g zone 1 (group never), h zone 0 (zone override never), pump max and pump idle
    assert main_cpp.count("::esphome::garden_zones::watchdog::DISABLED") == 4, main_cpp.count("watchdog::DISABLED")
    assert re.search(r"h_watchdog->add_zone\([^;]*, 21600000\);", main_cpp), "the 6 h group limit reaches the watchdog"
    assert re.search(r"g_watchdog->set_pump\(gz_pump, [^;]*DISABLED, [^;]*DISABLED\);", main_cpp)
