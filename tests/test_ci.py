"""Static checks of the CI workflows, Dependabot config, version sources and helper scripts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import REPO_ROOT

pytestmark = pytest.mark.unit

GITHUB = REPO_ROOT / ".github"
WORKFLOWS = GITHUB / "workflows"
CI = WORKFLOWS / "ci.yml"
CANARY = WORKFLOWS / "canary.yml"
DEPENDABOT = GITHUB / "dependabot.yml"
RULESET = GITHUB / "rulesets" / "master.json"
GITHUB_ACTIONS_APP_ID = 15368
SPEC = REPO_ROOT / "docs" / "SPEC.md"
DEVCONTAINER = REPO_ROOT / ".devcontainer" / "devcontainer.json"
DOCKERFILE = REPO_ROOT / ".devcontainer" / "Dockerfile"
SPEC_FLOOR = (2026, 2, 3)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_files() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def triggers(wf: dict) -> dict:
    # PyYAML reads a bare `on:` key as the boolean True.
    value = wf["on"] if "on" in wf else wf[True]
    return value if isinstance(value, dict) else {name: None for name in ([value] if isinstance(value, str) else value)}


def steps(job: dict) -> list[dict]:
    return job.get("steps", [])


def run_scripts(wf: dict) -> list[str]:
    return [s["run"] for job in wf["jobs"].values() for s in steps(job) if "run" in s]


def uses_steps(wf: dict) -> list[dict]:
    return [s for job in wf["jobs"].values() for s in steps(job) if "uses" in s]


def devcontainer_steps(job: dict) -> list[dict]:
    return [s for s in steps(job) if s.get("uses", "").startswith("devcontainers/ci@")]


def env_lines(step: dict) -> dict[str, str]:
    result = {}
    for line in str(step.get("with", {}).get("env", "")).splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            result[name.strip()] = value.strip()
    return result


def pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def pinned_version() -> str:
    for dep in pyproject()["dependency-groups"]["dev"]:
        match = re.fullmatch(r"esphome==(\d+\.\d+\.\d+)", dep)
        if match:
            return match.group(1)
    raise AssertionError("no exact esphome pin in pyproject.toml")


def minimum_version() -> str:
    return pyproject()["tool"]["garden-pilot"]["esphome-minimum"]


def vtuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def spec_section(heading_prefix: str) -> str:
    text = SPEC.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(heading_prefix)}.*?(?=^## |\Z)", text, re.S | re.M)
    assert match, heading_prefix
    return match.group(0)


def test_workflows_parse() -> None:
    assert CI.is_file() and CANARY.is_file()
    for path in workflow_files():
        wf = load_yaml(path)
        assert isinstance(wf, dict), path
        assert wf.get("name"), path
        assert triggers(wf), path
        assert wf.get("jobs"), path


def test_ci_triggers() -> None:
    trig = triggers(load_yaml(CI))
    assert set(trig) == {"pull_request", "push", "workflow_dispatch"}
    assert trig["pull_request"] == {"branches": ["master"]}
    assert trig["push"] == {"branches": ["master"]}
    assert "paths" not in json.dumps(trig) and "paths-ignore" not in json.dumps(trig)


def test_no_privileged_triggers() -> None:
    for path in workflow_files():
        names = set(triggers(load_yaml(path)))
        assert not names & {"pull_request_target", "workflow_run"}, path


def test_permissions_are_least_privilege() -> None:
    for path in workflow_files():
        wf = load_yaml(path)
        assert wf.get("permissions") == {}, path
        for name, job in wf["jobs"].items():
            assert "permissions" in job, (path, name)
            perms = job["permissions"]
            if path == CANARY and name == "report":
                assert perms == {"issues": "write"}
            else:
                assert set(perms.items()) <= {("contents", "read")}, (path, name)
        text = path.read_text(encoding="utf-8")
        assert "write-all" not in text and "read-all" not in text, path


def test_actions_are_pinned_to_sha() -> None:
    for path in workflow_files():
        wf = load_yaml(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        for step in uses_steps(wf):
            ref = step["uses"]
            assert not ref.startswith("docker://"), ref
            if ref.startswith("./"):
                continue
            assert re.fullmatch(r"[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}", ref), ref
            raw = [line for line in lines if re.search(rf"uses:\s*{re.escape(ref)}", line)]
            assert raw and all(re.search(r"# v\d+", line) for line in raw), ref


def test_checkout_does_not_persist_credentials() -> None:
    seen = 0
    for path in workflow_files():
        for step in uses_steps(load_yaml(path)):
            if step["uses"].startswith("actions/checkout@"):
                seen += 1
                assert step.get("with", {}).get("persist-credentials") is False, path
    assert seen


def test_every_job_has_a_timeout() -> None:
    for path in workflow_files():
        for name, job in load_yaml(path)["jobs"].items():
            timeout = job.get("timeout-minutes")
            assert isinstance(timeout, int) and 1 <= timeout <= 120, (path, name)


def test_ci_concurrency_cancels_superseded_prs() -> None:
    conc = load_yaml(CI)["concurrency"]
    assert "github.event.pull_request.number" in conc["group"] or "github.ref" in conc["group"]
    cancel = conc["cancel-in-progress"]
    assert isinstance(cancel, str) and "pull_request" in cancel and cancel.strip() != "true"


def ci_check_names() -> set[str]:
    jobs = load_yaml(CI)["jobs"]
    names = set()
    for key, job in jobs.items():
        name = job.get("name", key)
        matrix = job.get("strategy", {}).get("matrix")
        if matrix:
            for target in matrix["target"]:
                names.add(name.replace("${{ matrix.target }}", target))
        else:
            names.add(name)
    return names


def test_required_check_names_are_stable() -> None:
    jobs = load_yaml(CI)["jobs"]
    names = set()
    for key, job in jobs.items():
        name = job.get("name", key)
        matrix = job.get("strategy", {}).get("matrix")
        if matrix:
            for target in matrix["target"]:
                names.add(name.replace("${{ matrix.target }}", target))
        else:
            names.add(name)
    assert names == {"checks", "compile (pinned)", "compile (minimum)"}
    strategy = jobs["compile"]["strategy"]
    assert strategy["matrix"]["target"] == ["pinned", "minimum"]
    assert strategy["fail-fast"] is False


def test_build_jobs_use_the_devcontainer() -> None:
    ci_jobs = load_yaml(CI)["jobs"]
    canary_job = load_yaml(CANARY)["jobs"]["canary"]
    for job in [*ci_jobs.values(), canary_job]:
        found = devcontainer_steps(job)
        assert len(found) == 1
        with_ = found[0]["with"]
        assert with_["push"] == "never"
        assert with_["imageName"]
        assert with_.get("configFile", ".devcontainer/devcontainer.json") == ".devcontainer/devcontainer.json"
    checks = devcontainer_steps(ci_jobs["checks"])[0]["with"]["runCmd"]
    assert "script/lint" in checks and "script/test" in checks
    compile_step = devcontainer_steps(ci_jobs["compile"])[0]
    assert "script/compile" in compile_step["with"]["runCmd"]
    env = env_lines(compile_step)
    assert env["GP_SECRETS"] == "example"
    assert env["GP_ESPHOME"] == "${{ matrix.target }}"
    canary_env = env_lines(devcontainer_steps(canary_job)[0])
    assert "latest" in canary_env["GP_ESPHOME"] and "inputs.esphome" in canary_env["GP_ESPHOME"]


def _volume_names() -> set[str]:
    """Volume names are the last token of each `docker volume create` command (after `\\` continuations)."""
    names = set()
    for path in workflow_files():
        for script in run_scripts(load_yaml(path)):
            for command in re.findall(r"docker volume create(?:[^\n]*\\\n)*[^\n]*", script):
                names.add(command.split()[-1])
    return names


def test_cache_volumes_match_devcontainer() -> None:
    mounts = {}
    for mount in json.loads(DEVCONTAINER.read_text(encoding="utf-8"))["mounts"]:
        parts = dict(p.split("=", 1) for p in mount.split(",") if "=" in p)
        if parts.get("type") == "volume":
            mounts[parts["target"]] = parts["source"]
    expected = {mounts["/home/vscode/.cache"], mounts["/home/vscode/.platformio"]}
    assert _volume_names() == expected


def test_compile_cache_key() -> None:
    compile_job = load_yaml(CI)["jobs"]["compile"]
    caches = [s for s in steps(compile_job) if s.get("uses", "").startswith("actions/cache@")]
    assert caches
    for step in caches:
        key = step["with"]["key"]
        assert "matrix.target" in key
        assert "hashFiles(" in key and "pyproject.toml" in key and "uv.lock" in key
        assert "restore-keys" not in step["with"]
    canary = load_yaml(CANARY)
    for step in uses_steps(canary):
        if step["uses"].startswith("actions/cache"):
            assert step["uses"].startswith("actions/cache/restore@"), step["uses"]


def test_workflows_use_no_secrets() -> None:
    for path in GITHUB.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "secrets." not in text, path
            assert "!secret" not in text, path
            assert "secrets.yaml" not in text, path


def test_no_untrusted_interpolation_in_run() -> None:
    for path in workflow_files():
        wf = load_yaml(path)
        # devcontainers/ci `runCmd` is a shell script too.
        run_cmds = [str(s.get("with", {}).get("runCmd", "")) for s in uses_steps(wf)]
        for script in run_scripts(wf) + run_cmds:
            for needle in ("${{ github.event.", "${{ github.head_ref", "${{ inputs."):
                assert needle not in script, (path, needle)


def test_canary_triggers() -> None:
    trig = triggers(load_yaml(CANARY))
    assert set(trig) == {"schedule", "workflow_dispatch"}
    assert len(trig["schedule"]) == 1 and trig["schedule"][0]["cron"]
    assert trig["workflow_dispatch"]["inputs"]["esphome"]["default"] == "latest"


def test_canary_reports_through_one_issue() -> None:
    wf = load_yaml(CANARY)
    report = wf["jobs"]["report"]
    assert report["needs"] == "canary" or report["needs"] == ["canary"]
    assert "always()" in report["if"]
    assert report["permissions"] == {"issues": "write"}
    assert not [s for s in steps(report) if "uses" in s]
    assert "canary-failure" in "\n".join(run_scripts({"jobs": {"report": report}}))
    for name, job in wf["jobs"].items():
        if name != "report":
            assert "write" not in job["permissions"].values()


def test_dependabot_ecosystems() -> None:
    cfg = load_yaml(DEPENDABOT)
    assert cfg["version"] == 2
    updates = {u["package-ecosystem"]: u for u in cfg["updates"]}
    assert {k: v["directory"] for k, v in updates.items()} == {
        "github-actions": "/",
        "uv": "/",
        "docker": "/.devcontainer",
    }
    assert len(cfg["updates"]) == 3
    for update in updates.values():
        assert update["schedule"]["interval"] == "weekly"
        assert update["commit-message"]["prefix"]
        assert "esphome" not in json.dumps(update.get("ignore", []))
        for group in update.get("groups", {}).values():
            assert "esphome" not in group.get("patterns", [])
    groups = updates["uv"]["groups"]
    patterns = {p for g in groups.values() for p in g["patterns"]}
    assert {"pytest", "pyyaml", "yamllint"} <= patterns


def test_dockerfile_images_are_visible_to_dependabot() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    from_lines = [line for line in text.splitlines() if line.startswith("FROM ")]
    assert len(from_lines) >= 2
    for line in from_lines:
        assert re.search(r"@sha256:[0-9a-f]{64}", line), line
    stages = {m.group(1) for m in re.finditer(r"^FROM .* AS (\w+)\s*$", text, re.M)}
    for ref in re.findall(r"COPY --from=(\S+)", text):
        assert ref in stages, ref
    assert "until Dependabot" not in text


def test_esphome_pin_matches_lock() -> None:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = [p["version"] for p in lock["package"] if p["name"] == "esphome"]
    assert locked == [pinned_version()]


def test_spec_versions_match_sources() -> None:
    section = spec_section("6.")
    pinned = re.search(r"\*\*Pinned \(development\):\*\* ESPHome \*\*(\d+\.\d+\.\d+)\*\*", section)
    minimum = re.search(r"\*\*Minimum supported:\*\* ESPHome \*\*(\d+\.\d+\.\d+)\*\*", section)
    assert pinned and minimum
    assert pinned.group(1) == pinned_version()
    assert minimum.group(1) == minimum_version()
    assert SPEC_FLOOR <= vtuple(minimum_version()) <= vtuple(pinned_version())


def test_spec_min_version_question_is_closed() -> None:
    text = SPEC.read_text(encoding="utf-8")
    open_questions = re.search(r"^## 10\..*?(?=^### 10\.1|^## 11)", text, re.S | re.M)
    decided = re.search(r"^### 10\.1.*?(?=^## )", text, re.S | re.M)
    assert open_questions and decided
    assert "minimum esphome" not in open_questions.group(0).lower()
    assert "minimum esphome" in decided.group(0).lower()
    assert minimum_version() in decided.group(0)


def _resolve(value: str | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "GP_ESPHOME"}
    if value is not None:
        env["GP_ESPHOME"] = value
    return subprocess.run(
        ["sh", "script/_esphome", "--resolve"], cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )


def test_esphome_selector_resolves() -> None:
    for name in ("_esphome", "compile"):
        script = REPO_ROOT / "script" / name
        assert script.is_file() and script.stat().st_mode & 0o111, name
    assert _resolve(None).stdout.strip() == pinned_version()
    assert _resolve("pinned").stdout.strip() == pinned_version()
    assert _resolve("minimum").stdout.strip() == minimum_version()
    assert _resolve("latest").stdout.strip() == "latest"
    assert _resolve("2026.5.0").stdout.strip() == "2026.5.0"
    for bad in ("1; true", "bogus", "2026.5", "2026.5.0; id", " "):
        result = _resolve(bad)
        assert result.returncode != 0, bad
        assert result.stdout.strip() == "", bad


def _copied_paths(script: str) -> list[str]:
    text = (REPO_ROOT / "script" / script).read_text(encoding="utf-8")
    match = re.search(r"for path in (.*?); do", text)
    assert match, script
    return match.group(1).split()


def test_compile_stages_like_config() -> None:
    assert _copied_paths("compile") == _copied_paths("config")
    compile_text = (REPO_ROOT / "script" / "compile").read_text(encoding="utf-8")
    assert ".esphome/example-build" in compile_text
    assert ".esphome/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    config_text = (REPO_ROOT / "script" / "config").read_text(encoding="utf-8")
    assert "uv run" not in config_text and "script/_esphome" in config_text


def test_readmes_have_ci_badge() -> None:
    for name in ("README.md", "README.ru.md"):
        assert "actions/workflows/ci.yml/badge.svg" in (REPO_ROOT / name).read_text(encoding="utf-8"), name


def ruleset() -> dict:
    return json.loads(RULESET.read_text(encoding="utf-8"))


def rules_by_type() -> dict[str, dict]:
    return {rule["type"]: rule.get("parameters", {}) for rule in ruleset()["rules"]}


def test_ruleset_targets_the_default_branch() -> None:
    rs = ruleset()
    assert rs["target"] == "branch"
    assert rs["enforcement"] == "active"
    assert rs["bypass_actors"] == []
    assert rs["conditions"]["ref_name"] == {"include": ["~DEFAULT_BRANCH"], "exclude": []}


def test_ruleset_protects_history() -> None:
    assert {"deletion", "non_fast_forward", "required_linear_history"} <= rules_by_type().keys()


def test_ruleset_requires_squash_pull_requests() -> None:
    pr = rules_by_type()["pull_request"]
    assert pr["allowed_merge_methods"] == ["squash"]
    assert pr["required_approving_review_count"] == 0
    assert pr["required_review_thread_resolution"] is True


def test_ruleset_required_checks_match_ci_jobs() -> None:
    checks = rules_by_type()["required_status_checks"]
    required = checks["required_status_checks"]
    assert {c["context"] for c in required} == ci_check_names()
    assert all(c["integration_id"] == GITHUB_ACTIONS_APP_ID for c in required)
    assert checks["strict_required_status_checks_policy"] is False
