"""Task 022: the test harness itself (xdist grouping of the host builds)."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

import conftest
from conftest import HOST_GROUPS, REPO_ROOT, host_group

pytestmark = pytest.mark.unit

# A module-scoped fixture that builds a host program: `def <name>_program(` or `def host_build...(`.
_BUILDER = re.compile(r'@pytest\.fixture\(scope="module"[^\n]*\)\ndef (\w+_program|host_build\w*)\(')


def test_host_fixtures_are_grouped() -> None:
    found = set()
    for path in sorted((REPO_ROOT / "tests").glob("test_*.py")):
        found.update(_BUILDER.findall(path.read_text(encoding="utf-8")))
    assert found >= {"host_build", "host_build_pinned", "gp_program", "schedule_program", "scenario_program"}, found
    assert found == set(HOST_GROUPS), (sorted(found), sorted(HOST_GROUPS))


def test_host_groups_follow_build_directories() -> None:
    # host_build[pinned] and host_build_pinned build into the same directory: one group
    assert host_group(["host_build"], {"host_build": "pinned"}, "m", True) == host_group(["host_build_pinned"], {}, "m", True)
    assert host_group(["host_build"], {"host_build": "minimum"}, "m", True) != host_group(["host_build"], {"host_build": "pinned"}, "m", True)
    # every other fixture has its own group (one group per fixed directory)
    others = [g for name, g in HOST_GROUPS.items() if name not in {"host_build", "host_build_pinned"}]
    assert len(set(others)) == len(others)
    assert not any(g.startswith("gz-host-") for g in others)
    # modules without a fixture: only host tests of the sim-ui module are grouped
    assert host_group([], {}, "test_sim_ui", True) == "sim-ui"
    assert host_group([], {}, "test_sim_ui", False) is None
    assert host_group(["tmp_path"], {}, "test_layout", False) is None


def test_group_marks_reach_xdist(tmp_path) -> None:
    """Regression: the marks must be added before xdist's own collection hook reads them (tryfirst), or
    `--dist loadgroup` distributes like `load`. Runs a tiny session with the real conftest hook and two workers."""
    assert conftest.pytest_collection_modifyitems.pytest_impl["tryfirst"] is True
    (tmp_path / "conftest.py").write_text(
        "import pytest\n"
        "@pytest.hookimpl(tryfirst=True)\n"
        "def pytest_collection_modifyitems(items):\n"
        "    for item in items:\n"
        "        item.add_marker(pytest.mark.xdist_group(name='g1'))\n",
        encoding="utf-8",
    )
    (tmp_path / "test_x.py").write_text("def test_a():\n    pass\n\ndef test_b():\n    pass\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-n", "2", "--dist", "loadgroup", "-v", "-p", "no:cacheprovider", "test_x.py"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out[-1500:]
    ids = re.findall(r"\[(gw\d+)\] \[ *\d+%\] PASSED test_x\.py::(\S+)", out)
    assert len(ids) == 2 and all(i.endswith("@g1") for _w, i in ids), out[-1500:]
    assert len({w for w, _i in ids}) == 1, "one group, one worker"
