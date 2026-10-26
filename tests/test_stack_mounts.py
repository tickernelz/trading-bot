import os
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "stack.sh"
CONTAINERS = ["bot-a", "bot-b", "shadow-b", "analyst-b", "gateway"]
FAKE_SYSTEMD_RUN = """#!/bin/bash
printf '%s\\n' "$*" >> "$SYSTEMD_LOG"
position=0
for argument in "$@"; do
  position=$((position + 1))
  if [ "$argument" = bash ]; then exec "${@:$position}"; fi
done
exit 0
"""
FAKE_DOCKER = '#!/bin/bash\nprintf "%s\\n" "$*" >> "$DOCKER_LOG"\n'
FAKE_NPM = '#!/bin/bash\nprintf "%s\\n" "$*" >> "$NPM_LOG"\n'


def start(tmp_path, *components):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (("systemd-run", FAKE_SYSTEMD_RUN), ("docker", FAKE_DOCKER), ("npm", FAKE_NPM)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    run_dir = tmp_path / "run"
    (run_dir / "secrets").mkdir(parents=True)
    logs = {name: tmp_path / f"{name.lower()}.log" for name in ("SYSTEMD", "DOCKER", "NPM")}
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SYSTEMD_LOG": str(logs["SYSTEMD"]),
        "DOCKER_LOG": str(logs["DOCKER"]),
        "NPM_LOG": str(logs["NPM"]),
    }
    env.update(RUN_DIR=str(run_dir), IMAGE="image:test")
    subprocess.run([str(SCRIPT), "start", *components], env=env, check=True, capture_output=True)
    for log in logs.values():
        log.touch()
    container_runs = [line for line in logs["DOCKER"].read_text().splitlines() if line.startswith("run ")]
    unit_lines = logs["SYSTEMD"].read_text().splitlines()
    return run_dir, container_runs, unit_lines, logs


@pytest.mark.parametrize("component", CONTAINERS)
def test_a_container_never_mounts_the_secrets_directory(tmp_path, component):
    run_dir, runs, _, _ = start(tmp_path, component)
    assert len(runs) == 1
    tokens = shlex.split(runs[0])
    mounts = [tokens[index + 1] for index, token in enumerate(tokens) if token == "-v"]
    sources = [mount.split(":")[0] for mount in mounts]
    assert sources
    for source in sources:
        assert Path(source).parent == run_dir
        assert Path(source).name != "secrets"


@pytest.mark.parametrize("component", CONTAINERS)
def test_config_is_read_only_and_data_directories_exist_for_the_container(tmp_path, component):
    run_dir, runs, _, _ = start(tmp_path, component)
    tokens = shlex.split(runs[0])
    mounts = [tokens[index + 1] for index, token in enumerate(tokens) if token == "-v"]
    by_source = {Path(mount.split(":")[0]).name: mount for mount in mounts}
    assert by_source["config"].endswith(":ro")
    data = [name for name in by_source if name != "config"]
    assert data
    for name in data:
        assert not by_source[name].endswith(":ro")
        assert (run_dir / name).is_dir()


def test_each_component_only_sees_the_data_it_needs(tmp_path):
    seen = {}
    for component in CONTAINERS:
        _, runs, _, _ = start(tmp_path / component, component)
        tokens = shlex.split(runs[0])
        seen[component] = {
            Path(tokens[index + 1].split(":")[0]).name for index, token in enumerate(tokens) if token == "-v"
        }
    assert seen["bot-a"] == {"config", "bot-a"}
    assert seen["gateway"] == {"config", "gateway", "bot-a", "bot-b"}
    for component in ("bot-b", "shadow-b", "analyst-b"):
        assert seen[component] == {"config", "bot-b"}


@pytest.mark.parametrize("component", CONTAINERS)
def test_every_container_is_capped_for_cpu_and_memory(tmp_path, component):
    _, runs, _, _ = start(tmp_path, component)
    tokens = shlex.split(runs[0])
    assert float(tokens[tokens.index("--cpus") + 1]) <= 1.0
    assert tokens[tokens.index("--memory") + 1] == tokens[tokens.index("--memory-swap") + 1]


def test_the_pwa_is_a_host_unit_bounded_by_nice_and_cpu_quota(tmp_path):
    _, runs, unit_lines, logs = start(tmp_path, "pwa")
    assert runs == []
    calls = logs["NPM"].read_text().splitlines()
    assert calls[-1] == "--prefix " + str(SCRIPT.parent.parent / "pwa") + " run build"
    unit = unit_lines[0]
    tokens = shlex.split(unit)
    assert "Nice=10" in tokens
    assert "CPUQuota=50%" in tokens
    assert "MemoryMax=512M" in tokens
    assert any(token.startswith("WorkingDirectory=") and token.endswith("/pwa") for token in tokens)
    assert any(token.startswith("Environment=PATH=") for token in tokens)
    assert unit.endswith("GATEWAY_URL=http://127.0.0.1:8090 npm run preview")


def test_the_default_component_list_is_the_whole_stack(tmp_path):
    _, runs, unit_lines, _ = start(tmp_path)
    assert len(runs) == len(CONTAINERS)
    units = [shlex.split(line)[shlex.split(line).index("--unit") + 1] for line in unit_lines]
    assert units == [f"trading-bot-stack-{component}" for component in [*CONTAINERS, "pwa"]]
