#!/usr/bin/env python3
"""Start the app from a command on random local ports, then check the web panel, sign-in and /gw/v1/health."""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT_OFFSETS = (0, 1, 10, 11, 12)


def free_base() -> int:
    for _ in range(200):
        base = random.randint(20000, 60000)
        sockets = []
        try:
            for offset in PORT_OFFSETS:
                probe = socket.socket()
                sockets.append(probe)
                probe.bind(("127.0.0.1", base + offset))
        except OSError:
            continue
        finally:
            for probe in sockets:
                probe.close()
        return base
    raise SystemExit("no free port range found")


def request(url: str, body: dict | None = None, token: str | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=15) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def read_env(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def tail(home: Path) -> None:
    for log in sorted((home / "logs").glob("*.log")):
        lines = log.read_text(errors="replace").splitlines()[-25:]
        print(f"--- {log.name} (last {len(lines)} lines)")
        print("\n".join(lines))


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--engine-wait", type=int, default=120)
    parser.add_argument("command", nargs="+")
    args = parser.parse_args()

    version = subprocess.run([*args.command, "--version"], capture_output=True, text=True, timeout=180)
    print(version.stdout.strip())
    if version.returncode != 0:
        print(version.stderr[-3000:], file=sys.stderr)
        print("FAIL: --version exited with", version.returncode)
        return 1

    home = Path(tempfile.mkdtemp(prefix="tb-smoke-"))
    base = free_base()
    gateway = f"http://127.0.0.1:{base + 10}"
    env = {**os.environ, "TRADING_BOT_HOME": str(home)}
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [*args.command, "run", "--port-base", str(base)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=flags,
    )
    ok = False
    try:
        deadline = time.monotonic() + args.timeout
        index = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                print("FAIL: the app exited early with", proc.returncode)
                print(proc.stdout.read()[-3000:])
                return 1
            try:
                status, page = request(gateway + "/")
                if status == 200:
                    index = page
                    break
            except OSError:
                time.sleep(1)
        if index is None or b"<html" not in index.lower():
            print("FAIL: the web panel did not answer on", gateway)
            return 1
        print("web panel: 200, index.html served")
        password = read_env(home / "secrets" / "gateway.env")["GW_PASSWORD"]
        status, body = request(gateway + "/gw/v1/session", {"password": password})
        if status != 200:
            print("FAIL: sign-in returned", status, body[:200])
            return 1
        token = json.loads(body)["token"]
        print("sign-in: 200")
        status = 0
        engine_deadline = time.monotonic() + args.engine_wait
        while time.monotonic() < engine_deadline:
            status, body = request(gateway + "/gw/v1/health", token=token)
            if status == 200:
                break
            time.sleep(3)
        try:
            answer = json.loads(body)
        except ValueError:
            print("FAIL: health answered", status, "with a body that is not JSON:", body[:300])
            return 1
        if status == 200:
            print("health: 200 gateway", answer["gateway"]["status"], "freqtrade", answer["freqtrade"])
            print("RESULT: gateway and engine answered")
            ok = True
        elif isinstance(answer.get("error"), dict) or "code" in answer:
            print("health:", status, json.dumps(answer)[:300])
            if os.environ.get("SMOKE_REQUIRE_ENGINE") == "1":
                print("FAIL: the engine did not come up within", args.engine_wait, "s")
                return 1
            print("RESULT: gateway answered, engine did not come up within", args.engine_wait, "s")
            ok = True
        else:
            print("FAIL: unexpected health answer", status, body[:300])
            return 1
        return 0
    finally:
        stop(proc)
        if not ok:
            tail(home)
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
