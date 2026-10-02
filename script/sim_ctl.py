"""List, read and set entities of the running PC emulator over the native API (see script/sim-ctl).

Same path as Home Assistant: an `aioesphomeapi` client with the emulator's public dummy key. Only calls the
aioesphomeapi 46.3.0 client has: connect, list_entities_services, subscribe_states, number_command, switch_command,
disconnect. Exit codes: 0 ok, 1 connection/timeout error, 2 usage or entity error.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import re
import struct
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from aioesphomeapi import APIClient, NumberInfo, SensorInfo, SwitchInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
KEY_NAME = "sim_api_encryption_key"
KEY_ENV = "GP_SIM_API_KEY"
HINT = "is the emulator running (script/sim) and is port {port} reachable on {host}?"


class UsageError(Exception):
    """Bad usage or an entity problem: exit code 2."""


def kind_of(info: Any) -> str:
    """Entity kind from the aioesphomeapi class name (NumberInfo -> number)."""
    name = type(info).__name__
    return (name[:-4] if name.endswith("Info") else name).lower()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sim-ctl", description="List, read and set entities of the running PC emulator over the native API."
    )
    parser.add_argument("--host", default="127.0.0.1", help="emulator host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=6053, help="API port (default 6053)")
    parser.add_argument("--key", default=None, help=f"API encryption key (default: ${KEY_ENV}, else secrets.example.yaml)")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds to wait for a connection/state (default 10)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list all entities: kind, object_id, name, state")
    get = sub.add_parser("get", help="print the state of one entity")
    get.add_argument("name", help="object_id or name, case-insensitive")
    set_ = sub.add_parser("set", help="set a number entity")
    set_.add_argument("name")
    set_.add_argument("value", type=float)
    switch = sub.add_parser("switch", help="turn a switch entity on or off")
    switch.add_argument("name")
    switch.add_argument("state", choices=["on", "off"])
    return parser.parse_args(argv)


def default_key(
    args_key: str | None = None, environ: dict[str, str] | None = None, repo_root: Path = REPO_ROOT
) -> str:
    """--key, else env GP_SIM_API_KEY, else the public dummy in secrets.example.yaml (never the real secrets file)."""
    if args_key:
        return args_key
    env = os.environ if environ is None else environ
    if env.get(KEY_ENV):
        return env[KEY_ENV]
    path = repo_root / "secrets.example.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise UsageError(f"cannot read {path.name} for the API key ({err}); pass --key or set {KEY_ENV}") from err
    match = re.search(rf'^{KEY_NAME}:\s*"?([^"\s#]+)"?', text, re.MULTILINE)
    if not match:
        raise UsageError(f"{KEY_NAME} not found in {path.name}; pass --key or set {KEY_ENV}")
    return match.group(1)


def resolve_entity(entities: Sequence[Any], name: str, kind: str | None = None) -> Any:
    """The one entity whose object_id or name equals `name` (case-insensitive); kind: required entity kind."""
    wanted = name.strip().lower()
    found = [e for e in entities if wanted in (e.object_id.lower(), e.name.lower())]
    if not found:
        raise UsageError(f"no entity named {name!r}; try `sim-ctl list`")
    if len(found) > 1:
        options = ", ".join(f"{kind_of(e)}:{e.object_id}" for e in found)
        raise UsageError(f"{name!r} is ambiguous, use an object_id: {options}")
    entity = found[0]
    if kind and kind_of(entity) != kind:
        raise UsageError(f"{entity.object_id} is a {kind_of(entity)}, not a {kind}")
    return entity


def as_float32(value: float) -> float:
    """The value as the device stores it (float32), so a reported state compares equal to what was sent."""
    return struct.unpack("f", struct.pack("f", value))[0]


def check_number_value(info: NumberInfo, value: float) -> None:
    if math.isnan(value) or not info.min_value <= value <= info.max_value:
        raise UsageError(f"{value:g} is outside {info.object_id} range {info.min_value:g}..{info.max_value:g}")
    if info.step > 0:
        steps = (value - info.min_value) / info.step
        if abs(steps - round(steps)) > 1e-4:
            raise UsageError(f"{value:g} is not a multiple of step {info.step:g} (from {info.min_value:g}) of {info.object_id}")


def format_state(state: Any) -> str:
    if state is None or getattr(state, "missing_state", False):
        return "-"
    value = getattr(state, "state", None)
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:g}"
    return "-" if value is None else str(value)


def format_list(entities: Sequence[Any], states: dict[int, Any]) -> list[str]:
    rows = sorted(
        ((kind_of(e), e.object_id, e.name, format_state(states.get(e.key))) for e in entities),
        key=lambda r: (r[0], r[1]),
    )
    return [f"{k:<8} {o:<40} {n:<40} {s}" for k, o, n, s in rows]


async def _wait_for(predicate: Callable[[], bool], timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() >= end:
            return False
        await asyncio.sleep(0.05)
    return True


async def run(args: argparse.Namespace, client: Any, out: Callable[[str], None] = print) -> int:
    """Execute one command on a connected client. Returns the exit code."""
    entities, _services = await client.list_entities_services()
    states: dict[int, Any] = {}
    client.subscribe_states(lambda s: states.__setitem__(s.key, s))
    stateful = {e.key for e in entities if kind_of(e) in {"number", "sensor", "switch"}}
    # The device sends the current states right after subscribing; a short wait is enough.
    await _wait_for(lambda: stateful <= set(states), min(args.timeout, 2.0))

    if args.command == "list":
        for line in format_list(entities, states):
            out(line)
        return 0
    if args.command == "get":
        entity = resolve_entity(entities, args.name)
        out(f"{entity.object_id} = {format_state(states.get(entity.key))}")
        return 0
    if args.command == "set":
        entity = resolve_entity(entities, args.name, "number")
        check_number_value(entity, args.value)
        client.number_command(entity.key, args.value)
        done = await _wait_for(
            lambda: entity.key in states and abs(getattr(states[entity.key], "state", math.nan) - as_float32(args.value)) <= 1e-6 * max(1.0, abs(args.value)),
            args.timeout,
        )
    else:
        entity = resolve_entity(entities, args.name, "switch")
        want = args.state == "on"
        client.switch_command(entity.key, want)
        done = await _wait_for(
            lambda: entity.key in states and getattr(states[entity.key], "state", None) is want, args.timeout
        )
    out(f"{entity.object_id} = {format_state(states.get(entity.key))}")
    if not done:
        print(f"sim-ctl: {entity.object_id} did not report the new state in {args.timeout:g} s", file=sys.stderr)
        return 1
    return 0


def make_client(args: argparse.Namespace) -> Any:
    return APIClient(args.host, args.port, None, noise_psk=default_key(args.key), client_info="sim-ctl")


async def amain(args: argparse.Namespace, client: Any | None = None, out: Callable[[str], None] = print) -> int:
    client = make_client(args) if client is None else client
    try:
        await asyncio.wait_for(client.connect(login=False), args.timeout)
    except Exception as err:  # noqa: BLE001 - every connect failure (OS, timeout, API, encryption) is exit 1
        print(f"sim-ctl: cannot connect to {args.host}:{args.port} ({err or type(err).__name__})", file=sys.stderr)
        print("sim-ctl: " + HINT.format(host=args.host, port=args.port), file=sys.stderr)
        return 1
    try:
        return await run(args, client, out)
    finally:
        await client.disconnect()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(amain(args))
    except UsageError as err:
        print(f"sim-ctl: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
