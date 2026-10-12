"""Shared helpers for the repo checks."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


class _EsphomeLoader(yaml.SafeLoader):
    """SafeLoader that accepts ESPHome tags (!secret, !include, !lambda, !extend, ...) as plain values."""


def _any_tag(loader: yaml.Loader, tag_suffix: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.ScalarNode):
        return {"__tag__": tag_suffix, "value": loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {"__tag__": tag_suffix, "value": loader.construct_sequence(node)}
    return {"__tag__": tag_suffix, "value": loader.construct_mapping(node)}


_EsphomeLoader.add_multi_constructor("!", _any_tag)


def load_esphome_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_EsphomeLoader)  # noqa: S506 - SafeLoader subclass


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [REPO_ROOT / name for name in out.split("\0") if name]



def require_sdl_or_skip() -> None:
    """The sim entry file needs SDL2 dev files (`sdl2-config`) even for `esphome config`.

    Skips with a reason when they are missing, unless GP_REQUIRE_SDL=1 (CI), where it fails instead.
    """
    if shutil.which("sdl2-config") is not None:
        return
    reason = "sdl2-config not found: the PC emulator config needs SDL2 dev files (libsdl2-dev) even for `esphome config`"
    if os.environ.get("GP_REQUIRE_SDL") == "1":
        pytest.fail(reason + " (GP_REQUIRE_SDL=1)")
    pytest.skip(reason)


# ---------------------------------------------------------------------------------------------------- xdist grouping

# Host-build fixture -> xdist group. Every group is one fixed build directory (incremental rebuilds), and two workers
# must never build into the same directory at the same time: all tests that use the fixture run on one worker
# (`script/test` passes `--dist loadgroup`). `{param}` is replaced by the version param of a parametrized fixture.
# `host_build_pinned` and `host_build[pinned]` share `.esphome/gz-host/<pinned>`, hence the same group name.
HOST_GROUPS: dict[str, str] = {
    "host_build": "gz-host-{resolved}",
    "host_build_pinned": "gz-host-{resolved}",
    "groups_program": "gz-groups",
    "safety_program": "gz-safety",
    "overlap_program": "gz-overlap",
    "pump_program": "gz-pump",
    "scenario_program": "greenhouse-host",
    "gp_program": "gp-host",
    "schedule_program": "schedule-host",
}
# Whole modules that share one fixed directory / one TCP port without a fixture (script/sim-ui builds .esphome/sim-build).
HOST_MODULE_GROUPS: dict[str, str] = {"test_sim_ui": "sim-ui"}


def _resolved_version(label: str) -> str:
    """The ESPHome version behind a label (what script/_esphome --resolve prints): the build directory is keyed by it."""
    import tomllib

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if label == "minimum":
        return project["tool"]["garden-pilot"]["esphome-minimum"]
    for dep in project["dependency-groups"]["dev"]:
        if dep.startswith("esphome=="):
            return dep.split("==", 1)[1]
    return label


def host_group(fixturenames: list[str], params: dict, module: str, is_host: bool) -> str | None:
    for name, group in HOST_GROUPS.items():
        if name in fixturenames:
            # keyed by the resolved version, like the build directory: pinned == minimum would share one group
            return group.format(resolved=_resolved_version(params.get(name, "pinned")))
    return HOST_MODULE_GROUPS.get(module) if is_host else None


# tryfirst: xdist's own hook reads the `xdist_group` marks (it adds the `@group` suffix to the node ids that
# `--dist loadgroup` schedules by); without it the marks arrive too late and nothing is grouped.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        callspec = getattr(item, "callspec", None)
        is_host = item.get_closest_marker("host") is not None
        group = host_group(list(item.fixturenames), callspec.params if callspec else {}, item.module.__name__, is_host)
        if group is not None:
            item.add_marker(pytest.mark.xdist_group(name=group))


# --------------------------------------------------------------------------------------------------------- libfaketime

FAKETIME_GLOBS = ["/usr/lib/*/faketime/libfaketime.so.1", "/usr/lib/faketime/libfaketime.so.1"]


def require_faketime_or_none() -> str | None:
    """Path of libfaketime, or None when it is not installed (the schedule scenario then runs unaligned and slow).

    Fails instead of returning None when GP_REQUIRE_FAKETIME=1 (CI, where the devcontainer image installs it).
    """
    override = os.environ.get("GP_FAKETIME_LIB")  # a locally built library, e.g. where the image has none
    if override and Path(override).is_file():
        return override
    for pattern in FAKETIME_GLOBS:
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    if os.environ.get("GP_REQUIRE_FAKETIME") == "1":
        pytest.fail("libfaketime not found (searched " + ", ".join(FAKETIME_GLOBS) + "); install the `libfaketime` package (GP_REQUIRE_FAKETIME=1)")
    return None
