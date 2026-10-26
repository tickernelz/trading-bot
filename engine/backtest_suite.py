"""Run the pre-registered stage 2 backtest matrix and summarise it from the exported Freqtrade results."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from engine.backtest_report import load_run, markdown, summarize
from engine.settings import load_settings

FEE_PCT = 0.2
TAX_PCT = 0.21
SEED = 3778
PERIODS = {"in_sample": "20231026-20251026", "out_of_sample": "20251026-20261026"}
COSTS = {"fee_and_tax": (FEE_PCT + TAX_PCT) / 100, "fee_only": FEE_PCT / 100, "no_cost": 0.0}
RISK_MODES: dict[str, dict[str, float]] = {
    "as_configured": {},
    "limits_off": {"max_daily_loss_pct": 100.0, "max_total_drawdown_pct": 100.0},
}
MATRIX = (
    ("as_configured", "fee_and_tax"),
    ("limits_off", "fee_and_tax"),
    ("limits_off", "fee_only"),
    ("limits_off", "no_cost"),
)


@dataclass(frozen=True)
class Run:
    id: str
    period: str
    timerange: str
    risk_mode: str
    cost: str
    fee: float


def plan() -> list[Run]:
    """Every backtest of the suite, fixed before any result exists."""
    return [
        Run(f"{period}-{risk_mode}-{cost}", period, timerange, risk_mode, cost, COSTS[cost])
        for period, timerange in PERIODS.items()
        for risk_mode, cost in MATRIX
    ]


def risk_config(base: dict[str, Any], risk_mode: str) -> dict[str, Any]:
    """Return the base configuration with the risk overrides of risk_mode applied."""
    config = copy.deepcopy(base)
    config["risk"].update(RISK_MODES[risk_mode])
    return config


def backtest_argv(run: Run, out: Path, datadir: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "engine.launch",
        "backtesting",
        "--timerange",
        run.timerange,
        "--fee",
        repr(run.fee),
        "--export",
        "trades",
        "--backtest-directory",
        str(out),
        "--cache",
        "none",
        "--datadir",
        str(datadir),
    ]


def execute(run: Run, config_path: Path, out: Path, datadir: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    userdir = out / "userdir"
    userdir.mkdir(exist_ok=True)
    env = {**os.environ, "TRADING_BOT_CONFIG": str(config_path), "TRADING_BOT_USERDIR": str(userdir)}
    started = datetime.now(UTC)
    with (out / "freqtrade.log").open("w", encoding="utf-8") as log:
        code = subprocess.run(
            backtest_argv(run, out, datadir), env=env, stdout=log, stderr=subprocess.STDOUT
        ).returncode
    seconds = (datetime.now(UTC) - started).total_seconds()
    if code != 0:
        raise RuntimeError(f"backtest {run.id} exited {code}; see {out / 'freqtrade.log'}")
    trades, stats = load_run(out, load_settings(config_path).strategy.name)
    log_text = (out / "freqtrade.log").read_text(encoding="utf-8")
    return {**asdict(run), "seconds": round(seconds, 1), "summary": summarize(trades, stats, SEED, log_text)}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.backtest_suite", description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--datadir", required=True, type=Path)
    args = parser.parse_args(argv)

    base_path = Path(os.environ.get("TRADING_BOT_CONFIG", "config/config.yaml"))
    base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    configs = args.out / "config"
    configs.mkdir(parents=True, exist_ok=True)
    for risk_mode in RISK_MODES:
        path = configs / f"{risk_mode}.yaml"
        path.write_text(yaml.safe_dump(risk_config(base, risk_mode), sort_keys=False), encoding="utf-8")
        load_settings(path)
    runs = plan()
    meta = {"fee_pct": FEE_PCT, "tax_pct": TAX_PCT, "seed": SEED, "periods": PERIODS, "risk_modes": RISK_MODES}
    (args.out / "plan.json").write_text(
        json.dumps({**meta, "runs": [asdict(run) for run in runs]}, indent=2), encoding="utf-8"
    )
    results = []
    for run in runs:
        result = execute(run, configs / f"{run.risk_mode}.yaml", args.out / "runs" / run.id, args.datadir)
        results.append(result)
        print(f"{run.id}: {result['summary']['trades']} trades in {result['seconds']} s", file=sys.stderr)
    report = {**meta, "generated_at": datetime.now(UTC).isoformat(), "runs": results}
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.out / "report.md").write_text(markdown(results), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
