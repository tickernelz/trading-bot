from __future__ import annotations

import pytest

from engine.settings import ConfigError, load_settings
from tests.conftest import EXAMPLE


def test_example_config_is_valid():
    settings = load_settings(EXAMPLE)
    assert settings.mode == "dry_run"
    assert settings.risk.max_daily_loss_pct == 1.0
    assert settings.risk.max_total_drawdown_pct == 10.0
    assert settings.risk.risk_per_trade_pct == 0.5
    assert settings.risk.on_breach == "stop_new_entries"
    assert settings.compute.max_cost_idr_per_day is False
    assert settings.data.social is False
    assert settings.bot_id == "A"
    assert settings.shadow.url == "http://127.0.0.1:8091"
    assert {"systemone", "openai-decisions"} <= {provider.type for provider in settings.providers}
    assert len({voter.provider for voter in settings.swarm.voters if voter.enabled}) == 7


def test_rules_only_bot_needs_no_shadow_service(example_raw, write_config):
    example_raw["swarm"]["enabled"] = False
    del example_raw["shadow"]
    assert load_settings(write_config(example_raw)).shadow is None


def _mutations():
    def unknown_key(raw):
        raw["risk"]["max_daily_loss"] = 1.0

    def live_mode(raw):
        raw["mode"] = "live"

    def daily_above_total(raw):
        raw["risk"]["max_daily_loss_pct"] = 12.0

    def risk_above_daily(raw):
        raw["risk"]["risk_per_trade_pct"] = 2.0

    def negative_limit(raw):
        raw["risk"]["max_daily_loss_pct"] = -1.0

    def unsupported_breach_action(raw):
        raw["risk"]["on_breach"] = "ignore"

    def leverage_enabled(raw):
        raw["risk"]["leverage"] = 3

    def non_idr_pair(raw):
        raw["exchange"]["pairs"] = ["BTC/USDT"]

    def duplicate_pair(raw):
        raw["exchange"]["pairs"] = ["BTC/IDR", "BTC/IDR"]

    def api_listens_beyond_loopback(raw):
        raw["api"]["listen"] = "0.0.0.0"

    def missing_fee(raw):
        del raw["exchange"]["fee_pct"]

    def unknown_timezone(raw):
        raw["risk"]["daily_reset_timezone"] = "Mars/Olympus"

    def voter_unknown_provider(raw):
        raw["swarm"]["voters"][0]["provider"] = "missing"

    def voter_unlisted_model(raw):
        raw["swarm"]["voters"][0]["model"] = "other-model"

    def quorum_above_voters(raw):
        raw["swarm"]["min_voters_answered"] = 8

    def analyst_unknown_provider(raw):
        raw["llm"]["analyst_model"] = "missing:deepseek-v4.1-flash-1017"

    def missing_section(raw):
        del raw["risk"]

    def wrong_type(raw):
        raw["capital"]["initial_idr"] = "two million"

    def veto_not_implemented(raw):
        raw["swarm"]["mode"] = "veto"

    def shadow_without_service(raw):
        del raw["shadow"]

    def shadow_beyond_loopback(raw):
        raw["shadow"]["listen"] = "0.0.0.0"

    def lowercase_bot_id(raw):
        raw["bot_id"] = "b"

    def analyst_on_decision_provider(raw):
        raw["llm"]["analyst_model"] = "experientiallabs-systemone:jev-latest"

    return [
        veto_not_implemented,
        shadow_without_service,
        shadow_beyond_loopback,
        lowercase_bot_id,
        analyst_on_decision_provider,
        unknown_key,
        live_mode,
        daily_above_total,
        risk_above_daily,
        negative_limit,
        unsupported_breach_action,
        leverage_enabled,
        non_idr_pair,
        duplicate_pair,
        missing_fee,
        api_listens_beyond_loopback,
        unknown_timezone,
        voter_unknown_provider,
        voter_unlisted_model,
        quorum_above_voters,
        analyst_unknown_provider,
        missing_section,
        wrong_type,
    ]


@pytest.mark.parametrize("mutate", _mutations(), ids=lambda fn: fn.__name__)
def test_invalid_config_is_rejected(example_raw, write_config, mutate):
    mutate(example_raw)
    with pytest.raises(ConfigError):
        load_settings(write_config(example_raw))


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="No such file"):
        load_settings(tmp_path / "absent.yaml")


def test_non_mapping_is_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_settings(path)
