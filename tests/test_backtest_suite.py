from __future__ import annotations

import pytest

from engine.backtest_suite import COSTS, PERIODS, plan, risk_config
from engine.settings import RiskSettings


def test_every_period_runs_the_same_matrix_and_out_of_sample_follows_in_sample():
    runs = plan()
    by_period = {period: {(run.risk_mode, run.cost) for run in runs if run.period == period} for period in PERIODS}
    assert by_period["in_sample"] == by_period["out_of_sample"]
    assert len({run.id for run in runs}) == len(runs)
    in_end = PERIODS["in_sample"].split("-")[1]
    out_start = PERIODS["out_of_sample"].split("-")[0]
    assert in_end == out_start


def test_primary_cost_is_fee_plus_tax_per_side():
    assert COSTS["fee_and_tax"] == pytest.approx(0.0041)


def test_limits_off_keeps_sizing_and_stays_valid(example_raw):
    relaxed = risk_config(example_raw, "limits_off")
    assert example_raw["risk"]["max_total_drawdown_pct"] == 10.0
    assert relaxed["risk"]["risk_per_trade_pct"] == example_raw["risk"]["risk_per_trade_pct"]
    assert RiskSettings.model_validate(relaxed["risk"]).max_total_drawdown_pct == 100.0
    assert risk_config(example_raw, "as_configured") == example_raw
