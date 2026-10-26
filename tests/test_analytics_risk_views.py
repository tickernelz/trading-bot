from __future__ import annotations

import copy

import pytest

from analytics.errors import AnalyticsError
from analytics.export import tax_summary, trades_csv
from analytics.limits import limits_idr, whatif_limits
from analytics.portfolio import portfolio
from analytics.stress import stress
from analytics.trades import position_of, risk_inputs
from engine.settings import Settings
from tests.analytics_support import NOW, closed_trade, open_trade


@pytest.fixture
def settings(example_raw) -> Settings:
    return Settings.model_validate(example_raw)


def inputs_for(settings, trades):
    return risk_inputs(settings, trades, NOW)


class TestLimits:
    def test_percentages_become_rupiah_against_the_engine_equity(self, settings):
        inputs = inputs_for(settings, [])
        limits = limits_idr(settings.risk, inputs.assess(settings.risk))
        assert limits.max_daily_loss_idr == pytest.approx(20_000)
        assert limits.daily_floor_idr == pytest.approx(1_980_000)
        assert limits.max_total_drawdown_idr == pytest.approx(200_000)
        assert limits.risk_per_trade_idr == pytest.approx(10_000)
        assert limits.max_open_risk_idr == pytest.approx(30_000)
        assert limits.trades_to_daily_limit == pytest.approx(2.0)

    def test_a_looser_daily_limit_moves_the_rupiah_figures_by_exactly_the_difference(self, settings):
        result = whatif_limits(settings.risk, {"max_daily_loss_pct": 2.0}, inputs_for(settings, []))
        assert result["delta_idr"]["max_daily_loss_idr"] == pytest.approx(20_000)
        assert result["delta_idr"]["max_total_drawdown_idr"] == 0
        assert result["changed"] == ["max_daily_loss_pct"]

    def test_a_tighter_limit_flags_the_losses_already_taken_today(self, settings):
        trades = [closed_trade(-12_000, close_date="2026-10-26 01:00:00")]
        result = whatif_limits(settings.risk, {"max_daily_loss_pct": 0.5}, inputs_for(settings, trades))
        assert result["current"]["now"]["breaches"] == []
        assert result["proposed"]["now"]["breaches"] == ["daily_loss"]
        assert result["proposed"]["now"]["entries_allowed"] is False

    def test_stops_filling_add_the_loss_between_now_and_each_stop(self, settings):
        inputs = inputs_for(settings, [open_trade(stake=300_000, stop_pct=-3.0)])
        result = whatif_limits(settings.risk, {}, inputs)
        position = inputs.positions[0]
        expected = position.pnl - position.pnl_at(position.stop_abs)
        assert result["current"]["all_stops_hit"]["additional_loss_idr"] == pytest.approx(expected)
        assert result["current"]["all_stops_hit"]["daily_loss_pct"] > result["current"]["now"]["daily_loss_pct"]

    def test_positions_without_a_stop_are_counted_not_guessed(self, settings):
        trade = open_trade()
        del trade["stop_loss_abs"]
        result = whatif_limits(settings.risk, {}, inputs_for(settings, [trade]))
        assert result["current"]["all_stops_hit"]["positions_without_stop"] == 1
        assert result["current"]["all_stops_hit"]["additional_loss_idr"] == 0

    def test_a_proposal_that_breaks_the_limit_ordering_is_refused(self, settings):
        with pytest.raises(AnalyticsError) as error:
            whatif_limits(settings.risk, {"risk_per_trade_pct": 2.0}, inputs_for(settings, []))
        assert error.value.status == 422
        assert "risk_per_trade_pct" in error.value.message

    def test_only_the_four_tunable_limits_can_be_previewed(self, settings):
        with pytest.raises(AnalyticsError) as error:
            whatif_limits(settings.risk, {"leverage": 3}, inputs_for(settings, []))
        assert error.value.code == "invalid_request"


