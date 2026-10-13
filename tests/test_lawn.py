"""Lawn package (task 024): packages/lawn/{irrigation,zone,gp}.yaml, the pump group `lawn_zones` and gp group `gp_lawn`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from conftest import REPO_ROOT, _EsphomeLoader, load_esphome_yaml
from test_layout import DEVICE_ENTRIES, _entry_packages, _strip_comments, _uncomment_examples

pytestmark = pytest.mark.unit

LAWN = REPO_ROOT / "packages" / "lawn"
IRRIGATION = LAWN / "irrigation.yaml"
ZONE = LAWN / "zone.yaml"
GP = LAWN / "gp.yaml"
ZONE_FILE = "packages/lawn/zone.yaml"
IRRIGATION_FILE = "packages/lawn/irrigation.yaml"
GP_FILE = "packages/lawn/gp.yaml"


def _load(path: Path) -> dict:
    data = load_esphome_yaml(path)
    assert isinstance(data, dict), path
    return data


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _code(path: Path) -> str:
    return _strip_comments(path.read_text(encoding="utf-8"))


def _seconds(value: str) -> float:
    m = re.fullmatch(r"(\d+)(s|min|h)", value)
    assert m, value
    return int(m.group(1)) * {"s": 1, "min": 60, "h": 3600}[m.group(2)]


def test_lawn_irrigation_shape() -> None:
    data = _load(IRRIGATION)
    assert set(data) == {"substitutions", "external_components", "garden_zones"}
    groups = data["garden_zones"]["groups"]
    assert len(groups) == 1
    g = groups[0]
    assert g["id"] == "lawn_zones" and g["name"] == "${lawn_name}"
    assert g["max_parallel"] == "${lawn_max_parallel}"
    assert g["max_on_time"] == "${lawn_max_on_time}"
    assert g["pump_switch_id"] == "board_relay_${pump_relay}"
    assert g["pump_max_on_time"] == "${lawn_pump_max_on_time}"
    assert g["pump_idle_timeout"] == "${lawn_pump_idle_timeout}"
    assert g["pump_start_pump_delay"] == "${lawn_pump_start_pump_delay}"
    assert g["pump_stop_valve_delay"] == "${lawn_pump_stop_valve_delay}"
    assert g["auto_advance_switch"]["id"] == "lawn_zones_auto_advance"
    assert g["auto_advance_switch"]["name"] == "${lawn_name} auto advance"
    trip = g["on_watchdog_trip"][0]["logger.log"]
    assert trip["level"] == "ERROR" and trip["tag"] == "lawn_zones"
    assert "main_switch" not in g and "zones" not in g
    assert "garden_zone" not in data
    assert data["external_components"] == [{"source": "${gp_root}/components", "components": ["garden_zones", "garden_zone"]}]
    assert not re.search(r"GPIO\d+|!secret|lvgl|sprinkler|!extend|defaults:", _code(IRRIGATION))


def test_lawn_defaults() -> None:
    s = _load(IRRIGATION)["substitutions"]
    assert s == {
        "lawn_name": "Lawn",
        "lawn_max_parallel": "1",
        "lawn_max_on_time": "60min",
        "lawn_zone_run_max": "55",
        "lawn_zone_run_initial": "15",
        "lawn_pump_max_on_time": "2h",
        "lawn_pump_idle_timeout": "10s",
        "lawn_pump_start_pump_delay": "0s",
        "lawn_pump_stop_valve_delay": "0s",
        "gp_root": ".",
    }
    assert "never" not in s.values()
    delays = _seconds(s["lawn_pump_start_pump_delay"]) + _seconds(s["lawn_pump_stop_valve_delay"])
    assert int(s["lawn_zone_run_max"]) * 60 + delays + 2 <= _seconds(s["lawn_max_on_time"])
    assert _seconds(s["lawn_pump_max_on_time"]) >= _seconds(s["lawn_max_on_time"])
    assert int(s["lawn_zone_run_initial"]) <= int(s["lawn_zone_run_max"])
    assert _seconds(s["lawn_pump_idle_timeout"]) >= delays + 2
    assert s["lawn_max_parallel"] == "1"
    assert "pump_relay" not in s, "the pump relay has no default: the entry file sets it"


def test_lawn_zone_shape() -> None:
    data = _load(ZONE)
    assert set(data) == {"garden_zone", "gp_zone"}
    assert len(data["garden_zone"]) == 1 and len(data["gp_zone"]) == 1
    z, gz = data["garden_zone"][0], data["gp_zone"][0]
    assert z["group"] == "lawn_zones" and gz["group"] == "gp_lawn"
    valve = z["valve_switch"]
    assert valve == {"id": "lawn_zone${zone}_engine_valve", "name": "${zone_name}", "internal": True}
    assert gz["name"] == valve["name"] and gz["id"] == "lawn_zone${zone}_switch"
    assert str(gz["position"]) == "${zone}"
    assert z["enable_switch"] == {"id": "lawn_zone${zone}_enable", "name": "${zone_name} enable"}
    n = z["run_duration_number"]
    assert n["id"] == "lawn_zone${zone}_run_duration" and n["name"] == "${zone_name} run duration"
    assert str(n["max_value"]) == "${lawn_zone_run_max}" and str(n["initial_value"]) == "${lawn_zone_run_initial}"
    assert n["min_value"] == 1 and n["restore_value"] is True and n["unit_of_measurement"] == "min" and n["mode"] == "BOX"
    assert z["valve_switch_id"] == "board_relay_${relay}"
    assert not re.search(r"lvgl\.|sprinkler|!extend|GPIO\d+|!secret", _code(ZONE))


def test_lawn_gp_shape() -> None:
    data = _load(GP)
    groups = data["gp"]["groups"]
    assert len(groups) == 1
    g = groups[0]
    assert {k: g[k] for k in ("id", "name", "key", "garden_zones_id")} == {
        "id": "gp_lawn", "name": "${lawn_name}", "key": "lawn", "garden_zones_id": "lawn_zones"
    }
    assert {"on_zone_finished", "on_stop"} <= set(g)
    wd = data["binary_sensor"][0]
    assert wd["id"] == "lawn_zones_watchdog_problem" and wd["device_class"] == "problem"
    assert wd["condition"] == {"gp.watchdog_tripped": "gp_lawn"} and wd["name"] == "${lawn_name} watchdog"
    reset = data["button"][0]
    assert reset["id"] == "lawn_zones_watchdog_reset" and reset["entity_category"] == "config"
    assert reset["name"] == "${lawn_name} watchdog reset"
    assert reset["on_press"] == [{"gp.reset_watchdog": "gp_lawn"}]
    sw = data["switch"][0]
    assert sw["platform"] == "template" and sw["id"] == "gp_lawn_main_switch" and sw["name"] == "${lawn_name} irrigation"
    assert sw["restore_mode"] == "DISABLED" and sw["optimistic"] is False
    assert sw["turn_on_action"] == [{"gp.full_cycle": "gp_lawn"}]
    assert sw["turn_off_action"] == [{"gp.stop_all": "gp_lawn"}]
    assert sw["lambda"] == "return id(gp_lawn)->summary().running;"
    ts = data["text_sensor"][0]
    assert ts["id"] == "gp_lawn_status" and ts["name"] == "${lawn_name} status"
    assert {s["id"] for s in data["script"]} == {"gp_lawn_zone_finished", "gp_lawn_stopped", "gp_lawn_zone_done"}
    code = _code(GP)
    assert "gp_greenhouse" not in code and "gh_zones" not in code
    assert not re.search(r"garden_zones\.|sprinkler|lvgl\.", code)
    for d in _walk(data):
        for k, v in d.items():
            if isinstance(k, str) and k.startswith("gp.") and k != "gp.watchdog_tripped":
                assert v == "gp_lawn", (k, v)
        lam = d.get("lambda")
        if isinstance(lam, str):
            assert len([ln for ln in lam.splitlines() if ln.strip()]) <= 1
        if d.get("__tag__") == "lambda":
            assert len([ln for ln in d["value"].splitlines() if ln.strip()]) <= 1
        if isinstance(d.get("id"), str):
            assert not re.fullmatch(r"lawn_zones_watchdog|lawn_zones_lane_\d+", d["id"])


def _lawn_entries() -> list[tuple[Path, dict[str, dict], dict]]:
    """Device entries that enable the lawn (commented examples count as active): (path, packages, substitutions)."""
    result = []
    for entry in DEVICE_ENTRIES:
        packages = _entry_packages(entry)
        if not any(p["path"] == IRRIGATION_FILE for p in packages.values()):
            continue
        text = _uncomment_examples(entry.read_text(encoding="utf-8"))[0]
        subst = yaml.load(text, Loader=_EsphomeLoader)["substitutions"]  # noqa: S506 - SafeLoader subclass
        result.append((entry, packages, subst))
    return result


def _effective(subst: dict, name: str) -> str:
    return str(subst.get(name, _load(IRRIGATION)["substitutions"][name]))


def test_lawn_entries_exist() -> None:
    names = {e.name for e, _, _ in _lawn_entries()}
    assert {"garden-pilot.yaml", "my-garden.yaml"} <= names


def test_lawn_session_fits_pump_limit() -> None:
    for entry, packages, subst in _lawn_entries():
        zones = [p for p in packages.values() if p["path"] == ZONE_FILE]
        assert zones, entry.name
        delays = _seconds(_effective(subst, "lawn_pump_start_pump_delay")) + _seconds(_effective(subst, "lawn_pump_stop_valve_delay"))
        session = len(zones) * (int(_effective(subst, "lawn_zone_run_max")) * 60 + delays)
        limit = _effective(subst, "lawn_pump_max_on_time")
        assert limit != "never"
        assert session <= _seconds(limit), f"{entry.name}: {len(zones)} zones need {session} s, pump limit {limit}"


def test_lawn_includes() -> None:
    for entry, packages, _ in _lawn_entries():
        keys = list(packages)
        irr = [k for k, p in packages.items() if p["path"] == IRRIGATION_FILE]
        assert irr == ["lawn_irrigation"], entry.name
        assert "pump_relay" in packages["lawn_irrigation"]["vars"], entry.name
        zones = [k for k, p in packages.items() if p["path"] == ZONE_FILE]
        assert zones and zones == [f"lawn_zone_{n}" for n in range(1, len(zones) + 1)], f"{entry.name}: {zones}"
        names = []
        for n, key in enumerate(zones, 1):
            v = packages[key]["vars"]
            assert set(v) == {"zone", "zone_name", "relay"}, f"{entry.name}: {key}"
            assert str(v["zone"]) == str(n), f"{entry.name}: {key}"
            names.append(v["zone_name"])
            assert keys.index("lawn_irrigation") < keys.index(key)
        assert len(set(names)) == len(names)
        gps = [k for k, p in packages.items() if p["path"] == GP_FILE]
        assert gps == ["lawn_gp"], entry.name
        assert keys.index("lawn_gp") > keys.index(zones[-1])
        assert keys.index("lawn_gp") > keys.index("core_gp")
        if "core_api" in keys:
            assert "core_gp_api" in keys and keys.index("lawn_gp") > keys.index("core_gp_api")


def test_greenhouse_public_defaults_unchanged() -> None:
    s = _load(REPO_ROOT / "packages" / "greenhouse" / "irrigation.yaml")["substitutions"]
    assert (s["gh_max_parallel"], s["gh_max_on_time"], s["gh_bed_run_max"], s["gh_bed_run_initial"]) == ("1", "60min", "55", "5")


def test_no_entry_overrides_lawn_max_parallel() -> None:
    for entry, _, subst in _lawn_entries():
        assert "lawn_max_parallel" not in subst, f"{entry.name}: lawn_max_parallel other than 1 is not supported yet"
