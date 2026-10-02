"""Shared helpers for the repo checks."""

from __future__ import annotations

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
