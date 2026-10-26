from __future__ import annotations

import argparse
import multiprocessing
import sys
from pathlib import Path

from tbapp import paths, version
from tbapp.provision import DEFAULT_PORT_BASE, Ports, check_port_base, provision

COMPONENTS = ("bot-a", "bot-b", "shadow", "analyst", "gateway")


def run_component(name: str) -> int:
    if name in {"bot-a", "bot-b"}:
        from engine import launch

        return launch.main(["trade"])
    if name == "shadow":
        from engine import shadow

        return shadow.main()
    if name == "analyst":
        from engine import analyst_service

        return analyst_service.main()
    from gateway.__main__ import main as gateway_main

    return gateway_main()


def print_version() -> int:
    import ccxt
    import freqtrade
    import numpy
    import pandas
    import talib

    print(version.describe())
    print(
        f"freqtrade {freqtrade.__version__}, ccxt {ccxt.__version__}, pandas {pandas.__version__}, "
        f"numpy {numpy.__version__}, ta-lib {talib.__version__}"
    )
    return 0


def home_of(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    return paths.data_home()


def prepare(home: Path, port_base: int) -> None:
    password = provision(home, paths.bundle_root(), Ports(check_port_base(port_base)))
    if password is not None:
        print(f"created {home}")
        print(f"web panel password: {password}")
        print(f"(kept in {home / 'secrets' / 'gateway.env'})", flush=True)


def run(home: Path, port_base: int) -> int:
    from tbapp.supervisor import Supervisor, busy_ports, configured_ports

    prepare(home, port_base)
    busy = busy_ports(configured_ports(home))
    if busy:
        listing = ", ".join(f"{name} on {port}" for name, port in busy.items())
        print(f"trading-bot: refusing to start: ports already in use: {listing}", file=sys.stderr)
        return 2
    if paths.pwa_dir() is None:
        print("trading-bot: web panel files not found; only the API will be served", file=sys.stderr)
    return Supervisor(home).run()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="trading-bot", description="Spot crypto swing bot, dry-run only.")
    root.add_argument("--version", action="store_true", help="print versions and exit")
    sub = root.add_subparsers(dest="command")
    for name, text in (("run", "start everything"), ("init", "create the data folder and exit")):
        command = sub.add_parser(name, help=text)
        command.add_argument("--home", help="data folder (default: per-user application data)")
        command.add_argument(
            "--port-base",
            type=int,
            default=DEFAULT_PORT_BASE,
            help=f"first of the local ports, used when the data folder is created (default {DEFAULT_PORT_BASE})",
        )
    inner = sub.add_parser("component")
    inner.add_argument("name", choices=COMPONENTS)
    return root


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    args = parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        return print_version()
    if args.command == "component":
        return run_component(args.name)
    if args.command == "init":
        prepare(home_of(args.home), args.port_base)
        return 0
    return run(home_of(getattr(args, "home", None)), getattr(args, "port_base", DEFAULT_PORT_BASE))
