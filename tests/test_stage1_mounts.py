import os
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "stage1.sh"
COMPONENTS = ["bot-a", "bot-b", "shadow-b", "analyst-b", "gateway"]
FAKE_SYSTEMD_RUN = '#!/bin/bash\nwhile [ "$1" != bash ]; do shift; done\nexec "$@"\n'
FAKE_DOCKER = '#!/bin/bash\nprintf "%s\\n" "$*" >> "$DOCKER_LOG"\n'


def start(tmp_path, component):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (("systemd-run", FAKE_SYSTEMD_RUN), ("docker", FAKE_DOCKER)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    run_dir = tmp_path / "run"
    (run_dir / "secrets").mkdir(parents=True)
    log = tmp_path / "docker.log"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "DOCKER_LOG": str(log)}
    env.update(RUN_DIR=str(run_dir), IMAGE="image:test")
    subprocess.run([str(SCRIPT), "start", component], env=env, check=True, capture_output=True)
    runs = [line for line in log.read_text().splitlines() if line.startswith("run ")]
    assert len(runs) == 1
    tokens = shlex.split(runs[0])
    mounts = [tokens[i + 1] for i, token in enumerate(tokens) if token == "-v"]
    return run_dir, mounts


@pytest.mark.parametrize("component", COMPONENTS)
def test_a_container_never_mounts_the_secrets_directory(tmp_path, component):
    run_dir, mounts = start(tmp_path, component)
    sources = [mount.split(":")[0] for mount in mounts]
    assert sources
    for source in sources:
        assert Path(source).parent == run_dir
        assert Path(source).name != "secrets"


@pytest.mark.parametrize("component", COMPONENTS)
def test_config_is_read_only_and_data_directories_exist_for_the_container(tmp_path, component):
    run_dir, mounts = start(tmp_path, component)
    by_source = {Path(mount.split(":")[0]).name: mount for mount in mounts}
    assert by_source["config"].endswith(":ro")
    data = [name for name in by_source if name != "config"]
    assert data
    for name in data:
        assert not by_source[name].endswith(":ro")
        assert (run_dir / name).is_dir()


def test_each_component_only_sees_the_data_it_needs(tmp_path):
    seen = {
        component: {Path(m.split(":")[0]).name for m in start(tmp_path / component, component)[1]}
        for component in COMPONENTS
    }
    assert seen["bot-a"] == {"config", "bot-a"}
    assert seen["gateway"] == {"config", "gateway", "bot-a", "bot-b"}
    for component in ("bot-b", "shadow-b", "analyst-b"):
        assert seen[component] == {"config", "bot-b"}
