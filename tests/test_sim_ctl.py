"""script/sim_ctl.py: argument parsing, key lookup, entity resolution and commands against a fake client."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest
from aioesphomeapi import NumberInfo, NumberState, SensorInfo, SensorState, SwitchInfo, SwitchState

import re

import yaml

from conftest import REPO_ROOT, _EsphomeLoader

pytestmark = pytest.mark.unit

_spec = importlib.util.spec_from_file_location("sim_ctl", REPO_ROOT / "script" / "sim_ctl.py")
assert _spec and _spec.loader
sim_ctl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim_ctl)

NUMBER = NumberInfo(object_id="sim_soil_moisture", key=1, name="Sim soil moisture", min_value=0, max_value=100, step=1)
SWITCH = SwitchInfo(object_id="sim_auto_drift", key=2, name="Sim auto drift")
SENSOR = SensorInfo(object_id="greenhouse_soil_moisture", key=3, name="Greenhouse soil moisture")
ENTITIES = [SENSOR, SWITCH, NUMBER]


def test_parse_args_defaults_and_commands() -> None:
    args = sim_ctl.parse_args(["list"])
    assert (args.host, args.port, args.timeout, args.command) == ("127.0.0.1", 6053, 10.0, "list")
    assert sim_ctl.parse_args(["get", "x"]).name == "x"
    args = sim_ctl.parse_args(["--host", "h", "--port", "1", "--timeout", "2", "set", "n", "35"])
    assert (args.host, args.port, args.timeout, args.value) == ("h", 1, 2.0, 35.0)
    assert sim_ctl.parse_args(["switch", "s", "on"]).state == "on"


@pytest.mark.parametrize(
    "argv", [[], ["bogus"], ["switch", "s", "maybe"], ["set", "n", "abc"], ["set", "n"], ["get"]]
)
def test_parse_args_bad_usage_exits_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        sim_ctl.parse_args(argv)
    assert exc.value.code == 2


def test_default_key_from_example(tmp_path: Path) -> None:
    (tmp_path / "secrets.example.yaml").write_text('# c\nsim_api_encryption_key: "EXAMPLEKEY="\n', encoding="utf-8")
    (tmp_path / "secrets.yaml").write_text('sim_api_encryption_key: "REALKEY="\n', encoding="utf-8")
    assert sim_ctl.default_key(None, {}, tmp_path) == "EXAMPLEKEY="
    assert sim_ctl.default_key(None, {"GP_SIM_API_KEY": "ENVKEY"}, tmp_path) == "ENVKEY"
    assert sim_ctl.default_key("ARGKEY", {"GP_SIM_API_KEY": "ENVKEY"}, tmp_path) == "ARGKEY"
    (tmp_path / "secrets.example.yaml").write_text("other: 1\n", encoding="utf-8")
    with pytest.raises(sim_ctl.UsageError):
        sim_ctl.default_key(None, {}, tmp_path)


def test_default_key_of_the_repo_is_the_public_dummy() -> None:
    key = sim_ctl.default_key(None, {})
    assert key in (REPO_ROOT / "secrets.example.yaml").read_text(encoding="utf-8")


def test_resolve_entity() -> None:
    assert sim_ctl.resolve_entity(ENTITIES, "sim_soil_moisture") is NUMBER
    assert sim_ctl.resolve_entity(ENTITIES, "SIM SOIL moisture") is NUMBER
    assert sim_ctl.resolve_entity(ENTITIES, "Sim auto drift", "switch") is SWITCH
    with pytest.raises(sim_ctl.UsageError, match="no entity"):
        sim_ctl.resolve_entity(ENTITIES, "nothing")
    twin = NumberInfo(object_id="other", key=9, name="Sim soil moisture", min_value=0, max_value=1)
    with pytest.raises(sim_ctl.UsageError, match="ambiguous.*sim_soil_moisture.*other"):
        sim_ctl.resolve_entity([NUMBER, twin], "sim soil moisture")
    with pytest.raises(sim_ctl.UsageError, match="not a number"):
        sim_ctl.resolve_entity(ENTITIES, "greenhouse_soil_moisture", "number")
    with pytest.raises(sim_ctl.UsageError, match="not a switch"):
        sim_ctl.resolve_entity(ENTITIES, "sim_soil_moisture", "switch")
    sim_ctl.check_number_value(NUMBER, 100)
    for bad in (-1, 100.5, float("nan")):
        with pytest.raises(sim_ctl.UsageError, match="outside"):
            sim_ctl.check_number_value(NUMBER, bad)


class FakeClient:
    """Same method names as aioesphomeapi 46.3.0 APIClient; echoes commands back as states."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.calls: list[tuple] = []
        self.on_state = None
        self.initial = [NumberState(key=1, state=50.0), SwitchState(key=2, state=False), SensorState(key=3, state=50.0)]

    async def connect(self, on_stop=None, login=False, log_errors=True) -> None:
        if self.fail:
            raise self.fail

    async def list_entities_services(self):
        return ENTITIES, []

    def subscribe_states(self, on_state) -> None:
        self.on_state = on_state
        for state in self.initial:
            on_state(state)

    def number_command(self, key: int, state: float, device_id: int = 0) -> None:
        self.calls.append(("number", key, state))
        self.on_state(NumberState(key=key, state=state))

    def switch_command(self, key: int, state: bool, device_id: int = 0) -> None:
        self.calls.append(("switch", key, state))
        self.on_state(SwitchState(key=key, state=state))

    async def disconnect(self, force: bool = False) -> None:
        self.calls.append(("disconnect",))


