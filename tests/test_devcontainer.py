"""Static checks of the devcontainer configs (no container engine needed)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.unit

DEVCONTAINER_DIR = REPO_ROOT / ".devcontainer"
DEFAULT = DEVCONTAINER_DIR / "devcontainer.json"
VARIANTS = sorted(DEVCONTAINER_DIR.glob("*/devcontainer.json"))
DOCKERFILE = DEVCONTAINER_DIR / "Dockerfile"
HOME = "/home/vscode"
DISPLAY_ENV = {"DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "SDL_VIDEODRIVER", "PULSE_SERVER"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_paths(path: Path) -> tuple[Path, Path]:
    build = load(path)["build"]
    context = (path.parent / build.get("context", ".")).resolve()
    dockerfile = (path.parent / build["dockerfile"]).resolve() if "dockerfile" in build else context / "Dockerfile"
    # Per the spec, `dockerfile` is relative to devcontainer.json, `context` too.
    return dockerfile, context


def volume_mounts(cfg: dict) -> dict[str, str]:
    """target -> source for `type=volume` mounts."""
    result = {}
    for mount in cfg.get("mounts", []):
        parts = dict(p.split("=", 1) for p in mount.split(",") if "=" in p)
        if parts.get("type") == "volume":
            result[parts["target"]] = parts["source"]
    return result


def is_display_mount(mount: str) -> bool:
    return "type=bind" in mount


def test_configs_exist() -> None:
    assert DEFAULT.is_file()
    assert VARIANTS, "expected at least the SDL variant"


def test_configs_are_strict_json() -> None:
    for path in [DEFAULT, *VARIANTS]:
        assert isinstance(load(path), dict), path


def test_variants_share_the_image() -> None:
    base = load(DEFAULT)
    for path in VARIANTS:
        assert build_paths(path) == build_paths(DEFAULT), path
        assert load(path)["build"].get("args") == base["build"].get("args")


def test_build_context_is_devcontainer_dir() -> None:
    for path in [DEFAULT, *VARIANTS]:
        assert build_paths(path)[1] == DEVCONTAINER_DIR.resolve(), path


def test_variants_differ_only_in_display_settings() -> None:
    base = load(DEFAULT)
    for path in VARIANTS:
        cfg = copy.deepcopy(load(path))
        cfg.pop("name", None)
        cfg.get("build", {}).pop("dockerfile", None)
        cfg.get("build", {}).pop("context", None)
        cfg["mounts"] = [m for m in cfg.get("mounts", []) if not is_display_mount(m)]
        for key in DISPLAY_ENV:
            cfg.get("containerEnv", {}).pop(key, None)
        expected = copy.deepcopy(base)
        expected.pop("name", None)
        expected["build"].pop("dockerfile", None)
        expected["build"].pop("context", None)
        assert cfg == expected, path


def test_default_has_no_host_display() -> None:
    cfg = load(DEFAULT)
    assert not [m for m in cfg.get("mounts", []) if is_display_mount(m)]
    assert not DISPLAY_ENV & set(cfg.get("containerEnv", {}))
    assert not DISPLAY_ENV & set(cfg.get("remoteEnv", {}))
    text = DEFAULT.read_text(encoding="utf-8")
    for needle in ("X11-unix", "wslg", "XAUTHORITY"):
        assert needle not in text


def test_sdl_variant_forwards_x11() -> None:
    sdl = DEVCONTAINER_DIR / "sdl" / "devcontainer.json"
    cfg = load(sdl)
    assert any("/tmp/.X11-unix" in m and "type=bind" in m for m in cfg["mounts"])
    assert "DISPLAY" in cfg["containerEnv"]
    assert "XAUTHORITY" not in sdl.read_text(encoding="utf-8")


def test_caches_are_named_volumes() -> None:
    volumes = volume_mounts(load(DEFAULT))
    assert f"{HOME}/.cache" in volumes
    assert f"{HOME}/.platformio" in volumes


def test_run_args_are_engine_neutral() -> None:
    args = load(DEFAULT)["runArgs"]
    joined = " ".join(args)
    for forbidden in ("--userns", "keep-id", "--device-cgroup-rule", "--privileged", "--network=host"):
        assert forbidden not in joined
    for arg in args:
        if arg.startswith(("--device", "--group-add")):
            assert re.search(r"\$\{localEnv:\w+:[^}]+\}", arg), arg
            assert "keep-groups" not in arg
    assert "--security-opt" in args and "label=disable" in args


def _from_line() -> str:
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("FROM mcr.microsoft.com/devcontainers/python"):
            return line
    raise AssertionError("no FROM")


def test_base_image_matches_python_version() -> None:
    python = (REPO_ROOT / ".python-version").read_text().strip()
    line = _from_line()
    # Tag: `<python>-<debian>` (the form Dependabot proposes) or `<image-major>-<python>-<debian>`.
    match = re.match(
        r"FROM mcr\.microsoft\.com/devcontainers/python:(?:\d+-)?(\d+\.\d+)-(\w+)@sha256:[0-9a-f]{64}", line
    )
    assert match, line
    assert match.group(1) == python


def test_uv_is_pinned() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^FROM ghcr\.io/astral-sh/uv:\d+\.\d+\.\d+@sha256:[0-9a-f]{64} AS uv$", text, re.M)
    assert "COPY --from=uv /uv /uvx /bin/" in text


def test_esphome_comes_only_from_uv_lock() -> None:
    for path in DEVCONTAINER_DIR.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "esphome/esphome" not in text, path
            assert not re.search(r"(pip|pipx|uv pip)\s+install[^\n]*esphome", text), path
    assert load(DEFAULT)["postCreateCommand"] == "script/setup"


def test_venv_is_outside_workspace() -> None:
    cfg = load(DEFAULT)
    env = {**cfg["containerEnv"], **cfg.get("remoteEnv", {})}
    venv = env["UV_PROJECT_ENVIRONMENT"]
    assert venv.startswith("/") and not venv.startswith("/workspaces")
    assert cfg["customizations"]["vscode"]["settings"]["python.defaultInterpreterPath"].startswith(venv)
    assert any(part.startswith(f"{venv}/bin") for part in env["PATH"].split(":"))


def test_claude_code_is_not_installed_by_default() -> None:
    cfg = load(DEFAULT)
    text = "".join(p.read_text(encoding="utf-8") for p in DEVCONTAINER_DIR.rglob("*") if p.is_file())
    assert "anthropics/devcontainer-features" not in text
    assert not re.search(r"claude-code|@anthropic", DOCKERFILE.read_text(encoding="utf-8"))
    assert "anthropic.claude-code" not in cfg["customizations"]["vscode"]["extensions"]
    assert cfg["containerEnv"]["CLAUDE_CONFIG_DIR"] in volume_mounts(cfg)
    assert cfg["containerEnv"]["CLAUDE_CONFIG_DIR"] == f"{HOME}/.claude"


def test_vscode_associations_are_carried_over() -> None:
    wanted = json.loads((REPO_ROOT / ".vscode" / "settings.json").read_text())["files.associations"]
    have = load(DEFAULT)["customizations"]["vscode"]["settings"]["files.associations"]
    assert wanted.items() <= have.items()


def test_no_secrets_in_image() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(COPY|ADD)\s+(?!--from=)", text, re.M)
    for needle in ("secrets", "!secret", ".env"):
        assert needle not in text


def test_sdl_smoke_script_is_executable() -> None:
    script = REPO_ROOT / "script" / "sdl-smoke"
    assert script.is_file()
    assert script.stat().st_mode & 0o111


def test_vscode_extensions_are_a_named_volume() -> None:
    # Avoids reinstalling VS Code server extensions on every container rebuild.
    for path in [DEFAULT, *VARIANTS]:
        assert f"{HOME}/.vscode-server/extensions" in volume_mounts(load(path)), path
    assert f"{HOME}/.vscode-server/extensions" in DOCKERFILE.read_text(encoding="utf-8")
