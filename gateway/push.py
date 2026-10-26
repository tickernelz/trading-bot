"""Web Push: per-language message catalogs, subscription routes and VAPID delivery."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from fastapi import Depends, FastAPI
from py_vapid import Vapid02
from py_vapid.utils import b64urlencode
from pydantic import BaseModel, ConfigDict, Field
from pywebpush import WebPushException, webpush

from gateway.feed import now_iso
from gateway.ledger import Ledger
from gateway.upstream import ApiError

logger = logging.getLogger("trading_bot.gateway")

KINDS = ("fill", "risk_breach", "kill_switch", "heartbeat_lost", "quorum_failed", "daily_summary")
Kind = Literal["fill", "risk_breach", "kill_switch", "heartbeat_lost", "quorum_failed", "daily_summary"]
URLS = {
    "fill": "/#activity",
    "risk_breach": "/#summary",
    "kill_switch": "/#summary",
    "heartbeat_lost": "/#system",
    "quorum_failed": "/#swarm",
    "daily_summary": "/#summary",
}
DEFAULT_LANG = "en"
LOCALES = Path(__file__).parent / "locales"
MAX_SUBSCRIPTIONS = 20
TTL_S = 600
SEND_TIMEOUT_S = 10.0
CONCURRENT_SENDS = 4
GONE = (404, 410)
SIGNED = frozenset({"pnl_pct"})
Base64Url = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+={0,2}$")]


def _check_catalog(lang: str, catalog: Mapping[str, Any], base: Mapping[str, Any]) -> None:
    if set(catalog) != {"number", "words", "kinds"}:
        raise ValueError(f"locale {lang}: expected number, words and kinds")
    if set(catalog["number"]) != {"group", "decimal"}:
        raise ValueError(f"locale {lang}: number needs group and decimal")
    if set(catalog["words"]) != set(base["words"]):
        raise ValueError(f"locale {lang}: words differ from {DEFAULT_LANG}")
    if set(catalog["kinds"]) != set(KINDS):
        raise ValueError(f"locale {lang}: kinds must be exactly {', '.join(KINDS)}")
    for kind, entry in catalog["kinds"].items():
        if set(entry) != {"title", "body"} or not all(isinstance(text, str) and text for text in entry.values()):
            raise ValueError(f"locale {lang}: {kind} needs a title and a body")


def load_catalogs(directory: Path = LOCALES) -> dict[str, dict[str, Any]]:
    catalogs = {file.stem: json.loads(file.read_text(encoding="utf-8")) for file in sorted(directory.glob("*.json"))}
    if DEFAULT_LANG not in catalogs:
        raise ValueError(f"locale {DEFAULT_LANG} is missing from {directory}")
    for lang, catalog in catalogs.items():
        _check_catalog(lang, catalog, catalogs[DEFAULT_LANG])
    return catalogs


CATALOGS = load_catalogs()


def resolve_lang(code: str | None, catalogs: Mapping[str, Any] = CATALOGS) -> str:
    """The catalog language for a client language code; an unknown or empty code gives the default."""
    if not code:
        return DEFAULT_LANG
    normal = code.strip().lower().replace("_", "-")
    if normal in catalogs:
        return normal
    primary = normal.split("-", 1)[0]
    return primary if primary in catalogs else DEFAULT_LANG


def format_number(value: float, style: Mapping[str, str], *, signed: bool = False) -> str:
    decimals = 0 if isinstance(value, int) or abs(value) >= 1000 else 2
    text = (
        f"{abs(value):,.{decimals}f}".replace(",", "\x00")
        .replace(".", style["decimal"])
        .replace("\x00", style["group"])
    )
    if value < 0:
        return "-" + text
    return "+" + text if signed and value > 0 else text


def render(
    kind: str, params: Mapping[str, Any], lang: str | None, catalogs: Mapping[str, Any] = CATALOGS
) -> dict[str, str]:
    code = resolve_lang(lang, catalogs)
    catalog = catalogs[code]
    values: dict[str, str] = {}
    for name, value in params.items():
        if name in ("side", "metric"):
            values[name] = catalog["words"][value]
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            values[name] = str(value)
        else:
            values[name] = format_number(value, catalog["number"], signed=name in SIGNED)
    entry = catalog["kinds"][kind]
    return {"title": entry["title"].format_map(values), "body": entry["body"].format_map(values), "lang": code}


def public_host_only(endpoint: str) -> None:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise ApiError(400, "invalid_request", "push endpoint must be an https URL without credentials")
    if host == "localhost" or host.endswith(".localhost"):
        raise ApiError(400, "invalid_request", "push endpoint must not point at this machine")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ApiError(400, "invalid_request", "push endpoint must not be a private or loopback address")


class Courier:
    """Holds the VAPID key pair and delivers one encrypted payload to one subscription."""

    def __init__(self, key_path: Path, subject: str) -> None:
        self.subject = subject
        if key_path.exists():
            self._vapid = Vapid02.from_file(str(key_path))
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            self._vapid = Vapid02()
            self._vapid.generate_keys()
            self._vapid.save_key(str(key_path))
            os.chmod(key_path, 0o600)
        raw = self._vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self.public_key = b64urlencode(raw)

    def send(self, subscription: dict[str, Any], payload: str, urgency: str) -> None:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=self._vapid,
            vapid_claims={"sub": self.subject},
            ttl=TTL_S,
            headers={"Urgency": urgency},
            timeout=SEND_TIMEOUT_S,
        )


class Keys(BaseModel):
    model_config = ConfigDict(extra="ignore")
    p256dh: Base64Url
    auth: Base64Url


class PushSubscription(BaseModel):
    model_config = ConfigDict(extra="ignore")
    endpoint: Annotated[str, Field(min_length=1, max_length=2048)]
    keys: Keys


class Subscribe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription: PushSubscription
    kinds: Annotated[list[Kind], Field(max_length=len(KINDS))] = list(KINDS)
    lang: Annotated[str, Field(max_length=35)] | None = None


class Unsubscribe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: Annotated[str, Field(min_length=1, max_length=2048)]


class PushDesk:
    def __init__(self, ledger: Ledger, courier: Courier, *, allow_local_endpoints: bool = False) -> None:
        self.ledger = ledger
        self.courier = courier
        self.allow_local_endpoints = allow_local_endpoints
        self._slots = asyncio.Semaphore(CONCURRENT_SENDS)

    @property
    def public_key(self) -> str:
        return self.courier.public_key

    def subscribe(self, body: Subscribe) -> dict[str, Any]:
        if not self.allow_local_endpoints:
            public_host_only(body.subscription.endpoint)
        lang = resolve_lang(body.lang)
        kinds = [kind for kind in KINDS if kind in body.kinds]
        if not self.ledger.save_subscription(
            body.subscription.endpoint,
            body.subscription.keys.p256dh,
            body.subscription.keys.auth,
            kinds,
            lang,
            MAX_SUBSCRIPTIONS,
        ):
            raise ApiError(409, "push_limit", f"at most {MAX_SUBSCRIPTIONS} push subscriptions are kept")
        return {"endpoint": body.subscription.endpoint, "kinds": kinds, "lang": lang}

    def unsubscribe(self, endpoint: str) -> bool:
        return self.ledger.delete_subscription(endpoint)

    async def notify(self, kind: str, params: Mapping[str, Any]) -> dict[str, int]:
        subscriptions = self.ledger.push_subscriptions(kind)
        texts = {lang: render(kind, params, lang) for lang in {item["lang"] for item in subscriptions}}
        urgency = "normal" if kind == "daily_summary" else "high"
        results = await asyncio.gather(
            *(self._deliver(item, kind, texts[item["lang"]], urgency) for item in subscriptions)
        )
        return {"sent": results.count(True), "failed": results.count(False)}

    async def _deliver(self, item: dict[str, Any], kind: str, text: dict[str, str], urgency: str) -> bool:
        payload = json.dumps(
            {"kind": kind, **text, "url": URLS[kind], "ts": now_iso(), "id": os.urandom(4).hex()}, ensure_ascii=False
        )
        info = {"endpoint": item["endpoint"], "keys": {"p256dh": item["p256dh"], "auth": item["auth"]}}
        async with self._slots:
            try:
                await asyncio.to_thread(self.courier.send, info, payload, urgency)
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in GONE:
                    self.ledger.delete_subscription(item["endpoint"])
                logger.warning("push to %s failed: %s", urlsplit(item["endpoint"]).hostname, status or exc)
                return False
            except Exception as exc:
                logger.warning("push to %s failed: %r", urlsplit(item["endpoint"]).hostname, exc)
                return False
        return True


def fill_params(side: str, data: Mapping[str, Any]) -> dict[str, Any] | None:
    pair = data.get("pair")
    rate = data.get("close_rate" if side == "sell" else "open_rate")
    amount = data.get("stake_amount")
    if not isinstance(pair, str) or not all(isinstance(item, (int, float)) for item in (rate, amount)):
        return None
    return {"side": side, "pair": pair, "amount": amount, "rate": rate}


SAMPLES: dict[str, dict[str, Any]] = {"daily_summary": {"bot": "Bot A", "pnl_pct": -0.31, "closed": 2}}


def install_push(app: FastAPI, desk: PushDesk, reader: Callable[..., Any]) -> None:
    @app.get("/gw/v1/push/key", dependencies=[Depends(reader)])
    async def key() -> dict[str, str]:
        return {"public_key": desk.public_key}

    @app.post("/gw/v1/push/subscriptions", dependencies=[Depends(reader)], status_code=201)
    async def subscribe(body: Subscribe) -> dict[str, Any]:
        return desk.subscribe(body)

    @app.delete("/gw/v1/push/subscriptions", dependencies=[Depends(reader)])
    async def unsubscribe(body: Unsubscribe) -> dict[str, bool]:
        return {"removed": desk.unsubscribe(body.endpoint)}

    @app.post("/gw/v1/push/test", dependencies=[Depends(reader)])
    async def test() -> dict[str, int]:
        return await desk.notify("daily_summary", SAMPLES["daily_summary"])
