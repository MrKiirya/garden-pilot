"""Layout rules: pins and board settings only in hardware/, secrets only in the entry file, core without LVGL."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import REPO_ROOT, _EsphomeLoader, load_esphome_yaml

pytestmark = pytest.mark.unit

ENTRY = REPO_ROOT / "garden-pilot.yaml"
SIM_ENTRY = REPO_ROOT / "garden-pilot-sim.yaml"
ENTRIES = [ENTRY, SIM_ENTRY]


def tracked_files() -> list[Path]:
    """Tracked plus new (not ignored) files, so the checks also cover a task before its first commit.

    Including untracked files is on purpose: locally this is stricter than CI, which only sees tracked files.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [REPO_ROOT / n for n in sorted(set(out.split("\0"))) if n and (REPO_ROOT / n).is_file()]


def _yaml_files(*folders: str) -> list[Path]:
    roots = [REPO_ROOT / f for f in folders]
    return [p for p in tracked_files() if p.suffix == ".yaml" and any(r in p.parents for r in roots)]


def _strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def _hardware_profiles() -> list[Path]:
    profiles = sorted((REPO_ROOT / "hardware").glob("*.yaml"))
    assert profiles, "no hardware/*.yaml profile found"
    return profiles


def _has_secret_tag(node: object) -> bool:
    if isinstance(node, dict):
        return node.get("__tag__") == "secret" or any(_has_secret_tag(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_secret_tag(v) for v in node)
    return False


def _subst_keys(path: Path) -> set[str]:
    data = load_esphome_yaml(path)
    assert isinstance(data, dict)
    return set(data.get("substitutions") or {})


BED = REPO_ROOT / "packages" / "greenhouse" / "bed.yaml"
BED_SOIL = REPO_ROOT / "packages" / "greenhouse" / "bed_soil.yaml"
BED_FILE = "packages/greenhouse/bed.yaml"
BED_SOIL_FILE = "packages/greenhouse/bed_soil.yaml"
_EXAMPLE_START = re.compile(r"^  # ([A-Za-z0-9_]+): !include\s*$")
_EXAMPLE_CONT = re.compile(r"^  #   ")


def _uncomment_examples(text: str) -> tuple[str, set[str]]:
    """Uncomment the commented-out example include blocks of the entry file (`  # key: !include` + `  #   ` lines)."""
    out: list[str] = []
    examples: set[str] = set()
    in_example = False
    for line in text.splitlines():
        m = _EXAMPLE_START.match(line)
        if m:
            in_example = True
            examples.add(m.group(1))
            out.append(line[:2] + line[4:])
        elif in_example and _EXAMPLE_CONT.match(line):
            out.append(line[:2] + line[4:])
        else:
            in_example = False
            out.append(line)
    return "\n".join(out) + "\n", examples


def _entry_text_with_examples() -> str:
    return _uncomment_examples(ENTRY.read_text(encoding="utf-8"))[0]


def _entry_includes(path_suffix: str, entry: Path = ENTRY) -> list[dict]:
    """Entry-file packages including `path_suffix` with file:/vars:, in file order.

    Each item: key, vars, active (False for commented-out examples).
    """
    text, examples = _uncomment_examples(entry.read_text(encoding="utf-8"))
    data = yaml.load(text, Loader=_EsphomeLoader)  # noqa: S506 - SafeLoader subclass
    items = []
    for key, pkg in data["packages"].items():
        if not (isinstance(pkg, dict) and pkg.get("__tag__") == "include"):
            continue
        value = pkg["value"]
        file = value.get("file") if isinstance(value, dict) else value
        if file != path_suffix:
            continue
        assert isinstance(value, dict), f"{key}: include {path_suffix} with file:/vars:"
        items.append({"key": key, "vars": value.get("vars") or {}, "active": key not in examples})
    return items


def _template_vars(path: Path) -> set[str]:
    return set(re.findall(r"\$\{(\w+)\}", _strip_comments(path.read_text(encoding="utf-8"))))


def _pin_refs() -> set[str]:
    refs: set[str] = set()
    for path in _yaml_files("packages"):
        if path in (BED, BED_SOIL):
            continue  # their ${adc_pin} is a var, not a board pin
        refs |= set(re.findall(r"\$\{(\w+_pin)\}", _strip_comments(path.read_text(encoding="utf-8"))))
    refs |= set(re.findall(r"\$\{(\w+_pin)\}", _strip_comments(_entry_text_with_examples())))
    return refs


def _esp32_profiles() -> list[Path]:
    return [p for p in _hardware_profiles() if "esp32" in load_esphome_yaml(p)]


def test_pins_only_in_hardware() -> None:
    hardware = REPO_ROOT / "hardware"
    offenders = []
    for path in tracked_files():
        if path.suffix != ".yaml" or hardware in path.parents:
            continue
        if re.search(r"GPIO\d+", _strip_comments(path.read_text(encoding="utf-8"))):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"GPIO literals outside hardware/: {offenders}"


def test_hardware_profiles_shape() -> None:
    profiles = _hardware_profiles()
    for path in profiles:
        data = load_esphome_yaml(path)
        assert isinstance(data, dict)
        assert set(data) <= {"substitutions", "esp32", "psram", "host", "switch"}, path.name
        assert ("esp32" in data) != ("host" in data), f"{path.name}: exactly one of esp32 / host"
        if "esp32" in data:
            assert "board" in data["esp32"], path.name
            assert data.get("substitutions"), path.name


def test_hardware_profiles_define_every_pin_used() -> None:
    used = _pin_refs()
    assert used
    for path in _esp32_profiles():
        pins = {k for k in _subst_keys(path) if k.endswith("_pin")}
        assert used <= pins, f"{path.name} lacks pins: {sorted(used - pins)}"
        own = set(re.findall(r"\$\{(\w+_pin)\}", _strip_comments(path.read_text(encoding="utf-8"))))
        assert pins <= used | own, f"{path.name} defines unused pins: {sorted(pins - used - own)}"


def test_hardware_board_settings_are_used() -> None:
    """Non-pin board substitutions (display/touch orientation, calibration) must be referenced by a package."""
    text = "\n".join(_strip_comments(p.read_text(encoding="utf-8")) for p in _yaml_files("packages"))
    for path in _hardware_profiles():
        for key in _subst_keys(path):
            if key.endswith("_pin"):
                continue
            assert f"${{{key}}}" in text, f"{path.name}: {key} is not used under packages/"


def test_analog_pins_named_by_function() -> None:
    for path in _esp32_profiles():
        keys = _subst_keys(path)
        # Literal split on purpose: the acceptance grep for the old analog pin name must find nothing outside tasks/
        assert "soil_ao" "_pin" not in keys, f"{path.name}: analog soil input must be adc_<n>_pin"
        adc = {k for k in keys if k.endswith("_pin") and ("adc" in k or "ao" in k.split("_"))}
        assert adc, f"{path.name} defines no analog input pin"
        for key in adc:
            assert re.fullmatch(r"adc_\d+_pin", key), f"{path.name}: analog pin {key} must be adc_<n>_pin"
    for path in tracked_files():
        if path.suffix == ".yaml":
            text = path.read_text(encoding="utf-8")
            assert "soil_ao" "_pin" not in _strip_comments(text), f"{path}: use adc_<n>_pin"


def test_sim_profile_has_no_hardware() -> None:
    path = REPO_ROOT / "hardware" / "sim.yaml"
    assert path.is_file()
    data = load_esphome_yaml(path)
    assert isinstance(data, dict)
    assert "host" in data and "esp32" not in data
    assert not [k for k in _subst_keys(path) if k.endswith("_pin")]
    assert not re.search(r"GPIO\d+", _strip_comments(path.read_text(encoding="utf-8")))
    switches = data.get("switch") or []
    assert switches
    for sw in switches:
        assert sw.get("platform") == "template", sw
        assert sw.get("internal") is True, sw
        assert sw.get("restore_mode") == "ALWAYS_OFF", sw


def _relay_ids(path: Path) -> set[str]:
    data = load_esphome_yaml(path)
    assert isinstance(data, dict)
    return {sw["id"] for sw in data.get("switch") or []}


def test_board_relays_are_safe() -> None:
    reference: set[str] | None = None
    for path in _hardware_profiles():
        data = load_esphome_yaml(path)
        assert isinstance(data, dict)
        for sw in data.get("switch") or []:
            assert re.fullmatch(r"board_relay_\d+", str(sw.get("id"))), f"{path.name}: bad relay id {sw.get('id')}"
            assert sw.get("internal") is True, f"{path.name}: {sw['id']} must be internal"
            assert sw.get("restore_mode") in {"RESTORE_DEFAULT_OFF", "ALWAYS_OFF"}, f"{path.name}: {sw['id']}"
        ids = _relay_ids(path)
        assert ids, f"{path.name} defines no board_relay_N"
        if reference is None:
            reference = ids
        assert ids == reference, f"{path.name}: relay ids {sorted(ids)} differ from {sorted(reference)}"


def test_no_gpio_switch_in_packages() -> None:
    for path in _yaml_files("packages"):
        data = load_esphome_yaml(path)
        if not isinstance(data, dict):
            continue
        for sw in data.get("switch") or []:
            assert not (isinstance(sw, dict) and sw.get("platform") == "gpio"), f"{path.name}: gpio switch"


def test_bed_includes() -> None:
    beds = _entry_includes(BED_FILE)
    assert len(beds) >= 2, "at least 2 beds with the stock sprinkler"
    assert all(b["active"] for b in beds), "bed.yaml includes must be active"
    expected = _template_vars(BED)
    assert expected == {"bed", "bed_name", "relay"}, expected
    for b in beds:
        assert set(b["vars"]) == expected, f"{b['key']}: vars {sorted(b['vars'])}"
    numbers = [str(b["vars"]["bed"]) for b in beds]
    assert len(set(numbers)) == len(numbers), "bed values must be unique"
    assert numbers == ["1", "2", "3"], "the greenhouse page uses valve_number 0/1/2 = beds 1, 2, 3 in order"
    keys = list(load_esphome_yaml_text(ENTRY.read_text(encoding="utf-8"))["packages"])
    first, last = keys.index("gh_irrigation"), keys.index("gh_lvgl_page")
    for b in beds:
        assert first < keys.index(b["key"]) < last, f"{b['key']} must sit between gh_irrigation and gh_lvgl_page"
    for path in _hardware_profiles():
        relays = _relay_ids(path)
        for b in beds:
            assert f"board_relay_{b['vars']['relay']}" in relays, f"{path.name}: no relay for {b['key']}"


def load_esphome_yaml_text(text: str) -> dict:
    return yaml.load(text, Loader=_EsphomeLoader)  # noqa: S506 - SafeLoader subclass


def test_bed_soil_includes() -> None:
    soils = _entry_includes(BED_SOIL_FILE)
    assert any(not s["active"] for s in soils), "keep a commented-out gh_bed_N_soil example in the entry file"
    expected = _template_vars(BED_SOIL)
    assert expected == {"bed", "bed_name", "adc_pin", "cal_dry_v", "cal_wet_v"}, expected
    beds = {str(b["vars"]["bed"]): b for b in _entry_includes(BED_FILE)}
    keys = list(load_esphome_yaml_text(_entry_text_with_examples())["packages"])
    adc_keys = [{k for k in _subst_keys(p) if re.fullmatch(r"adc_\d+_pin", k)} for p in _esp32_profiles()]
    active_pins: list[str] = []
    for s in soils:
        assert set(s["vars"]) == expected, f"{s['key']}: vars {sorted(s['vars'])}"
        m = re.fullmatch(r"\$\{(adc_\d+_pin)\}", str(s["vars"]["adc_pin"]))
        assert m, f"{s['key']}: adc_pin must be ${{adc_<n>_pin}}, got {s['vars']['adc_pin']}"
        assert all(m.group(1) in k for k in adc_keys), f"{s['key']}: {m.group(1)} missing in a profile"
        bed = beds.get(str(s["vars"]["bed"]))
        assert bed, f"{s['key']}: no bed {s['vars']['bed']}"
        assert bed["vars"]["bed_name"] == s["vars"]["bed_name"], f"{s['key']}: bed_name differs from its bed"
        assert keys.index(s["key"]) > keys.index(bed["key"]), f"{s['key']} must come after {bed['key']}"
        if s["active"]:
            active_pins.append(m.group(1))
    assert len(set(active_pins)) == len(active_pins), "two bed soil sensors on one ADC pin"


def test_bed_soil_shape() -> None:
    data = load_esphome_yaml(BED_SOIL)
    assert isinstance(data, dict)
    assert set(data) == {"sensor"}
    assert len(data["sensor"]) == 1
    sensor = data["sensor"][0]
    assert sensor["platform"] == "adc"
    assert sensor["pin"] == "${adc_pin}"
    assert "${bed}" in sensor["id"]
    assert sensor["name"] == "${bed_name} soil moisture"
    assert sensor["device_class"] == "moisture"
    assert sensor["unit_of_measurement"] == "%"
    assert "on_value" not in sensor
    filters = {next(iter(f)): f[next(iter(f))] for f in sensor["filters"]}
    assert set(filters["calibrate_linear"]) == {"${cal_dry_v} -> 0.0", "${cal_wet_v} -> 100.0"}
    assert filters["clamp"]["min_value"] == 0.0 and filters["clamp"]["max_value"] == 100.0
    text = _strip_comments(BED_SOIL.read_text(encoding="utf-8"))
    assert "lvgl" not in text.lower()
    assert not re.search(r"GPIO\d+|!secret|substitutions:|defaults:", text)


def test_bed_shape() -> None:
    data = load_esphome_yaml(BED)
    assert isinstance(data, dict)
    assert set(data) == {"sprinkler"}
    text = _strip_comments(BED.read_text(encoding="utf-8"))
    assert not re.search(r"GPIO\d+|!secret|substitutions:|defaults:|lvgl", text)
    assert "!extend" in text and "gh_sprinkler" in text


def test_bed_vars_do_not_shadow_globals() -> None:
    names = _template_vars(BED) | _template_vars(BED_SOIL)
    defined = set(load_esphome_yaml_text(ENTRY.read_text(encoding="utf-8")).get("substitutions") or {})
    for path in _hardware_profiles():
        defined |= _subst_keys(path)
    for path in _yaml_files("packages"):
        data = load_esphome_yaml(path)
        if isinstance(data, dict):
            defined |= set(data.get("substitutions") or {})
    assert not names & defined, f"bed vars shadow global substitutions: {sorted(names & defined)}"


@pytest.mark.parametrize("entry_path", ENTRIES, ids=lambda p: p.name)
def test_no_secret_outside_entry_file(entry_path: Path) -> None:
    for path in _yaml_files("packages", "hardware"):
        assert "!secret" not in _strip_comments(path.read_text(encoding="utf-8")), path
    entry = load_esphome_yaml(entry_path)
    assert isinstance(entry, dict)
    for section, value in entry.items():
        if section != "substitutions":
            assert not _has_secret_tag(value), f"!secret outside substitutions in {section}"
    tags = [v.get("__tag__") for v in entry["substitutions"].values() if isinstance(v, dict)]
    assert "secret" in tags, "the entry file should assign secrets to substitutions"


def test_substitutions_resolve() -> None:
    defined: set[str] = set()
    entry = load_esphome_yaml(ENTRY)
    assert isinstance(entry, dict)
    defined |= set(entry.get("substitutions") or {})
    for path in _hardware_profiles():
        defined |= _subst_keys(path)
    package_files = _yaml_files("packages")
    for path in package_files:
        data = load_esphome_yaml(path)
        if isinstance(data, dict):
            defined |= set(data.get("substitutions") or {})
    supplied = {
        BED: set().union(*(set(i["vars"]) for i in _entry_includes(BED_FILE))),
        BED_SOIL: set().union(*(set(i["vars"]) for i in _entry_includes(BED_SOIL_FILE))),
    }
    missing = set()
    for path in package_files:
        for name in re.findall(r"\$\{(\w+)\}", _strip_comments(path.read_text(encoding="utf-8"))):
            if name not in defined | supplied.get(path, set()):
                missing.add((path.name, name))
    assert not missing, f"undefined substitutions: {sorted(missing)}"


def _sim_data() -> dict:
    data = load_esphome_yaml(SIM_ENTRY)
    assert isinstance(data, dict)
    return data


def _package_files(data: dict) -> dict[str, str]:
    """Entry-file package key -> included file path (`!include path` or `!include {file: path}`)."""
    result = {}
    for key, pkg in data["packages"].items():
        assert isinstance(pkg, dict) and pkg.get("__tag__") == "include", key
        value = pkg["value"]
        result[key] = value["file"] if isinstance(value, dict) else value
    return result


def test_sim_substitutions_resolve() -> None:
    """Every ${name} used by a package the sim includes is defined by the sim entry file, hardware/sim.yaml,
    a package `substitutions:` block or a bed's vars (catches a sim package that needs wifi_ssid etc.)."""
    data = _sim_data()
    files = _package_files(data)
    sim_hw = REPO_ROOT / files["hardware"]
    defined = set(data.get("substitutions") or {}) | _subst_keys(sim_hw)
    supplied: dict[str, set[str]] = {}
    for key, pkg in data["packages"].items():
        value = pkg["value"]
        if isinstance(value, dict):
            supplied.setdefault(value["file"], set()).update(value.get("vars") or {})
    for rel in files.values():
        loaded = load_esphome_yaml(REPO_ROOT / rel)
        if isinstance(loaded, dict):
            defined |= set(loaded.get("substitutions") or {})
    missing = set()
    for rel in files.values():
        text = _strip_comments((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for name in re.findall(r"\$\{(\w+)\}", text):
            if name not in defined | supplied.get(rel, set()):
                missing.add((rel, name))
    assert not missing, f"undefined substitutions in the sim build: {sorted(missing)}"


def test_core_is_display_independent() -> None:
    lvgl_ids: set[str] = set()
    for path in _yaml_files("packages/lvgl"):
        lvgl_ids |= set(re.findall(r"\bid:\s*(\w+)", path.read_text(encoding="utf-8")))
    core = _yaml_files("packages/core")
    assert core, "packages/core is empty"
    for path in core:
        text = _strip_comments(path.read_text(encoding="utf-8"))
        assert "lvgl" not in text.lower(), path
        used = {i for i in lvgl_ids if re.search(rf"\b{re.escape(i)}\b", text)}
        assert not used, f"{path} references LVGL ids {sorted(used)}"


def test_gpio_actuators_are_safe() -> None:
    checked = 0
    for path in _yaml_files("packages", "hardware"):
        data = load_esphome_yaml(path)
        if not isinstance(data, dict):
            continue
        for sw in data.get("switch") or []:
            if isinstance(sw, dict) and sw.get("platform") == "gpio":
                checked += 1
                assert sw.get("internal") is True, f"{path.name}: gpio switch must be internal"
                assert sw.get("restore_mode") in {"RESTORE_DEFAULT_OFF", "ALWAYS_OFF"}, path.name
    assert checked, "no gpio switches found"


def _single_top_level(rel: str, key: str) -> dict | list:
    data = load_esphome_yaml(REPO_ROOT / rel)
    assert isinstance(data, dict)
    assert set(data) == {key}, f"{rel}: expected only `{key}`, got {sorted(data)}"
    return data[key]


def test_core_split() -> None:
    api = _single_top_level("packages/core/api.yaml", "api")
    assert isinstance(api, dict) and api["encryption"]["key"] == "${api_encryption_key}"
    ota = _single_top_level("packages/core/ota.yaml", "ota")
    assert len(ota) == 1 and ota[0]["platform"] == "esphome" and ota[0]["password"] == "${ota_password}"
    data = load_esphome_yaml(REPO_ROOT / "packages/core/network.yaml")
    assert isinstance(data, dict) and set(data) == {"wifi", "captive_portal"}
    for rel, platform in (("packages/core/time.yaml", "homeassistant"), ("packages/core/time_host.yaml", "host")):
        times = _single_top_level(rel, "time")
        assert len(times) == 1, rel
        assert times[0]["platform"] == platform and times[0]["id"] == "ha_time", rel


def _ids(items: list, platform: str | None = None) -> set[str]:
    return {i["id"] for i in items if platform is None or i.get("platform") == platform}


def test_display_packages_share_ids() -> None:
    touch = load_esphome_yaml(REPO_ROOT / "packages" / "display_touch.yaml")
    sdl = load_esphome_yaml(REPO_ROOT / "packages" / "display_sdl.yaml")
    assert isinstance(touch, dict) and isinstance(sdl, dict)
    for data in (touch, sdl):
        assert _ids(data["display"]) == {"tft_display"}
        assert _ids(data["touchscreen"]) == {"touch"}
        assert _ids(data["script"]) == {"touch_ui", "touch_dot_overlay"}
    assert [d["platform"] for d in sdl["display"]] == ["sdl"]
    assert [t["platform"] for t in sdl["touchscreen"]] == ["sdl"]
    text = _strip_comments((REPO_ROOT / "packages" / "display_sdl.yaml").read_text(encoding="utf-8"))
    assert not re.search(r"\$\{\w+_pin\}|GPIO|headless|snapshot_key", text)


def test_sim_entry_file() -> None:
    data = _sim_data()
    assert set(data) <= {"substitutions", "esphome", "logger", "api", "packages"}
    assert set(data.get("api") or {}) <= {"reboot_timeout"}
    files = _package_files(data)
    assert files["hardware"] == "hardware/sim.yaml"
    keys = list(files)
    required = ["core_api", "core_time_host", "display_sdl", "lvgl_base", "lvgl_page_home", "gh_irrigation",
                "gh_bed_1", "gh_bed_2", "gh_bed_3", "gh_lvgl_page", "gh_sprinkler_lvgl"]
    assert set(required) <= set(keys), sorted(set(required) - set(keys))
    first_page = [k for k in keys if k.startswith("lvgl_page_")][0]
    assert first_page == "lvgl_page_home"
    forbidden = {"core_network", "core_ota", "core_time", "display_touch", "gh_sensors_air", "gh_sensors_soil"}
    assert not forbidden & set(keys), sorted(forbidden & set(keys))
    assert BED_SOIL_FILE not in files.values()
    assert "web_server" not in data
    device = load_esphome_yaml(ENTRY)
    assert isinstance(device, dict)
    assert data["esphome"]["name"] != device["esphome"]["name"]
    assert data["logger"]["level"] in {"INFO", "WARN", "WARNING", "ERROR", "NONE"}
    secret_names = [v["value"] for v in data["substitutions"].values() if isinstance(v, dict) and v.get("__tag__") == "secret"]
    assert secret_names == ["sim_api_encryption_key"], "the emulator uses only its own public dummy key"
    assert data["substitutions"]["api_encryption_key"] == {"__tag__": "secret", "value": "sim_api_encryption_key"}
    text = _strip_comments(SIM_ENTRY.read_text(encoding="utf-8"))
    assert text.count("!secret") == 1


def test_sim_beds_match_device() -> None:
    sim_beds = _entry_includes(BED_FILE, SIM_ENTRY)
    device_beds = _entry_includes(BED_FILE, ENTRY)
    assert sim_beds == device_beds
    device_files = _package_files(load_esphome_yaml(ENTRY))  # type: ignore[arg-type]
    sim_files = _package_files(_sim_data())
    for key in set(device_files) & set(sim_files):
        if key != "hardware":
            assert device_files[key] == sim_files[key], key
