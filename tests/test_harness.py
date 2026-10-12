"""Task 022: the test harness itself (xdist grouping of the host builds)."""

from __future__ import annotations

import re

import pytest

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
    assert not {g.format(param="pinned") for g in others} & {"gz-host-pinned", "gz-host-minimum"}
    # modules without a fixture: only host tests of the sim-ui module are grouped
    assert host_group([], {}, "test_sim_ui", True) == "sim-ui"
    assert host_group([], {}, "test_sim_ui", False) is None
    assert host_group(["tmp_path"], {}, "test_layout", False) is None