class TestStress:
    def test_a_zero_fall_reproduces_the_current_book(self, settings):
        inputs = inputs_for(settings, [open_trade(current=990_000.0)])
        result = stress(settings.risk, inputs, 0.0)
        assert result["stop_missed"]["open_pnl"] == pytest.approx(result["now"]["open_pnl"], abs=1.0)
        assert result["stop_fills"]["equity"] == pytest.approx(result["now"]["equity"], abs=1.0)

    def test_a_ten_percent_fall_without_the_stop_loses_ten_percent_of_value_plus_fees(self, settings):
        trade = open_trade(stake=300_000, rate=1_000_000.0, stop_pct=-3.0)
        result = stress(settings.risk, inputs_for(settings, [trade]), 10.0)
        position = position_of(trade)
        expected = position.amount * 900_000.0 * (1 - 0.002) - position.cost
        assert result["positions"][0]["pnl_stop_missed"] == pytest.approx(expected)
        assert result["stop_missed"]["equity_change_idr"] == pytest.approx(-29_940)

    def test_a_stop_that_fills_caps_the_loss_at_the_stop_price(self, settings):
        trade = open_trade(stake=300_000, rate=1_000_000.0, stop_pct=-3.0)
        row = stress(settings.risk, inputs_for(settings, [trade]), 10.0)["positions"][0]
        assert row["pnl_stop_fills"] == pytest.approx(position_of(trade).pnl_at(970_000.0))
        assert row["pnl_stop_fills"] > row["pnl_stop_missed"]

    def test_a_fall_smaller_than_the_stop_distance_is_the_same_with_or_without_the_stop(self, settings):
        row = stress(settings.risk, inputs_for(settings, [open_trade(stop_pct=-3.0)]), 1.0)["positions"][0]
        assert row["pnl_stop_fills"] == pytest.approx(row["pnl_stop_missed"])

    def test_the_stress_state_uses_the_engine_breach_rules(self, settings):
        trades = [open_trade(stake=1_500_000, stop_pct=-3.0)]
        result = stress(settings.risk, inputs_for(settings, trades), 10.0)
        assert "daily_loss" in result["stop_missed"]["breaches"]
        assert result["stop_missed"]["entries_allowed"] is False
        assert result["now"]["breaches"] == []

    def test_no_open_positions_leave_equity_unchanged(self, settings):
        result = stress(settings.risk, inputs_for(settings, [closed_trade(-100.0)]), 10.0)
        assert result["positions"] == []
        assert result["stop_missed"]["equity_change_idr"] == 0


class TestPortfolio:
    def test_more_than_three_configured_pairs_all_appear_with_zero_rows(self, example_raw):
        raw = copy.deepcopy(example_raw)
        raw["exchange"]["pairs"] = ["BTC/IDR", "ETH/IDR", "SOL/IDR", "DOGE/IDR", "XRP/IDR", "ADA/IDR"]
        raw["risk"]["max_open_trades"] = 6
        settings = Settings.model_validate(raw)
        inputs = inputs_for(
            settings, [open_trade("BTC/IDR", 1, stake=400_000), open_trade("XRP/IDR", 2, stake=200_000)]
        )
        view = portfolio(settings, inputs.assess(settings.risk), inputs.positions)
        assert view["pairs_configured"] == 6
        assert [row["pair"] for row in view["pairs"]][:2] == ["BTC/IDR", "XRP/IDR"]
        assert {row["pair"] for row in view["pairs"]} == set(raw["exchange"]["pairs"])
        assert view["slots_used"] == 2 and view["slots_max"] == 6
        assert view["exposure_idr"] == pytest.approx(600_000)
        assert view["cash_idr"] == pytest.approx(view["equity"] - 600_000)

    def test_a_pair_above_the_share_limit_is_flagged_and_others_are_not(self, settings):
        inputs = inputs_for(
            settings, [open_trade("BTC/IDR", 1, stake=1_200_000), open_trade("ETH/IDR", 2, stake=100_000)]
        )
        rows = {
            row["pair"]: row for row in portfolio(settings, inputs.assess(settings.risk), inputs.positions)["pairs"]
        }
        assert rows["BTC/IDR"]["over_limit"] is True
        assert rows["ETH/IDR"]["over_limit"] is False
        assert rows["SOL/IDR"]["open_trades"] == 0

    def test_a_position_in_a_pair_that_left_the_config_is_reported(self, settings):
        inputs = inputs_for(settings, [open_trade("DOGE/IDR", 3, stake=100_000)])
        view = portfolio(settings, inputs.assess(settings.risk), inputs.positions)
        assert view["pairs_not_in_config"] == ["DOGE/IDR"]
        assert any(row["pair"] == "DOGE/IDR" and row["open_trades"] == 1 for row in view["pairs"])


