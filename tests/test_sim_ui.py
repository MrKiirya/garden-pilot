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
# The HISTORY header button of the Schedule page and the BACK button of the History page (task 027, design D20:
# packages/lvgl/page_schedules.yaml, packages/greenhouse/lvgl_history.yaml); row 1 TIME ON cell of the History page.
HISTORY_BTN = (196, 1, 72, 20)
HISTORY_BACK_BTN = (8, 210, 92, 26)
HISTORY_ROW1_ON = (158, 44, 66, 18)
GREEN_TEXT = (0x78, 0xDC, 0x77)
# Setup page nav button `setup_nav_btn_water` (packages/lvgl/page_setup.yaml): opens the Schedules page.
WATER_BTN = (164, 204, 76, 32)
# Schedule page (task 030): rows 1 and 4 of the greenhouse list (packages/greenhouse/lvgl_schedules.yaml); a tap on
# row 1 opens the editor, CANCEL (and SAVE) are its bottom buttons.
SCHED_ROW1 = (8, 44, 304, 34)
SCHED_ROW4 = (8, 158, 304, 34)
EDIT_CANCEL = (8, 210, 150, 26)
EDIT_SAVE = (162, 210, 150, 26)
GREEN_FILL = (0x4C, 0xAF, 0x50)
CARD_BG = (0x1C, 0x1B, 0x1B)
PAGE_BG = (0x13, 0x13, 0x13)


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
    nav = load_esphome_yaml(REPO_ROOT / "packages" / "lvgl" / "nav_bar.yaml")  # the shared nav: band at y 201, 1 px border
    band = nav["obj"]
    button = next(w["button"] for w in band["widgets"] if w["button"]["id"] == "${p}nav_btn_setup")
    button = {
        "x": band["x"] + button["x"], "y": band["y"] + band["border_width"] + button["y"],
        "width": button["width"], "height": button["height"],
    }
    assert (int(button["x"]), int(button["y"]), int(button["width"]), int(button["height"])) == SETUP_BTN


def _find_widget(node: object, wid: str) -> dict | None:
    if isinstance(node, dict):
        if node.get("id") == wid:
            return node
        for value in node.values():
            found = _find_widget(value, wid)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_widget(value, wid)
            if found:
                return found
    return None


@pytest.mark.unit
@pytest.mark.parametrize(
    "rel, wid, geometry",
    [
        ("packages/lvgl/page_schedules.yaml", "sched_btn_history", HISTORY_BTN),
        ("packages/greenhouse/lvgl_history.yaml", "gh_hist_btn_back", HISTORY_BACK_BTN),
    ],
)
def test_history_tap_targets_match_yaml(rel: str, wid: str, geometry: tuple[int, int, int, int]) -> None:
    button = _find_widget(load_esphome_yaml(REPO_ROOT / rel), wid)
    assert button, f"{wid} not found in {rel}: update the constants in tests/test_sim_ui.py"
    assert (int(button["x"]), int(button["y"]), int(button["width"]), int(button["height"])) == geometry


