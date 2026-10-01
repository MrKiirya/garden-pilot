"""Shared helpers for the repo checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

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

