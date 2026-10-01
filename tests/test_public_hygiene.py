"""Tracked files must not leak private network details or local paths (public repo)."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import pytest

from conftest import REPO_ROOT, tracked_files

pytestmark = pytest.mark.unit

IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
LOCAL_PATH = re.compile(r"(/var/mnt/|/var/home/|/home/[a-z_][a-z0-9_-]*/|[A-Za-z]:\\Users\\)")
# Files allowed to mention these patterns because they *describe* the rule.
ALLOWED = {"tests/test_public_hygiene.py"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".woff", ".woff2", ".bin"}


def _text_files() -> list[Path]:
    files = []
    for path in tracked_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED or path.suffix in BINARY_SUFFIXES or rel == "uv.lock" or not path.is_file():
            continue
        files.append(path)
    return files


@pytest.mark.parametrize("path", _text_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_no_private_ip_addresses(path: Path) -> None:
    for match in IPV4.findall(path.read_text(encoding="utf-8", errors="replace")):
        try:
            address = ipaddress.ip_address(match)
        except ValueError:
            continue  # version numbers like 1.2.3.400
        assert not address.is_private or address.is_loopback, f"private IP {match} in {path.name}"


@pytest.mark.parametrize("path", _text_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_no_local_absolute_paths(path: Path) -> None:
    found = LOCAL_PATH.findall(path.read_text(encoding="utf-8", errors="replace"))
    assert not found, f"local path {found[0]!r} in {path.name}"
