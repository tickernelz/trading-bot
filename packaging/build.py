#!/usr/bin/env python3
"""Build the native bundle for one target: install pinned dependencies, run PyInstaller, archive, checksum."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("linux-x64", "linux-arm64", "win-x64", "win-arm64", "mac-x64", "mac-arm64")
ALWAYS_DROPPED = {"bottleneck"}
EXTRA_REQUIREMENTS = ("pyyaml==6.0.3", "pywebpush==2.5.0", "http_ece==1.2.1", "py-vapid==1.9.6")
PYINSTALLER = "pyinstaller==6.22.3"
REPO_URL = "https://github.com/tickernelz/trading-bot"


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(line: str) -> str | None:
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line.strip())
    return normalize(match.group(1)) if match else None


def freqtrade_requirements(dropped: set[str]) -> list[str]:
    lines = []
    for raw in (ROOT / "vendor" / "freqtrade" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and requirement_name(line) not in dropped:
            lines.append(line)
    return lines


def pinned(name: str) -> str:
    for raw in (ROOT / "swarm" / "constraints.txt").read_text(encoding="utf-8").splitlines():
        if requirement_name(raw) == normalize(name):
            return raw.strip()
    raise SystemExit(f"{name} is not pinned in swarm/constraints.txt")


def run(command: list[str], **kwargs) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, check=True, **kwargs)


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_source_notice(folder: Path, version: str, target: str, commit: str) -> None:
    freqtrade = subprocess.run(
        ["git", "-C", str(ROOT / "vendor" / "freqtrade"), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    (folder / "SOURCE.txt").write_text(
        f"trading-bot {version} ({target})\n"
        f"Source code: {REPO_URL}\n"
        f"Commit: {commit or 'unknown'}\n"
        f"Release page: {REPO_URL}/releases/tag/v{version}\n"
        f"Freqtrade (unmodified, GPL-3.0): https://github.com/freqtrade/freqtrade at {freqtrade or 'unknown'}\n"
        "This program is free software under the GNU General Public License v3.0; see LICENSE.\n"
        "The bundle also contains third-party Python packages under their own licenses.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument("--version", default="0.0.0+dev")
    parser.add_argument("--commit", default="")
    parser.add_argument("--python", default="3.13")
    parser.add_argument("--skip", default="", help="comma separated requirements left out of the bundle")
    parser.add_argument("--from-source", default="", help="comma separated packages built from their sdist")
    parser.add_argument("--wheelhouse", type=Path, help="where wheels built from source are kept")
    parser.add_argument("--pwa", type=Path, default=ROOT / "pwa" / "dist")
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()

    work = (args.work or ROOT / "build" / args.target).resolve()
    venv = work / "venv"
    out = work / "out"
    dropped = ALWAYS_DROPPED | {normalize(name) for name in args.skip.split(",") if name}
    from_source = [normalize(name) for name in args.from_source.split(",") if name]
    if not (args.pwa / "index.html").is_file():
        raise SystemExit(f"{args.pwa} has no index.html; run npm run build in pwa first")

    shutil.rmtree(work, ignore_errors=True)
    out.mkdir(parents=True)
    run(["uv", "venv", "--seed", "--python", args.python, str(venv)])
    python = str(venv_python(venv))
    constraints = ROOT / "swarm" / "constraints.txt"
    find_links: list[str] = []
    if from_source:
        wheelhouse = (args.wheelhouse or work / "wheelhouse").resolve()
        wheelhouse.mkdir(parents=True, exist_ok=True)
        for name in from_source:
            run([python, "-m", "pip", "wheel", "--no-deps", "--no-binary", name, "-w", str(wheelhouse), pinned(name)])
        find_links = ["--find-links", str(wheelhouse)]

    requirements = work / "requirements.txt"
    requirements.write_text("\n".join([*freqtrade_requirements(dropped), *EXTRA_REQUIREMENTS]) + "\n", encoding="utf-8")
    install = ["uv", "pip", "install", "--python", python, "-c", str(constraints), *find_links]
    run([*install, "-r", str(requirements), str(ROOT / "swarm"), PYINSTALLER])
    run(
        [
            "uv", "pip", "install", "--python", python, "--no-deps",
            str(ROOT / "vendor" / "freqtrade"), str(ROOT / "vendor" / "freqtrade" / "ft_client"),
        ]
    )

    build_file = ROOT / "tbapp" / "_build.py"
    build_file.write_text(f'VERSION = "{args.version}"\nTARGET = "{args.target}"\n', encoding="utf-8")
    env = {**os.environ, "TB_PWA_DIR": str(args.pwa.resolve()), "TB_DROPPED": ",".join(sorted(dropped))}
    try:
        run(
            [
                python, "-m", "PyInstaller", str(ROOT / "packaging" / "trading-bot.spec"), "--noconfirm",
                "--distpath", str(work / "dist"), "--workpath", str(work / "pyi"),
            ],
            env=env,
            cwd=ROOT,
        )
    finally:
        build_file.unlink(missing_ok=True)

    bundle = work / "dist" / "trading-bot"
    shutil.copy(ROOT / "LICENSE", bundle / "LICENSE")
    write_source_notice(bundle, args.version, args.target, args.commit)
    name = f"trading-bot-{args.version}-{args.target}"
    staging = work / "stage"
    shutil.copytree(bundle, staging / name, symlinks=True)
    fmt = "zip" if args.target.startswith("win") else "gztar"
    archive = Path(shutil.make_archive(str(out / name), fmt, root_dir=staging, base_dir=name))
    (out / f"{archive.name}.sha256").write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    print(f"archive {archive} {archive.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
