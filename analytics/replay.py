"""Replay recorded voter answers under another quorum or spread limit, with no new LLM call."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from tb_swarm.aggregate import ChoiceResult
from tb_swarm.outcome import DecisionOutcome, settle

from analytics.source import RecordedDecision

VERDICTS = ("izinkan", "kecilkan", "lewati")
TAKE = ("izinkan", "kecilkan")
CHANGED_LIMIT = 50


def verdict_of(outcome: DecisionOutcome) -> str:
    """Name the swarm verdict: the winning option, or lewati when the outcome is a skip."""
    if not outcome.proceed or outcome.aggregate is None:
        return "lewati"
    result = outcome.aggregate.questions.get("verdict")
    if not isinstance(result, ChoiceResult):
        return "lewati"
    return result.winner


def replayable(decision: RecordedDecision) -> bool:
    return bool(decision.voters) and "verdict" in decision.request.questions


def replay_decision(
    decision: RecordedDecision,
    weights: Mapping[str, float],
    required: int,
    max_spread: float | None,
    exclude: frozenset[str],
) -> DecisionOutcome:
    records = [record for record in decision.voters if record.voter_id not in exclude]
    known = {record.voter_id: weights.get(record.voter_id, 1.0) for record in records}
    return settle(decision.request, decision.decision_id, records, known, required, max_spread)


def side(verdict: str | None) -> str:
    return "take" if verdict in TAKE else "skip"


def whatif_replay(
    decisions: tuple[RecordedDecision, ...],
    weights: Mapping[str, float],
    required: int,
    max_spread: float | None,
    exclude: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Re-decide each recorded decision and report how verdicts, and the trades behind them, would have moved."""
    recorded = Counter()
    replayed = Counter()
    transitions = Counter()
    changed: list[dict[str, Any]] = []
    groups: dict[str, dict[str, float]] = {}
    not_replayable = 0
    unknown_voters: set[str] = set()
    for decision in decisions:
        if not replayable(decision):
            not_replayable += 1
            continue
        unknown_voters.update(record.voter_id for record in decision.voters if record.voter_id not in weights)
        outcome = replay_decision(decision, weights, required, max_spread, exclude)
        before = decision.verdict or "lewati"
        after = verdict_of(outcome)
        recorded[before] += 1
        replayed[after] += 1
        if before != after:
            transitions[f"{before}->{after}"] += 1
            if len(changed) < CHANGED_LIMIT:
                changed.append(
                    {
                        "decision_id": decision.decision_id,
                        "pair": decision.pair,
                        "settled_at": decision.settled_at,
                        "recorded": {"verdict": before, "status": decision.status, "reason": decision.reason},
                        "replayed": {"verdict": after, "status": outcome.status, "reason": outcome.reason},
                    }
                )
        profit = decision.closed_profit
        if profit is not None:
            group = groups.setdefault(f"{side(before)}->{side(after)}", {"trades": 0, "profit_abs_idr": 0.0})
            group["trades"] += 1
            group["profit_abs_idr"] += profit
    return {
        "decisions": len(decisions),
        "replayed": sum(replayed.values()),
        "not_replayable": not_replayable,
        "recorded_verdicts": {name: recorded.get(name, 0) for name in VERDICTS},
        "replayed_verdicts": {name: replayed.get(name, 0) for name in VERDICTS},
        "transitions": dict(sorted(transitions.items())),
        "changed": changed,
        "changed_total": sum(transitions.values()),
        "trade_groups": dict(sorted(groups.items())),
        "unknown_voters": sorted(unknown_voters),
        "params": {
            "min_voters_answered": required,
            "max_spread": max_spread,
            "exclude_voters": sorted(exclude),
        },
        "note": "Angka trade_groups adalah data trade yang sudah tertutup, bukan kesimpulan untung atau rugi.",
    }
