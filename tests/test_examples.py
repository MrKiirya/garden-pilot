"""Example configs in examples/ (task 023): complete entry files that use the shared packages through `../` paths."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import REPO_ROOT, load_esphome_yaml

EXAMPLES_DIR = REPO_ROOT / "examples"
EXAMPLE_NAMES = ["minimal-1-bed", "beds-with-pump", "soil-sensors", "relay-module-8ch"]
EXAMPLES = [EXAMPLES_DIR / f"{n}.yaml" for n in EXAMPLE_NAMES]
ROOT_ENTRIES = [REPO_ROOT / "garden-pilot.yaml", REPO_ROOT / "garden-pilot-sim.yaml"]
LOG_LEVELS = {"INFO", "WARN", "WARNING", "ERROR", "NONE"}


def _strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def _load(path: Path) -> dict:
    data = load_esphome_yaml(path)
    assert isinstance(data, dict), path
    return data


def _includes(data: dict) -> dict[str, tuple[str, dict]]:
    """Package key -> (include path as written, vars)."""
    result = {}
    for key, pkg in data["packages"].items():
        assert isinstance(pkg, dict) and pkg.get("__tag__") == "include", key
        value = pkg["value"]
        result[key] = (value["file"], value.get("vars") or {}) if isinstance(value, dict) else (value, {})
    return result


@pytest.mark.unit
def test_examples_exist() -> None:
    assert (EXAMPLES_DIR / "README.md").is_file()
    found = sorted(p.name for p in EXAMPLES_DIR.glob("*.yaml") if p.name != "secrets.yaml")
    assert found == sorted(f"{n}.yaml" for n in EXAMPLE_NAMES)
    names = set()
    for path in EXAMPLES:
        data = _load(path)
        assert set(data) == {"substitutions", "esphome", "logger", "packages"}, path.name
        name = data["esphome"]["name"]
        assert re.fullmatch(r"gp-[a-z0-9-]+", name), name
        names.add(name)
        assert data["logger"]["level"] in LOG_LEVELS, path.name
        keys = list(data["packages"])
        assert {"display_touch", "lvgl_base", "gh_lvgl_page"} <= set(keys), path.name
        assert "touch_dot_test" not in keys, f"{path.name}: the debug overlay stays out of the examples"
    assert len(names) == len(EXAMPLES), "esphome names must be unique"
    assert not names & {_load(p)["esphome"]["name"] for p in ROOT_ENTRIES}


@pytest.mark.unit
def test_example_secrets_pattern() -> None:
    known = set(yaml.safe_load((REPO_ROOT / "secrets.example.yaml").read_text(encoding="utf-8")))
    for path in EXAMPLES:
        data = _load(path)
        tagged = {k: v["value"] for k, v in data["substitutions"].items() if isinstance(v, dict) and v.get("__tag__") == "secret"}
        assert tagged, f"{path.name}: assign the secrets to substitutions"
        assert set(tagged.values()) <= known, f"{path.name}: unknown secrets {sorted(set(tagged.values()) - known)}"
        text = _strip_comments(path.read_text(encoding="utf-8"))
        assert text.count("!secret") == len(tagged), f"{path.name}: !secret outside `substitutions:`"
        for section, value in data.items():
            if section != "substitutions":
                assert "secret" not in yaml.dump(value).replace("secrets", ""), f"{path.name}: !secret in {section}"


@pytest.mark.unit
def test_example_paths() -> None:
    for path in EXAMPLES:
        data = _load(path)
        assert data["substitutions"]["gp_root"] == "..", path.name
        includes = _includes(data)
        hardware = [k for k, (f, _) in includes.items() if f.startswith("../hardware/")]
        assert hardware == ["hardware"], f"{path.name}: exactly one hardware package, got {hardware}"
        for key, (file, _) in includes.items():
            assert file.startswith(("../packages/", "../hardware/")), f"{path.name}: {key}: {file}"
            assert (path.parent / file).resolve().is_file(), f"{path.name}: {key}: {file} does not exist"


@pytest.mark.unit
def test_gp_root_default() -> None:
    """A package that points at a repo folder (components/, the font) does it through ${gp_root}, default ".".

    Examples set gp_root: ".." because `external_components` and `font` paths resolve against the directory of the
    entry file, not of the including package.
    """
    seen = 0
    for path in sorted((REPO_ROOT / "packages").rglob("*.yaml")):
        text = _strip_comments(path.read_text(encoding="utf-8"))
        assert not re.search(r"source:\s*components\b", text), f"{path}: literal `source: components`"
        data = load_esphome_yaml(path)
        if not isinstance(data, dict):
            continue
        local = []
        for item in data.get("external_components") or []:
            source = item["source"]
            if not (isinstance(source, str) and re.match(r"(github|https?)://", source)):
                local.append(source)
        for font in data.get("font") or []:
            if isinstance(font.get("file"), str):
                local.append(font["file"])
        if not local:
            continue
        seen += 1
        assert all(s.startswith("${gp_root}/") for s in local), f"{path}: {local}"
        assert data["substitutions"]["gp_root"] == ".", f"{path}: define gp_root: \".\""
    assert seen == 5, "irrigation, irrigation_pump, schedule, gp (components) and screensaver (font)"
    assert "gp_root" not in (_load(REPO_ROOT / "garden-pilot.yaml")["substitutions"]), "root entry uses the default"


def _rank(key: str) -> int:
    fixed = ["hardware", "core_api", "core_ota", "core_network", "core_time", "core_diagnostics", "display_touch", "lvgl_base", "lvgl_page_boot"]
    if key in fixed:
        return fixed.index(key)
    if key.startswith("lvgl_"):
        return 20
    if key == "gh_irrigation":
        return 30
    if re.fullmatch(r"gh_bed_\d+(_soil)?", key):
        return 31
    if key == "core_gp":
        return 40
    if key == "core_gp_api":
        return 41
    if key == "gh_gp":
        return 42
    if key == "gh_schedule":
        return 60
    if key.startswith("gh_schedule_slot_"):
        return 61
    if key.startswith("gh_"):
        return 50
    raise AssertionError(f"unexpected package key {key}")


@pytest.mark.unit
def test_example_package_order() -> None:
    for path in EXAMPLES:
        keys = list(_load(path)["packages"])
        ranks = [_rank(k) for k in keys]
        assert ranks == sorted(ranks), f"{path.name}: packages out of order: {keys}"
        assert keys[:6] == ["hardware", "core_api", "core_ota", "core_network", "core_time", "core_diagnostics"], path.name
        assert keys.index("lvgl_page_home") > keys.index("lvgl_page_boot"), path.name
        beds = [k for k in keys if re.fullmatch(r"gh_bed_\d+", k)]
        assert beds == [f"gh_bed_{n}" for n in range(1, len(beds) + 1)] and beds, f"{path.name}: beds {beds}"
        for n in range(1, len(beds) + 1):
            if f"gh_bed_{n}_soil" in keys:
                assert keys.index(f"gh_bed_{n}_soil") == keys.index(f"gh_bed_{n}") + 1, path.name
        slots = [k for k in keys if k.startswith("gh_schedule_slot_")]
        assert slots == [f"gh_schedule_slot_{n}" for n in range(1, len(slots) + 1)] and 1 <= len(slots) <= 8, path.name
        assert "gh_schedule" in keys and keys.index("gh_schedule") < keys.index(slots[0]), path.name


# ---------------------------------------------------------------------------------------------------- esphome config


def _run_config(args: list[str], env_extra: dict[str, str] | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        env={**os.environ, **(env_extra or {})},
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.config
@pytest.mark.parametrize("name", EXAMPLE_NAMES, ids=lambda n: n.replace("-", "_"))
def test_example_validates(name: str) -> None:
    result = _run_config(["sh", "script/config", f"examples/{name}.yaml"], {"GP_SECRETS": "example"})
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]


@pytest.mark.config
def test_example_validates_minimal_on_lilygo(tmp_path: Path) -> None:
    """Example 1 with the LilyGO T-Relay-S3 profile swapped in (a staged copy; relay numbers stay 1..12)."""
    for folder in ("packages", "hardware", "components"):
        shutil.copytree(REPO_ROOT / folder, tmp_path / folder)
    (tmp_path / "examples").mkdir()
    text = (EXAMPLES_DIR / "minimal-1-bed.yaml").read_text(encoding="utf-8")
    swapped = text.replace("hardware/esp32-s3-devkitc1-breadboard.yaml", "hardware/lilygo-t-relay-s3.yaml")
    assert swapped != text
    (tmp_path / "examples" / "minimal-1-bed.yaml").write_text(swapped, encoding="utf-8")
    shutil.copy(REPO_ROOT / "secrets.example.yaml", tmp_path / "examples" / "secrets.yaml")
    result = _run_config(["sh", str(REPO_ROOT / "script" / "_esphome"), "config", str(tmp_path / "examples" / "minimal-1-bed.yaml")])
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]


@pytest.mark.config
def test_script_config_subdir() -> None:
    """script/config handles a config in a subdirectory and never leaves a secrets.yaml in the checkout."""
    secrets = EXAMPLES_DIR / "secrets.yaml"
    existed = secrets.exists()
    result = _run_config(["sh", "script/config", "examples/minimal-1-bed.yaml"], {"GP_SECRETS": "example"})
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    assert "esphome config OK: examples/minimal-1-bed.yaml" in result.stdout
    assert secrets.exists() == existed, "script/config must not create or remove examples/secrets.yaml"
