"""Tracked and new (untracked, not ignored) files must not leak private network details or local paths."""

from __future__ import annotations

import ipaddress
import re
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_ROOT, tracked_files

pytestmark = pytest.mark.unit

# A trailing dot is fine (end of a sentence); a trailing ".digit" means a longer version number.
IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?!\.?\d)")
LOCAL_PATH = re.compile(
    r"(?<![\w.:/])(/var/mnt/|/var/home/|/run/media/[^/\s]+/|/home/(?!vscode/)[a-z_][a-z0-9_-]*/|/root/|/Users/[^/\s]+/"
    r"|[A-Za-z]:[\\/]Users[\\/])"
)
# Shared address space (RFC 6598): Tailscale and carrier-grade NAT. Not covered by `is_private`.
CGNAT = ipaddress.ip_network("100.64.0.0/10")
# Files allowed to mention these patterns because they *describe* the rule. Example data in this file
# must be fictional: it is exempt from the scan itself.
ALLOWED = {"tests/test_public_hygiene.py"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".woff", ".woff2", ".bin"}


def leaked_ips(text: str) -> list[str]:
    """Private, link-local or CGNAT IPv4 addresses in `text` (loopback is allowed)."""
    leaks = []
    for match in IPV4.findall(text):
        octets = match.split(".")
        if any(int(octet) > 255 for octet in octets):
            continue
        address = ipaddress.ip_address(".".join(str(int(octet)) for octet in octets))  # drop leading zeros
        if address.is_loopback or address.is_unspecified:
            continue
        if address.is_private or address in CGNAT:
            leaks.append(match)
    return leaks


def _untracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [REPO_ROOT / name for name in out.split("\0") if name]


def _text_files() -> list[Path]:
    files = []
    for path in tracked_files() + _untracked_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED or path.suffix in BINARY_SUFFIXES or rel == "uv.lock" or not path.is_file():
            continue
        files.append(path)
    return files


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Connect to 192.168.1.2.", ["192.168.1.2"]),
        ("ha at 192.168.1.2:8080", ["192.168.1.2"]),
        ("gateway 10.0.0.5", ["10.0.0.5"]),
        ("padded 192.168.001.002", ["192.168.001.002"]),
        ("tailscale 100.101.102.103", ["100.101.102.103"]),
        ("version v1.2.3.4 and 1.2.3.4.5", []),
        ("loopback 127.0.0.1 and any 0.0.0.0", []),
        ("public 8.8.8.8", []),
        ("placeholder 192.168.x.x", []),
    ],
)
def test_ip_matcher(text: str, expected: list[str]) -> None:
    assert leaked_ips(text) == expected


@pytest.mark.parametrize(
    "text",
    ["/var/mnt/disk/x", "/home/alice/x", "/Users/alice/x", "C:\\Users\\bob", "C:/Users/bob", "/run/media/al/usb"],
)
def test_local_path_matcher(text: str) -> None:
    assert LOCAL_PATH.search(text)


@pytest.mark.parametrize("text", ["/home/vscode/.cache", "/home/vscode/"])
def test_container_user_home_is_allowed(text: str) -> None:
    # The devcontainer base image's fixed, generic user; not a local path.
    assert not LOCAL_PATH.search(text)


@pytest.mark.parametrize("text", ["/home/vscodex/.cache", "/home/alice/.cache", "/home/myvscode/x"])
def test_other_home_users_are_still_flagged(text: str) -> None:
    assert LOCAL_PATH.search(text)


@pytest.mark.parametrize("path", _text_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_no_private_ip_addresses(path: Path) -> None:
    leaks = leaked_ips(path.read_text(encoding="utf-8", errors="replace"))
    assert not leaks, f"private IP {leaks[0]} in {path.name}"


@pytest.mark.parametrize("path", _text_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_no_local_absolute_paths(path: Path) -> None:
    found = LOCAL_PATH.findall(path.read_text(encoding="utf-8", errors="replace"))
    assert not found, f"local path {found[0]!r} in {path.name}"
