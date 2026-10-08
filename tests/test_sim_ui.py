"""script/sim_ui.py: pure helpers (unit) and the headless emulator screenshot + tap scenario (host)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from conftest import REPO_ROOT, load_esphome_yaml

_spec = importlib.util.spec_from_file_location("sim_ui", REPO_ROOT / "script" / "sim_ui.py")
assert _spec and _spec.loader
sim_ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim_ui)

# Home bottom navigation button `nav_btn_setup` in packages/lvgl/page_home.yaml (x, y, width, height).
SETUP_BTN = (244, 204, 72, 32)


# ---------------------------------------------------------------------------------------------- unit


@pytest.mark.unit
def test_display_size_matches_sdl_package() -> None:
    assert (sim_ui.WIDTH, sim_ui.HEIGHT) == (320, 240)
    cfg = load_esphome_yaml(REPO_ROOT / "packages" / "display_sdl.yaml")
    dims = cfg["display"][0]["dimensions"]
    assert (dims["width"], dims["height"]) == (sim_ui.WIDTH, sim_ui.HEIGHT)


@pytest.mark.unit
def test_to_screen_maps_with_window_offset() -> None:
    box = (160, 120, 480, 360)
    assert sim_ui.to_screen(box, 0, 0) == (160, 120)
    assert sim_ui.to_screen(box, 319, 239) == (479, 359)


@pytest.mark.unit
@pytest.mark.parametrize("x, y", [(-1, 0), (320, 0), (0, -1), (0, 240)])
def test_to_screen_rejects_out_of_range(x: int, y: int) -> None:
    with pytest.raises(ValueError):
        sim_ui.to_screen((160, 120, 480, 360), x, y)


@pytest.mark.unit
def test_parse_window_geometry() -> None:
    text = "WINDOW=12582913\nX=160\nY=120\nWIDTH=320\nHEIGHT=240\nSCREEN=0\n"
    assert sim_ui.parse_window_geometry(text) == (160, 120, 480, 360)
    with pytest.raises(ValueError):
        sim_ui.parse_window_geometry("WINDOW=1\nX=160\nY=120\nWIDTH=320\n")


@pytest.mark.unit
def test_tap_steps_press_move_release() -> None:
    steps = sim_ui.tap_steps(440, 340)
    argvs = [argv for argv, _pause in steps]
    assert argvs == [["mousemove", "440", "340"], ["mousedown", "1"], ["mousemove", "441", "341"], ["mouseup", "1"]]
    assert all("click" not in argv for argv in argvs)
    # The pause after the press and after the move is what LVGL needs to register the touch.
    assert all(pause >= 0.2 for argv, pause in steps[:3])


@pytest.mark.unit
def test_shot_path() -> None:
    shots = REPO_ROOT / ".esphome" / "shots"
    default = sim_ui.shot_path(None)
    assert default.parent == shots and re.fullmatch(r"shot-\d{8}-\d{6}\.png", default.name)
    assert sim_ui.shot_path("home") == shots / "home.png"
    for bad in ("../x", "a/b", "", ".", "..", "a b"):
        with pytest.raises(ValueError):
            sim_ui.shot_path(bad)


@pytest.mark.unit
def test_looks_blank() -> None:
    image = Image.new("RGB", (320, 240), (10, 20, 30))
    assert sim_ui.looks_blank(image)
    image.paste((200, 200, 200), (10, 10, 60, 40))
    assert not sim_ui.looks_blank(image)


class _FakeSim:
    returncode = 3

    def __init__(self, alive: bool = True) -> None:
        self.alive = alive

    def poll(self) -> int | None:
        return None if self.alive else self.returncode


@pytest.mark.unit
def test_wait_ready_needs_port_and_window_not_log(monkeypatch: pytest.MonkeyPatch) -> None:
    # the log has no ready line at all (block-buffered stdout); port opens on the 2nd poll, window on the 3rd
    ports = iter([False, True, True])
    windows = iter([False, True])

    def fake_window(display: str, timeout: float = 30.0) -> tuple[int, int, int, int]:
        if not next(windows):
            raise sim_ui.SessionError("no window")
        return (1, 2, 321, 242)

    monkeypatch.setattr(sim_ui, "port_busy", lambda *a, **k: next(ports))
    monkeypatch.setattr(sim_ui, "find_window", fake_window)
    assert sim_ui._wait_ready(_FakeSim(), 10, ":99", poll=0.01) == (1, 2, 321, 242)


@pytest.mark.unit
def test_wait_ready_times_out_and_detects_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sim_ui, "port_busy", lambda *a, **k: False)
    with pytest.raises(sim_ui.SessionError, match="timeout"):
        sim_ui._wait_ready(_FakeSim(), 0.05, ":99", poll=0.01)
    with pytest.raises(sim_ui.SessionError, match="exited"):
        sim_ui._wait_ready(_FakeSim(alive=False), 5, ":99", poll=0.01)


@pytest.mark.unit
def test_ready_line() -> None:
    assert sim_ui.is_ready_line("\x1b[0;32m[12:00:00][I][app:100]: setup() finished successfully!\x1b[0m")
    assert not sim_ui.is_ready_line("\x1b[0;32m[12:00:00][I][app:029]: Running through setup()...\x1b[0m")
    assert not sim_ui.is_ready_line("")


@pytest.mark.unit
def test_outputs_stay_in_esphome_dir() -> None:
    root = (REPO_ROOT / ".esphome").resolve()
    for path in (sim_ui.STATE_PATH, sim_ui.LOG_PATH, sim_ui.shot_path("x"), sim_ui.shot_path(None)):
        assert path.resolve().is_relative_to(root), path


@pytest.mark.unit
def test_tap_target_is_the_setup_button() -> None:
    # Keeps the host scenario honest: the button must still be where the test taps.
    home = load_esphome_yaml(REPO_ROOT / "packages" / "lvgl" / "page_home.yaml")

    def find(node: object) -> dict | None:
        if isinstance(node, dict):
            if node.get("id") == "nav_btn_setup":
                return node
            for value in node.values():
                found = find(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find(value)
                if found:
                    return found
        return None

    button = find(home)
    assert button, "nav_btn_setup not found in page_home.yaml: update SETUP_BTN in tests/test_sim_ui.py"
    assert (int(button["x"]), int(button["y"]), int(button["width"]), int(button["height"])) == SETUP_BTN


@pytest.mark.unit
def test_tap_validates_range_before_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sim_ui, "STATE_PATH", tmp_path / "state.json")  # no session
    assert sim_ui.main(["tap", "320", "0"]) == 2
    assert sim_ui.main(["tap", "10", "10"]) == 1


@pytest.mark.unit
def test_start_with_stale_state_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"display": ":9", "sim_pid": 2**22 + 1, "xvfb_pid": 4242}), encoding="utf-8")
    monkeypatch.setattr(sim_ui, "STATE_PATH", state_path)
    stopped: list[dict] = []
    monkeypatch.setattr(sim_ui, "_stop_all", stopped.append)
    monkeypatch.setattr(sim_ui, "session_running", lambda state: False)
    monkeypatch.setattr(sim_ui, "port_busy", lambda port=6053: True)  # stop right after the cleanup
    assert sim_ui.main(["start"]) == 3
    assert stopped and stopped[0]["xvfb_pid"] == 4242
    assert not state_path.exists()


@pytest.mark.unit
def test_start_xvfb_deadline_holds_when_xvfb_hangs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "Xvfb"
    fake.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    started = time.monotonic()
    with pytest.raises(sim_ui.SessionError):
        sim_ui._start_xvfb(timeout=1)
    assert time.monotonic() - started < 10


# ---------------------------------------------------------------------------------------------- host


def _need(reason: str) -> None:
    """Skip, but fail where the screen test is required (the CI `sim-ui` job: GP_REQUIRE_SIM_UI=1)."""
    if os.environ.get("GP_REQUIRE_SIM_UI") == "1":
        pytest.fail(reason + "; GP_REQUIRE_SIM_UI=1 forbids skipping")
    pytest.skip(reason)


def _port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _sim_ui(*args: str, env: dict[str, str], timeout: float = 1200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "script/sim-ui", *args], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=timeout, check=False
    )


@pytest.mark.host
def test_sim_headless_shot_and_tap(tmp_path: Path) -> None:
    if os.environ.get("GP_SKIP_SIM_UI") == "1":
        pytest.skip("GP_SKIP_SIM_UI=1 (run by the separate CI job sim-ui)")
    for tool in ("Xvfb", "xdotool", "sdl2-config"):
        if shutil.which(tool) is None:
            _need(f"{tool} not found")
    if shutil.which(os.environ.get("CXX", "g++")) is None:
        _need("no C++ compiler")
    if _port_busy(6053):
        _need("port 6053 is busy (a running emulator?)")

    env = {**os.environ, "ESPHOME_PREFDIR": str(tmp_path)}
    env.pop("GP_SIM_UI_DISPLAY", None)
    pids: dict[str, int] = {}
    try:
        started = _sim_ui("start", env=env)
        assert started.returncode == 0, (started.stdout + started.stderr)[-4000:]
        recorded = json.loads(sim_ui.STATE_PATH.read_text(encoding="utf-8"))
        pids = {"sim": recorded["sim_pid"], "xvfb": recorded["xvfb_pid"]}
        home = _sim_ui("shot", "home", env=env)
        assert home.returncode == 0, home.stderr
        home_img = Image.open(REPO_ROOT / ".esphome" / "shots" / "home.png").convert("RGB")
        assert home_img.size == (320, 240)
        assert not sim_ui.looks_blank(home_img)

        x, y, w, h = SETUP_BTN
        tapped = _sim_ui("tap", str(x + w // 2), str(y + h // 2), env=env)
        assert tapped.returncode == 0, tapped.stderr
        setup = _sim_ui("shot", "setup", env=env)
        assert setup.returncode == 0, setup.stderr
        setup_img = Image.open(REPO_ROOT / ".esphome" / "shots" / "setup.png").convert("RGB")
        assert setup_img.size == (320, 240)
        assert not sim_ui.looks_blank(setup_img)
        diff = ImageChops.difference(home_img, setup_img).convert("L").point(lambda v: 255 if v else 0)
        changed = diff.histogram()[255] / (320 * 240)
        assert changed > 0.02, f"only {changed:.1%} of pixels changed after tapping SETUP"
    finally:
        _sim_ui("stop", env=env)
    assert pids, "start did not record any pids"
    assert not sim_ui._group_has_live(pids["sim"]), "emulator still running after stop"
    assert not sim_ui._alive(pids["xvfb"]), "Xvfb still running after stop"
