import asyncio
import json
import random
import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_swarm.config import SwarmConfig, SwarmSettings, VoterSpec
from tb_swarm.errors import ConfigError, ProviderError
from tb_swarm.models import DecisionRequest, DecisionResponse
from tb_swarm.outcome import DecisionOutcome, VoterRecord, VoterStatus, settle
from tb_swarm.providers.base import DecisionProvider
from tb_swarm.providers.factory import AgentFactory, build_provider
from tb_swarm.redact import redact
from tb_swarm.shuffle import OptionOrder, identity_order, plan_order
from tb_swarm.validate import parse_answers

MAX_ERROR_CHARS = 300


class VoterLog:
    """Append-only JSONL record of every swarm decision, for the read-only analyst."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, request: DecisionRequest, outcome: DecisionOutcome) -> None:
        line = {
            "ts": datetime.now(UTC).isoformat(),
            "decision_id": outcome.decision_id,
            "status": outcome.status,
            "reason": outcome.reason,
            "required": outcome.required,
            "answered": outcome.answered,
            "request": request.model_dump(mode="json"),
            "aggregate": asdict(outcome.aggregate) if outcome.aggregate else None,
            "voters": [record.model_dump(mode="json") for record in outcome.voters],
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def _present_options(request: DecisionRequest) -> dict[str, list[str]]:
    shown: dict[str, list[str]] = {}
    for name, question in request.questions.items():
        criteria = getattr(question, "criteria", None)
        if isinstance(criteria, dict):
            shown[name] = list(criteria)
    return shown


class SwarmRunner:
    def __init__(
        self,
        settings: SwarmSettings,
        providers: Mapping[str, DecisionProvider],
        *,
        seed: str | int | None = None,
        log: VoterLog | None = None,
    ) -> None:
        voters = [voter for voter in settings.voters if voter.enabled]
        missing = [voter.id for voter in voters if voter.id not in providers]
        if missing:
            raise ConfigError(f"no provider instance for voters {missing}")
        self._settings = settings
        self._voters = voters
        self._providers = providers
        self._seed = seed
        self._log = log

    @classmethod
    def from_config(
        cls,
        config: SwarmConfig,
        env: Mapping[str, str],
        *,
        agent_factory: AgentFactory | None = None,
        seed: str | int | None = None,
        log: VoterLog | None = None,
    ) -> "SwarmRunner":
        providers = {
            voter.id: build_provider(voter, config.providers[voter.provider], env, agent_factory)
            for voter in config.swarm.voters
            if voter.enabled
        }
        if log is None and config.swarm.log_path:
            log = VoterLog(config.swarm.log_path)
        return cls(config.swarm, providers, seed=seed, log=log)

    def _rng(self, decision_id: str, voter: VoterSpec) -> random.Random:
        if self._seed is None:
            return random.Random()
        return random.Random(f"{self._seed}:{decision_id}:{voter.id}")

    async def _ask(self, voter: VoterSpec, request: DecisionRequest, decision_id: str) -> VoterRecord:
        shuffle = self._settings.shuffle_options and voter.variation == "option_order"
        rng = self._rng(decision_id, voter)
        order: OptionOrder = plan_order(request, rng) if shuffle else identity_order()
        presented = order.present(request, rng) if shuffle else request
        started = time.perf_counter()

        secrets = self._providers[voter.id].secrets()

        def record(status: VoterStatus, **extra: Any) -> VoterRecord:
            if extra.get("error"):
                extra["error"] = redact(extra["error"], secrets)[:MAX_ERROR_CHARS]
            return VoterRecord(
                voter_id=voter.id,
                status=status,
                latency_s=time.perf_counter() - started,
                presented_options=_present_options(presented),
                flipped_scores=sorted(order.flipped_scores),
                **extra,
            )

        try:
            response: DecisionResponse = await asyncio.wait_for(
                self._providers[voter.id].decide(presented), timeout=voter.timeout_s
            )
            restored = order.restore(request, response)
            answers = parse_answers(request, {name: a.model_dump() for name, a in restored.answers.items()})
        except TimeoutError:
            return record("timeout", error_kind="timeout", error=f"no answer within {voter.timeout_s}s")
        except ProviderError as exc:
            if exc.kind == "invalid":
                status: VoterStatus = "invalid"
            elif exc.kind == "timeout":
                status = "timeout"
            else:
                status = "failed"
            return record(status, error_kind=exc.kind, error=str(exc))
        except Exception as exc:
            return record("failed", error_kind="internal", error=f"{type(exc).__name__}: {exc}")
        return record("ok", model=restored.model, usage=restored.usage, answers=answers)

    async def decide(self, request: DecisionRequest, decision_id: str | None = None) -> DecisionOutcome:
        decision_id = decision_id or uuid.uuid4().hex
        required = self._settings.min_voters_answered
        if not self._settings.enabled:
            outcome = DecisionOutcome(decision_id, "skip", "swarm_disabled", required, 0, None)
        else:
            records = list(await asyncio.gather(*(self._ask(voter, request, decision_id) for voter in self._voters)))
            outcome = self._settle(request, decision_id, records, required)
        if self._log is not None:
            self._log.append(request, outcome)
        return outcome

    def _settle(
        self, request: DecisionRequest, decision_id: str, records: list[VoterRecord], required: int
    ) -> DecisionOutcome:
        weights = {voter.id: voter.weight for voter in self._voters}
        return settle(request, decision_id, records, weights, required, self._settings.max_spread)

    async def aclose(self) -> None:
        await asyncio.gather(*(provider.aclose() for provider in self._providers.values()))
