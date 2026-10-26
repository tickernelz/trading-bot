"""Voter calibration and accuracy against closed-trade outcomes, and the drift rule that retires a voter."""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from tb_swarm.models import ChoiceAnswer

from analytics.replay import TAKE
from analytics.source import RecordedDecision
from engine.settings import ConfigError, Scoreboard, Settings


@dataclass
class VoterStats:
    voter_id: str
    calls: int = 0
    ok_calls: int = 0
    choice_only: int = 0
    samples: list[tuple[float, bool]] = field(default_factory=list)


def take_probability(answer: ChoiceAnswer) -> float:
    if answer.probabilities:
        return min(1.0, max(0.0, sum(answer.probabilities.get(option, 0.0) for option in TAKE)))
    return 1.0 if answer.choice in TAKE else 0.0


def collect(decisions: tuple[RecordedDecision, ...]) -> dict[str, VoterStats]:
    stats: dict[str, VoterStats] = {}
    for decision in decisions:
        profit = decision.closed_profit
        for record in decision.voters:
            entry = stats.setdefault(record.voter_id, VoterStats(record.voter_id))
            entry.calls += 1
            if record.status != "ok":
                continue
            entry.ok_calls += 1
            answer = (record.answers or {}).get("verdict")
            if profit is None or not isinstance(answer, ChoiceAnswer):
                continue
            if not answer.probabilities:
                entry.choice_only += 1
            entry.samples.append((take_probability(answer), profit > 0))
    return stats


def calibration_bins(samples: list[tuple[float, bool]], bins: int) -> list[dict[str, Any]]:
    rows = []
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        inside = [(p, y) for p, y in samples if low <= p < high or (index == bins - 1 and p == 1.0)]
        rows.append(
            {
                "low": low,
                "high": high,
                "n": len(inside),
                "mean_predicted": sum(p for p, _ in inside) / len(inside) if inside else None,
                "observed": sum(1 for _, y in inside if y) / len(inside) if inside else None,
            }
        )
    return rows


def voter_row(stats: VoterStats, config: Scoreboard) -> dict[str, Any]:
    samples = stats.samples
    n = len(samples)
    row: dict[str, Any] = {
        "voter_id": stats.voter_id,
        "calls": stats.calls,
        "answered": stats.ok_calls,
        "answer_rate": stats.ok_calls / stats.calls if stats.calls else None,
        "samples": n,
        "kind": "choice_only" if stats.choice_only else "probabilistic",
        "status": "insufficient",
        "reasons": [],
        "shortfall": None,
        "accuracy": None,
        "base_rate": None,
        "majority_accuracy": None,
        "brier": None,
        "brier_baseline": None,
        "ece": None,
        "bins": None,
    }
    if n == 0:
        return row
    base = sum(1 for _, y in samples if y) / n
    accuracy = sum(1 for p, y in samples if (p >= 0.5) == y) / n
    majority = max(base, 1 - base)
    row.update({"accuracy": accuracy, "base_rate": base, "majority_accuracy": majority})
    reasons = []
    if stats.choice_only:
        row["shortfall"] = majority - accuracy
        drifting = accuracy < majority - config.accuracy_margin
        if drifting:
            reasons.append(
                f"akurasi {accuracy:.3f} di bawah penebak kelas mayoritas {majority:.3f} - {config.accuracy_margin}"
            )
    else:
        brier = sum((p - (1.0 if y else 0.0)) ** 2 for p, y in samples) / n
        baseline = base * (1 - base)
        bins = calibration_bins(samples, config.bins)
        ece = sum(item["n"] / n * abs(item["mean_predicted"] - item["observed"]) for item in bins if item["n"])
        row.update({"brier": brier, "brier_baseline": baseline, "ece": ece, "bins": bins})
        row["shortfall"] = brier - baseline
        if ece > config.max_ece:
            reasons.append(f"ece {ece:.3f} above the limit {config.max_ece}")
        if brier > baseline + config.brier_margin:
            reasons.append(f"brier {brier:.3f} worse than the constant guesser {baseline:.3f} + {config.brier_margin}")
    if n < config.min_samples:
        return row
    row["status"] = "drifting" if reasons else "ok"
    row["reasons"] = reasons
    return row


def scoreboard(decisions: tuple[RecordedDecision, ...], config: Scoreboard) -> dict[str, Any]:
    """Score every voter on closed trades: accuracy of take versus skip, Brier score and calibration error."""
    stats = collect(decisions)
    rows = [voter_row(entry, config) for entry in stats.values()]
    return {
        "decisions": len(decisions),
        "with_outcome": sum(1 for decision in decisions if decision.closed_profit is not None),
        "config": config.model_dump(),
        "voters": sorted(rows, key=lambda row: row["voter_id"]),
        "definition": {
            "take": list(TAKE),
            "outcome": "closed trade with profit_abs > 0",
            "probability": "sum of the allow and reduce probabilities; used only when every voter answer carries probabilities",
            "kind": "probabilistic when every answer carries probabilities, choice_only when any answer has none",
            "drifting": "n >= min_samples and: probabilistic: ece > max_ece or brier > constant-guesser brier + brier_margin; choice_only: accuracy < majority-class guesser accuracy - accuracy_margin",
        },
        "note": "The scoreboard is calibration data, not a conclusion about profit or loss.",
    }


def plan_disables(board: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Choose which drifting voters to turn off without dropping below the swarm quorum."""
    config = settings.analytics.scoreboard
    enabled = {voter.id for voter in settings.swarm.voters if voter.enabled}
    drifting = [row for row in board["voters"] if row["status"] == "drifting" and row["voter_id"] in enabled]
    drifting.sort(key=lambda row: row["shortfall"], reverse=True)
    spare = len(enabled) - settings.swarm.min_voters_answered
    chosen = [row["voter_id"] for row in drifting[: max(0, spare)]]
    kept = [row["voter_id"] for row in drifting[max(0, spare) :]]
    return {
        "enabled_voters": len(enabled),
        "quorum": settings.swarm.min_voters_answered,
        "auto_disable": config.auto_disable,
        "disable": chosen if config.auto_disable else [],
        "recommended": chosen,
        "kept_for_quorum": kept,
    }


CONFIG_LOCK = threading.Lock()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_disables(config_path: str | os.PathLike[str], voter_ids: list[str]) -> list[str]:
    """Set enabled false for the given voters in the config file; the result must still validate."""
    if not voter_ids:
        return []
    path = Path(config_path)
    with CONFIG_LOCK:
        before = file_digest(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        changed = []
        for voter in raw["swarm"]["voters"]:
            if voter["id"] in voter_ids and voter.get("enabled"):
                voter["enabled"] = False
                changed.append(voter["id"])
        if not changed:
            return []
        try:
            Settings.model_validate(raw)
        except ValueError as exc:
            raise ConfigError(f"{path}: disabling {changed} gives an invalid config: {exc}") from exc
        handle, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                yaml.safe_dump(raw, stream, sort_keys=False, allow_unicode=True)
            os.chmod(temp, path.stat().st_mode & 0o777)
            if file_digest(path) != before:
                raise ConfigError(f"{path}: changed while the voter switch was being prepared; nothing written")
            os.replace(temp, path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
    return changed