@pytest.mark.unit
def test_schedule_tap_targets_match_yaml() -> None:
    """The scenario taps SCHEDULE on the Setup page, a list row and CANCEL, and inspects the pixels of rows 1 and 4."""

    def geometry(node: object, wid: str) -> tuple[int, int, int, int] | None:
        if isinstance(node, dict):
            if node.get("id") == wid and "width" in node:
                return (int(node["x"]), int(node["y"]), int(node["width"]), int(node["height"]))
            for value in node.values():
                found = geometry(value, wid)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = geometry(value, wid)
                if found:
                    return found
        return None

    nav = load_esphome_yaml(REPO_ROOT / "packages" / "lvgl" / "nav_bar.yaml")  # shared nav, children inside the border
    band = nav["obj"]
    x, y, w, h = geometry(nav, "${p}nav_btn_water")
    assert (band["x"] + x, band["y"] + band["border_width"] + y, w, h) == WATER_BTN
    setup = load_esphome_yaml(REPO_ROOT / "packages" / "lvgl" / "page_setup.yaml")
    from test_screens_schedules import _rows_data  # the rows and buttons come from small includes with vars

    rows = _rows_data()
    assert geometry(rows, "gh_sched_row1") == SCHED_ROW1
    assert geometry(rows, "gh_sched_row4") == SCHED_ROW4
    assert geometry(rows, "gh_sed_btn_cancel") == EDIT_CANCEL
    assert geometry(rows, "gh_sed_btn_save") == EDIT_SAVE


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

        # Setup -> SCHEDULE: the list shows the four slot rows (all OFF)
        wx, wy, ww, wh = WATER_BTN
        tapped = _sim_ui("tap", str(wx + ww // 2), str(wy + wh // 2), env=env)
        assert tapped.returncode == 0, tapped.stderr
        time.sleep(1.5)  # the rows are drawn by the 1 s poller
        shot = _sim_ui("shot", "schedules", env=env)
        assert shot.returncode == 0, shot.stderr
        sched_img = Image.open(REPO_ROOT / ".esphome" / "shots" / "schedules.png").convert("RGB")
        assert not sim_ui.looks_blank(sched_img)
        diff = ImageChops.difference(setup_img, sched_img).convert("L").point(lambda v: 255 if v else 0)
        assert diff.histogram()[255] / (320 * 240) > 0.02, "the Schedule page looks like the Setup page"

        def near(pixel: tuple[int, ...], want: tuple[int, int, int]) -> bool:
            return all(abs(a - b) <= 8 for a, b in zip(pixel, want))

        for rx, ry, rw, rh in (SCHED_ROW1, SCHED_ROW4):
            assert near(sched_img.getpixel((rx + rw // 2, ry + rh - 4)), CARD_BG), f"slot row at y={ry} is not drawn"

        # row 1 -> the editor (SAVE is green-fill: a slot that is off can always be saved)
        rx, ry, rw, rh = SCHED_ROW1
        tapped = _sim_ui("tap", str(rx + rw // 2), str(ry + rh // 2), env=env)
        assert tapped.returncode == 0, tapped.stderr
        time.sleep(0.5)
        shot = _sim_ui("shot", "schedule_edit", env=env)
        assert shot.returncode == 0, shot.stderr
        edit_img = Image.open(REPO_ROOT / ".esphome" / "shots" / "schedule_edit.png").convert("RGB")
        diff = ImageChops.difference(sched_img, edit_img).convert("L").point(lambda v: 255 if v else 0)
        assert diff.histogram()[255] / (320 * 240) > 0.02, "the editor looks like the list"
        sx, sy, sw, sh = EDIT_SAVE
        assert near(edit_img.getpixel((sx + 8, sy + sh // 2)), GREEN_FILL), "SAVE is not green-fill"

        # CANCEL -> back on the list
        cx, cy, cw, ch = EDIT_CANCEL
        tapped = _sim_ui("tap", str(cx + cw // 2), str(cy + ch // 2), env=env)
        assert tapped.returncode == 0, tapped.stderr
        time.sleep(0.5)
        shot = _sim_ui("shot", "schedule_back", env=env)
        assert shot.returncode == 0, shot.stderr
        back_img = Image.open(REPO_ROOT / ".esphome" / "shots" / "schedule_back.png").convert("RGB")
        assert near(back_img.getpixel((rx + rw // 2, ry + rh - 4)), CARD_BG), "CANCEL did not return to the list"
        # probe the right end of SAVE: on the list that spot is the inactive SETUP nav button (the left end of SAVE
        # overlaps the active, green SCHEDULE nav button)
        assert not near(back_img.getpixel((sx + sw - 30, sy + sh // 2)), GREEN_FILL), "still on the editor after CANCEL"

        # Task 027 (D20): Schedule page > HISTORY (empty) > a zone starts: row 1 is live and green > BACK.
        def tap_and_shot(button: tuple[int, int, int, int], name: str) -> Image.Image:
            bx, by, bw, bh = button
            assert _sim_ui("tap", str(bx + bw // 2), str(by + bh // 2), env=env).returncode == 0
            return shot_of(name)

        def shot_of(name: str) -> Image.Image:
            assert _sim_ui("shot", name, env=env).returncode == 0
            image = Image.open(REPO_ROOT / ".esphome" / "shots" / f"{name}.png").convert("RGB")
            assert image.size == (320, 240) and not sim_ui.looks_blank(image), name
            return image

        def changed_share(a: Image.Image, b: Image.Image) -> float:
            mask = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v else 0)
            return mask.histogram()[255] / (320 * 240)

        def has_colour(image: Image.Image, box: tuple[int, int, int, int], rgb: tuple[int, int, int]) -> bool:
            bx, by, bw, bh = box
            return any(near(px, rgb) for px in image.crop((bx, by, bx + bw, by + bh)).getdata())

        # The History BACK button (ghost: text-dim #becab9 outline and text) is drawn inside its box; a single pixel
        # is fragile (RGB565 rounding, 1 px border), so look for the colour anywhere in the box.
        def back_drawn(image: Image.Image) -> bool:
            return has_colour(image, HISTORY_BACK_BTN, (0xBE, 0xCA, 0xB9))

        # tap the right end of HISTORY: the emulator-only SIM button on the top layer covers the header centre
        hx, hy, hw, hh = HISTORY_BTN
        assert _sim_ui("tap", str(hx + hw - 6), str(hy + hh // 2), env=env).returncode == 0
        history_img = shot_of("history")
        assert changed_share(back_img, history_img) > 0.02, "tapping HISTORY did not change the screen"
        assert back_drawn(history_img), "the History BACK button is not drawn"
        assert not has_colour(history_img, HISTORY_ROW1_ON, GREEN_TEXT), "an empty history shows a live row"

        # a zone starts (the zone switch is the Home Assistant path): row 1 is open, its TIME ON is green
        started = subprocess.run(
            ["sh", "script/sim-ctl", "switch", "Greenhouse bed 1", "on"], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120, check=False
        )
        assert started.returncode == 0, started.stderr
        time.sleep(5)  # the engine opens the valve after its switching delay; the page polls every second
        live_img = shot_of("history_live")
        assert has_colour(live_img, HISTORY_ROW1_ON, GREEN_TEXT), "row 1 is not live (green TIME ON)"
        time.sleep(2)
        live_again = shot_of("history_live2")
        assert has_colour(live_again, HISTORY_ROW1_ON, GREEN_TEXT), "the live row disappeared"
        subprocess.run(
            ["sh", "script/sim-ctl", "switch", "Greenhouse bed 1", "off"], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120, check=False
        )

        hback_img = tap_and_shot(HISTORY_BACK_BTN, "history_back")
        assert changed_share(live_again, hback_img) > 0.02, "tapping BACK did not leave the History page"
        assert not back_drawn(hback_img), "still on the History page"
        assert near(hback_img.getpixel((rx + rw // 2, ry + rh - 4)), CARD_BG), "BACK did not return to the Schedule list"
    finally:
        _sim_ui("stop", env=env)
    assert pids, "start did not record any pids"
    assert not sim_ui._group_has_live(pids["sim"]), "emulator still running after stop"
    assert not sim_ui._alive(pids["xvfb"]), "Xvfb still running after stop"