def _run(argv: list[str], client: FakeClient) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = asyncio.run(sim_ctl.amain(sim_ctl.parse_args(["--timeout", "0.3", *argv]), client, lines.append))
    return code, lines


def test_commands_with_fake_client() -> None:
    client = FakeClient()
    code, lines = _run(["list"], client)
    assert code == 0 and len(lines) == 3
    assert [line.split()[0] for line in lines] == ["number", "sensor", "switch"]
    assert "sim_soil_moisture" in lines[0] and "Sim soil moisture" in lines[0] and lines[0].endswith("50")
    assert lines[2].endswith("off")

    code, lines = _run(["get", "Sim soil moisture"], FakeClient())
    assert (code, lines) == (0, ["sim_soil_moisture = 50"])

    client = FakeClient()
    code, lines = _run(["set", "sim_soil_moisture", "35"], client)
    assert (code, lines) == (0, ["sim_soil_moisture = 35"])
    assert ("number", 1, 35.0) in client.calls and client.calls[-1] == ("disconnect",)

    client = FakeClient()
    code, lines = _run(["switch", "Sim auto drift", "on"], client)
    assert (code, lines) == (0, ["sim_auto_drift = on"])
    assert ("switch", 2, True) in client.calls


def test_usage_errors_do_not_send() -> None:
    client = FakeClient()
    for argv in (["set", "sim_soil_moisture", "500"], ["set", "greenhouse_soil_moisture", "1"],
                 ["switch", "sim_soil_moisture", "on"]):
        with pytest.raises(sim_ctl.UsageError):
            _run(argv, client)
    assert not [c for c in client.calls if c[0] in ("number", "switch")]


def test_connection_failure_exits_1_with_hint(capsys: pytest.CaptureFixture[str]) -> None:
    code, lines = _run(["list"], FakeClient(fail=ConnectionRefusedError("refused")))
    assert code == 1 and lines == []
    err = capsys.readouterr().err
    assert "script/sim" in err and "6053" in err


def test_set_rejects_off_step_values() -> None:
    client = FakeClient()
    with pytest.raises(sim_ctl.UsageError, match="step"):
        _run(["set", "sim_soil_moisture", "35.3"], client)
    assert not [c for c in client.calls if c[0] == "number"]


def test_set_accepts_the_float32_state_the_device_reports() -> None:
    fine = NumberInfo(object_id="fine", key=1, name="Fine", min_value=0, max_value=100, step=0.1)

    class Float32Client(FakeClient):
        async def list_entities_services(self):
            return [fine], []

        def number_command(self, key: int, state: float, device_id: int = 0) -> None:
            self.calls.append(("number", key, state))
            self.on_state(NumberState(key=key, state=sim_ctl.as_float32(state)))

    code, lines = _run(["set", "fine", "99.3"], Float32Client())
    assert code == 0 and lines == ["fine = 99.3"]


def _sim_object_ids() -> set[str]:
    """object_id ESPHome sends for every sim entity: snake_case(sanitize(name)); per-bed names expanded for beds 1..3."""
    from esphome.helpers import sanitize, snake_case

    names: set[str] = set()
    for rel in ("sensors.yaml", "bed_soil.yaml", "drift.yaml"):
        text = (REPO_ROOT / "packages" / "sim" / rel).read_text(encoding="utf-8")
        for bed in ("1", "2", "3"):
            data = yaml.load(  # noqa: S506 - SafeLoader subclass
                text.replace("${bed_name}", f"Greenhouse bed {bed}").replace("${bed}", bed).replace("${relay}", bed),
                Loader=_EsphomeLoader,
            )
            for section in ("number", "sensor", "switch"):
                names |= {i["name"] for i in data.get(section) or []}
    return {snake_case(sanitize(n)) for n in names} | {n.lower() for n in names}


def test_sim_ctl_examples_resolve() -> None:
    ids = _sim_object_ids()
    assert "greenhouse_soil_moisture" in ids and "sim auto drift" in ids
    sources = ["README.md", "README.ru.md", "script/sim-ctl"]
    found = 0
    for rel in sources:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for m in re.finditer(r'script/sim-ctl (?:get|set|switch) ("[^"]+"|[\w]+)', text):
            found += 1
            assert m.group(1).strip('"').lower() in ids, f"{rel}: {m.group(0)}"
    assert found >= 6