class TestExport:
    def test_csv_has_one_row_per_trade_and_the_documented_columns(self):
        text = trades_csv([closed_trade(-1000.0, trade_id=1), open_trade(trade_id=2)])
        lines = text.strip().split("\n")
        assert lines[0].startswith("trade_id,pair,is_open,enter_tag,exit_reason,open_date,close_date")
        assert len(lines) == 3
        assert lines[1].split(",")[0] == "1"
        assert "-1000.0" in lines[1]

    def test_spreadsheet_formulas_in_text_columns_are_neutralised(self):
        trade = closed_trade(10.0)
        trade["enter_tag"] = '=HYPERLINK("http://x")'
        trade["exit_reason"] = "+cmd"
        text = trades_csv([trade])
        assert "'=HYPERLINK" in text
        assert "'+cmd" in text
        assert ",=HYPERLINK" not in text

    def test_tax_sums_sell_value_and_applies_the_configured_rate_per_month(self):
        trades = [
            closed_trade(100.0, close_date="2026-10-02 01:00:00", close_rate=1_000_000.0, amount=0.5, trade_id=1),
            closed_trade(-50.0, close_date="2026-10-20 01:00:00", close_rate=2_000_000.0, amount=0.25, trade_id=2),
            closed_trade(10.0, close_date="2026-11-01 01:00:00", close_rate=1_000_000.0, amount=1.0, trade_id=3),
            open_trade(trade_id=4),
        ]
        summary = tax_summary(trades, 0.21)
        october = next(row for row in summary["months"] if row["month"] == "2026-10")
        assert october["trades"] == 2
        assert october["sell_value_idr"] == pytest.approx(1_000_000.0)
        assert october["pph22_final_idr"] == pytest.approx(2_100.0)
        assert october["realized_profit_idr"] == pytest.approx(50.0)
        assert summary["total"]["trades"] == 3
        assert summary["total"]["pph22_final_idr"] == pytest.approx(2_100.0 + 2_100.0)

    def test_year_filter_excludes_other_years(self):
        trades = [
            closed_trade(1.0, close_date="2025-12-31 23:00:00"),
            closed_trade(1.0, close_date="2026-01-01 00:30:00"),
        ]
        assert tax_summary(trades, 0.21, year=2026)["total"]["trades"] == 1

    def test_the_summary_states_its_basis_and_what_is_unverified(self):
        basis = tax_summary([], 0.21)["basis"]
        assert "PMK 50/2025" in basis["regulation"]
        assert "not tax advice" in basis["disclaimer"]
        assert any("PAKD" in item for item in basis["not_verified"])

    def test_closed_trades_without_a_close_rate_are_counted_as_skipped(self):
        trade = closed_trade(1.0)
        del trade["close_rate"]
        summary = tax_summary([trade], 0.21)
        assert summary["skipped_without_rate"] == 1
        assert summary["total"]["trades"] == 0


class TestTaxTimezone:
    def test_a_trade_after_17_utc_on_the_last_day_belongs_to_the_next_month_in_jakarta(self):
        trades = [closed_trade(1.0, close_date="2026-10-31 18:30:00", close_rate=1_000_000.0, amount=1.0)]
        assert [row["month"] for row in tax_summary(trades, 0.21, timezone="UTC")["months"]] == ["2026-10"]
        assert [row["month"] for row in tax_summary(trades, 0.21, timezone="Asia/Jakarta")["months"]] == ["2026-11"]

    def test_the_year_filter_uses_the_same_timezone(self):
        trades = [closed_trade(1.0, close_date="2026-12-31 18:30:00")]
        assert tax_summary(trades, 0.21, year=2026, timezone="UTC")["total"]["trades"] == 1
        assert tax_summary(trades, 0.21, year=2026, timezone="Asia/Jakarta")["total"]["trades"] == 0
        assert tax_summary(trades, 0.21, year=2027, timezone="Asia/Jakarta")["total"]["trades"] == 1
