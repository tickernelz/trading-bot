from __future__ import annotations

import copy

import pytest

from engine.launch import freqtrade_config
from engine.settings import ConfigError, Settings, load_settings

PAIRS = ["BTC/IDR", "ETH/IDR", "SOL/IDR", "DOGE/IDR", "XRP/IDR", "ADA/IDR", "TRX/IDR", "BNB/IDR"]


class TestAnalyticsSettings:
    def test_a_config_without_an_analytics_section_gets_the_documented_defaults(self, example_raw):
        raw = copy.deepcopy(example_raw)
        raw.pop("analytics", None)
        analytics = Settings.model_validate(raw).analytics
        assert analytics.scoreboard.auto_disable is True
        assert analytics.scoreboard.min_samples == 30
        assert analytics.scoreboard.accuracy_margin == 0.05
        assert analytics.stress.drop_pct == 10.0
        assert analytics.tax.pph22_final_pct == 0.21
        assert analytics.portfolio.max_pair_share_pct == 50.0

    def test_auto_disable_can_be_switched_off_in_the_config(self, example_raw):
        raw = copy.deepcopy(example_raw)
        raw["analytics"] = {"scoreboard": {"auto_disable": False}}
        assert Settings.model_validate(raw).analytics.scoreboard.auto_disable is False

    @pytest.mark.parametrize(
        "section",
        [
            {"scoreboard": {"min_samples": 2}},
            {"scoreboard": {"max_ece": 1.5}},
            {"scoreboard": {"bins": 1}},
            {"scoreboard": {"accuracy_margin": 0.6}},
            {"scoreboard": {"interval_s": 5}},
            {"stress": {"drop_pct": 0}},
            {"stress": {"drop_pct": 101}},
            {"tax": {"pph22_final_pct": -1}},
            {"portfolio": {"max_pair_share_pct": 0}},
            {"scoreboard": {"unknown": 1}},
            {"unknown": {}},
        ],
    )
    def test_out_of_range_values_and_unknown_keys_are_refused(self, example_raw, section):
        raw = copy.deepcopy(example_raw)
        raw["analytics"] = section
        with pytest.raises(ValueError):
            Settings.model_validate(raw)

    def test_the_example_config_loads_through_the_file_loader(self, tmp_path, example_raw, write_config):
        assert load_settings(write_config(example_raw)).analytics.scoreboard.enabled is True

    def test_a_bad_analytics_value_stops_the_loader_with_a_config_error(self, example_raw, write_config):
        raw = copy.deepcopy(example_raw)
        raw["analytics"] = {"stress": {"drop_pct": -5}}
        with pytest.raises(ConfigError):
            load_settings(write_config(raw))


class TestManyPairs:
    def test_more_than_three_pairs_are_accepted_and_all_reach_the_freqtrade_whitelist(self, example_raw):
        raw = copy.deepcopy(example_raw)
        raw["exchange"]["pairs"] = PAIRS
        raw["risk"]["max_open_trades"] = 8
        config = freqtrade_config(Settings.model_validate(raw))
        assert config["exchange"]["pair_whitelist"] == PAIRS
        assert config["max_open_trades"] == 8

    def test_a_non_idr_pair_is_still_refused_with_many_pairs(self, example_raw):
        raw = copy.deepcopy(example_raw)
        raw["exchange"]["pairs"] = [*PAIRS, "BTC/USDT"]
        with pytest.raises(ValueError, match="IDR"):
            Settings.model_validate(raw)
