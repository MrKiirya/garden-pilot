"""Headless screenshots and taps of the PC emulator (see script/sim-ui).

The emulator (script/sim: ESPHome `host` + SDL) runs on a private Xvfb display; screenshots are X-level grabs of its
320x240 window and taps are xdotool press/move/release sequences (a plain `xdotool click` is too short for LVGL).
Never touches the desktop display. Exit codes: 0 ok, 1 failure / no session, 2 usage, 3 already running / port busy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
WIDTH = 320  # keep equal to `dimensions` in packages/display_sdl.yaml
HEIGHT = 240
SCREEN = "640x480x24"
API_PORT = 6053  # fixed by the emulator
OUT_DIR = REPO_ROOT / ".esphome"
STATE_DIR = OUT_DIR / "sim-ui"
STATE_PATH = STATE_DIR / "state.json"
LOG_PATH = STATE_DIR / "sim.log"
SHOTS_DIR = OUT_DIR / "shots"
READY_TEXT = "setup() finished"  # optional log hint only; readiness is port + window (see _wait_ready)
_LINE_BUFFERED = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []  # keeps sim.log useful while running
MIN_COLORS = 2  # an image with fewer distinct colours is blank
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class UsageError(Exception):
    """Bad usage: exit code 2."""


class SessionError(Exception):
    """No session or a failed step: exit code 1."""


class Busy(Exception):
    """A session is running or the API port is busy: exit code 3."""


# ------------------------------------------------------------------------------------------ pure helpers


def to_screen(box: tuple[int, int, int, int], x: int, y: int) -> tuple[int, int]:
    """Display pixel (x, y) to screen coordinates, for a window whose top-left corner is box[:2]."""
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        raise ValueError(f"({x}, {y}) is outside the {WIDTH}x{HEIGHT} display (x 0..{WIDTH - 1}, y 0..{HEIGHT - 1})")
    return box[0] + x, box[1] + y


def parse_window_geometry(text: str) -> tuple[int, int, int, int]:
    """Box (left, top, right, bottom) from `xdotool getwindowgeometry --shell` output."""
    values = dict(re.findall(r"^(\w+)=(-?\d+)\s*$", text, re.M))
    missing = [k for k in ("X", "Y", "WIDTH", "HEIGHT") if k not in values]
    if missing:
        raise ValueError(f"window geometry is missing {', '.join(missing)}")
    x, y, w, h = (int(values[k]) for k in ("X", "Y", "WIDTH", "HEIGHT"))
    return x, y, x + w, y + h


def tap_steps(sx: int, sy: int, pause: float = 0.3) -> list[tuple[list[str], float]]:
    """xdotool argv steps of a tap with the pause after each: the press must be long enough and move for LVGL."""
    return [
        (["mousemove", str(sx), str(sy)], pause),
        (["mousedown", "1"], pause),
        (["mousemove", str(sx + 1), str(sy + 1)], pause),
        (["mouseup", "1"], 0.0),
    ]


def shot_path(name: str | None, now: datetime | None = None) -> Path:
    """.esphome/shots/NAME.png; NAME defaults to shot-YYYYmmdd-HHMMSS and may not contain path separators."""
    if name is None:
        name = (now or datetime.now()).strftime("shot-%Y%m%d-%H%M%S")
    if not NAME_RE.fullmatch(name) or name in (".", ".."):
        raise ValueError(f"bad shot name {name!r}: use letters, digits, '.', '_' and '-' only")
    return SHOTS_DIR / f"{name}.png"


def looks_blank(image: Any) -> bool:
    """True when the image has fewer than MIN_COLORS distinct colours (uniform: nothing was drawn)."""
    colors = image.convert("RGB").getcolors(maxcolors=MIN_COLORS)
    return colors is not None and len(colors) < MIN_COLORS


def is_ready_line(line: str) -> bool:
    return READY_TEXT in _ANSI.sub("", line)


# ------------------------------------------------------------------------------------------ session state


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie child of this process still answers kill(0).
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def load_state() -> dict[str, Any] | None:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def session_running(state: dict[str, Any] | None) -> bool:
    return bool(state) and _group_alive(state["sim_pid"])


def port_busy(port: int = API_PORT) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _need_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SessionError(f"{name} not found (it is in the devcontainer image; install it on a plain host)")


def _xenv(display: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "XAUTHORITY")}
    env["DISPLAY"] = display
    return env


def _xdotool(display: str, *args: str) -> str:
    result = subprocess.run(["xdotool", *args], env=_xenv(display), capture_output=True, text=True, check=False, timeout=30)
    if result.returncode != 0:
        raise SessionError(f"xdotool {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def find_window(display: str, timeout: float = 30.0) -> tuple[int, int, int, int]:
    """Box of the emulator window on the private display (the only top-level window there)."""
    end = time.monotonic() + timeout
    while True:
        found = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", "."],
            env=_xenv(display), capture_output=True, text=True, check=False, timeout=30,
        ).stdout.split()
        for wid in found:
            geometry = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", wid],
                env=_xenv(display), capture_output=True, text=True, check=False, timeout=30,
            ).stdout
            try:
                box = parse_window_geometry(geometry)
            except ValueError:
                continue
            if (box[2] - box[0], box[3] - box[1]) == (WIDTH, HEIGHT):
                return box
        if time.monotonic() >= end:
            raise SessionError(f"no {WIDTH}x{HEIGHT} emulator window found on {display}")
        time.sleep(0.5)


def _start_xvfb(timeout: float = 20.0) -> tuple[subprocess.Popen[bytes], str]:
    read_fd, write_fd = os.pipe()
    proc = subprocess.Popen(
        ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", SCREEN, "-nolisten", "tcp"],
        pass_fds=[write_fd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    os.close(write_fd)
    try:
        data = b""
        end = time.monotonic() + timeout
        while b"\n" not in data:
            remaining = end - time.monotonic()
            if remaining <= 0 or not select.select([read_fd], [], [], remaining)[0]:
                break
            chunk = os.read(read_fd, 64)
            if not chunk:
                break
            data += chunk
        number = data.decode().strip()
        if not number.isdigit():
            raise SessionError("Xvfb did not report a display number")
    except Exception:
        proc.kill()
        raise
    finally:
        os.close(read_fd)
    return proc, f":{number}"


def _kill_group(pgid: int, grace: float = 5.0) -> None:
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if not _group_alive(pgid) or not _group_has_live(pgid):
                return
            time.sleep(0.2)


def _group_has_live(pgid: int) -> bool:
    """True while any non-zombie process is left in the group (zombies of this process do not count)."""
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            rest = stat.read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if rest[0] != "Z" and int(rest[2]) == pgid:
            return True
    return False


# ------------------------------------------------------------------------------------------ commands


def cmd_start(args: argparse.Namespace) -> int:
    state = load_state()
    if session_running(state):
        raise Busy("a sim-ui session is already running (script/sim-ui status | stop)")
    if state:  # stale: the emulator is gone, but Xvfb or other leftovers may survive
        _stop_all(state)
        STATE_PATH.unlink(missing_ok=True)
    if port_busy():
        raise Busy(f"port {API_PORT} is in use (a running script/sim?): stop it first")
    _need_tool("xdotool")
    external = os.environ.get("GP_SIM_UI_DISPLAY")
    xvfb: subprocess.Popen[bytes] | None = None
    if external:
        display = external
    else:
        _need_tool("Xvfb")
        xvfb, display = _start_xvfb()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    sim: subprocess.Popen[bytes] | None = None
    try:
        env = _xenv(display)
        with LOG_PATH.open("wb") as log:
            sim = subprocess.Popen(
                [*_LINE_BUFFERED, "sh", str(REPO_ROOT / "script" / "sim")], cwd=REPO_ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
        STATE_PATH.write_text(
            json.dumps({"display": display, "sim_pid": sim.pid, "xvfb_pid": xvfb.pid if xvfb else None}), encoding="utf-8"
        )
        _wait_ready(sim, args.timeout, display)
        time.sleep(args.settle)
        box = find_window(display)
        state = {"display": display, "sim_pid": sim.pid, "xvfb_pid": xvfb.pid if xvfb else None, "box": list(box)}
        STATE_PATH.write_text(json.dumps(state), encoding="utf-8")
    except BaseException as err:
        _stop_all(load_state() or {"sim_pid": sim.pid if sim else None, "xvfb_pid": xvfb.pid if xvfb else None})
        STATE_PATH.unlink(missing_ok=True)
        if isinstance(err, SessionError):
            tail = LOG_PATH.read_text(errors="replace").splitlines()[-30:] if LOG_PATH.exists() else []
            print("\n".join(_ANSI.sub("", line) for line in tail), file=sys.stderr)
        raise
    print(f"display {display}, window box {box[0]},{box[1]} - {box[2]},{box[3]} ({WIDTH}x{HEIGHT})")
    return 0


def _wait_ready(sim: subprocess.Popen[bytes], timeout: float, display: str, poll: float = 1.0) -> tuple[int, int, int, int]:
    """Ready = API port accepts a connection AND the emulator window exists.

    The log is not used: the program's stdout is block-buffered when redirected to a file (ESPHome 2026.6.3), so
    `setup() finished` may only reach sim.log at exit.
    """
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if port_busy():
            try:
                return find_window(display, timeout=0)
            except SessionError:
                pass
        if sim.poll() is not None:
            raise SessionError(f"script/sim exited with code {sim.returncode} before the UI was ready")
        time.sleep(poll)
    raise SessionError(f"timeout after {timeout:g} s waiting for port {API_PORT} and the emulator window ({LOG_PATH.relative_to(REPO_ROOT)})")


def _session() -> dict[str, Any]:
    state = load_state()
    if not session_running(state) or not state or "box" not in state:
        raise SessionError("no running session: start one with `script/sim-ui start`")
    return state


def cmd_shot(args: argparse.Namespace) -> int:
    try:
        path = shot_path(args.name)
    except ValueError as err:
        raise UsageError(str(err)) from err
    state = _session()
    from PIL import ImageGrab  # imported late: not needed by the other commands

    try:
        image = ImageGrab.grab(xdisplay=state["display"]).crop(tuple(state["box"]))
    except Exception as err:  # noqa: BLE001 - Pillow raises OSError/ValueError depending on the X server
        raise SessionError(f"screen grab failed: {err}") from err
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(path.relative_to(REPO_ROOT))
    return 0


def cmd_tap(args: argparse.Namespace) -> int:
    try:
        to_screen((0, 0, WIDTH, HEIGHT), args.x, args.y)  # range check first: it does not depend on the window box
    except ValueError as err:
        raise UsageError(str(err)) from err
    state = _session()
    sx, sy = to_screen(tuple(state["box"]), args.x, args.y)
    for argv, pause in tap_steps(sx, sy):
        _xdotool(state["display"], *argv)
        time.sleep(pause)
    time.sleep(args.settle)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    state = load_state()
    if not session_running(state) or not state:
        print("not running")
        return 1
    box = state.get("box")
    print(f"running: display {state['display']}, sim pgid {state['sim_pid']}, window box {box}")
    return 0


def _stop_all(state: dict[str, Any]) -> None:
    if state.get("sim_pid"):
        _kill_group(state["sim_pid"])
    xvfb = state.get("xvfb_pid")
    if xvfb and _alive(xvfb):
        _kill_group(xvfb, grace=3.0)


def cmd_stop(_args: argparse.Namespace) -> int:
    state = load_state()
    if state:
        _stop_all(state)
    STATE_PATH.unlink(missing_ok=True)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sim-ui", description="Headless screenshots and taps of the PC emulator.")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="start Xvfb and the emulator, wait until the UI is up")
    start.add_argument("--timeout", type=float, default=900.0, help="seconds to wait for the build and start (default 900)")
    start.add_argument("--settle", type=float, default=5.0, help="seconds to wait after start-up (default 5)")
    shot = sub.add_parser("shot", help="save a 320x240 PNG of the screen to .esphome/shots/NAME.png")
    shot.add_argument("name", nargs="?", default=None)
    tap = sub.add_parser("tap", help="tap at display pixel X Y (x 0..319, y 0..239)")
    tap.add_argument("x", type=int)
    tap.add_argument("y", type=int)
    tap.add_argument("--settle", type=float, default=0.5, help="seconds to wait after the tap (default 0.5)")
    sub.add_parser("status", help="show whether a session runs")
    sub.add_parser("stop", help="stop the emulator and Xvfb (idempotent)")
    return parser.parse_args(argv)


COMMANDS = {"start": cmd_start, "shot": cmd_shot, "tap": cmd_tap, "status": cmd_status, "stop": cmd_stop}


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except UsageError as err:
        print(f"sim-ui: {err}", file=sys.stderr)
        return 2
    except Busy as err:
        print(f"sim-ui: {err}", file=sys.stderr)
        return 3
    except SessionError as err:
        print(f"sim-ui: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
