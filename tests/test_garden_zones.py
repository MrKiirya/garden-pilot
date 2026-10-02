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
SIM_CONFIG = REPO_ROOT / "tests" / "configs" / "garden_zones_sim.yaml"
FORKED = ["__init__.py", "automation.h", "sprinkler.h", "sprinkler.cpp"]
ALL_FILES = [*FORKED, "queue_ops.h", "LICENSE", "PATCHES.md", "README.md"]
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


def _stage(dest: Path) -> Path:
    """Copy the test config and everything it includes to `dest` (the config expects to sit at the root)."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("hardware", "components"):
        shutil.copytree(
            REPO_ROOT / name, dest / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__")
        )
    config = dest / "garden-zones-sim.yaml"
    shutil.copy(SIM_CONFIG, config)
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
