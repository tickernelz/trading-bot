"""Measure the gateway: drive forced fills on a test bot, or hold simulated PWA clients open."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time

import httpx
import websockets

TOPICS = [
    "entry",
    "entry_fill",
    "exit",
    "exit_fill",
    "status",
    "warning",
    "whitelist",
    "gw.risk",
    "gw.risk_denied",
    "gw.decision",
    "gw.candles",
]
REFRESH = [
    "/gw/v1/health",
    "/gw/v1/overview",
    "/gw/v1/risk",
    "/gw/v1/trades/open",
    "/gw/v1/trades?limit=50",
    "/gw/v1/equity?window=day",
    "/gw/v1/equity?window=7d&bots=A,B",
    "/gw/v1/decisions?limit=20",
    "/gw/v1/sysinfo",
    "/gw/v1/logs?limit=30",
]


async def login(gateway: str) -> str:
    async with httpx.AsyncClient(base_url=gateway) as client:
        response = await client.post("/gw/v1/session", json={"password": os.environ["GW_PASSWORD"]})
        response.raise_for_status()
        return response.json()["token"]


async def fills(args: argparse.Namespace) -> dict:
    token = await login(args.gateway)
    auth = (os.environ["FT_API_USERNAME"], os.environ["FT_API_PASSWORD"])
    seen: list[dict] = []
    ws_url = args.gateway.replace("http://", "ws://") + f"/gw/v1/events?token={token}"
    async with (
        websockets.connect(ws_url) as feed,
        httpx.AsyncClient(base_url=args.bot + "/api/v1", auth=auth, timeout=10) as bot,
    ):
        await feed.send(json.dumps({"type": "subscribe", "topics": ["entry_fill", "exit_fill"], "candles": []}))

        async def listen() -> None:
            async for raw in feed:
                event = json.loads(raw)
                if event["type"] in ("entry_fill", "exit_fill"):
                    seen.append(
                        {
                            "type": event["type"],
                            "trade_id": event["data"].get("trade_id"),
                            "client_ms": int(time.time() * 1000),
                        }
                    )

        listener = asyncio.create_task(listen())
        for cycle in range(args.cycles):
            entered = await bot.post("/forceenter", json={"pair": args.pair, "side": "long"})
            entered.raise_for_status()
            trade_id = entered.json()["trade_id"]
            await wait_for(seen, "entry_fill", trade_id, 120)
            await asyncio.sleep(args.hold)
            exited = await bot.post("/forceexit", json={"tradeid": str(trade_id), "ordertype": "market"})
            exited.raise_for_status()
            await wait_for(seen, "exit_fill", trade_id, 120)
            print(f"cycle {cycle + 1}: trade {trade_id} entry and exit fills reached the gateway feed", flush=True)
        listener.cancel()
    async with httpx.AsyncClient(base_url=args.gateway, headers={"Authorization": f"Bearer {token}"}) as client:
        metrics = (await client.get("/gw/v1/metrics")).json()
    return {"cycles": args.cycles, "pair": args.pair, "feed_seen": seen, "metrics": metrics}


async def wait_for(seen: list[dict], kind: str, trade_id: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(item["type"] == kind and item["trade_id"] == trade_id for item in seen):
            return
        await asyncio.sleep(0.2)
    raise TimeoutError(f"{kind} for trade {trade_id} did not reach the feed within {timeout}s")


async def pwa_client(gateway: str, token: str, pairs: list[str], until: float, stats: dict) -> None:
    ws_url = gateway.replace("http://", "ws://") + f"/gw/v1/events?token={token}"
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        websockets.connect(ws_url, max_size=2**24) as feed,
        httpx.AsyncClient(base_url=gateway, headers=headers, timeout=15) as client,
    ):
        await feed.send(
            json.dumps(
                {
                    "type": "subscribe",
                    "topics": TOPICS,
                    "candles": [{"pair": pair, "timeframe": "1h", "limit": 300} for pair in pairs],
                }
            )
        )

        async def drain() -> None:
            async for _ in feed:
                stats["events"] += 1

        reader = asyncio.create_task(drain())
        while time.monotonic() < until:
            for path in REFRESH:
                started = time.perf_counter()
                response = await client.get(path)
                stats["latencies"].append((time.perf_counter() - started) * 1000)
                stats["status"][response.status_code] = stats["status"].get(response.status_code, 0) + 1
            await asyncio.sleep(30)
        reader.cancel()


async def clients(args: argparse.Namespace) -> dict:
    token = await login(args.gateway)
    stats: dict = {"events": 0, "latencies": [], "status": {}}
    until = time.monotonic() + args.seconds
    await asyncio.gather(*(pwa_client(args.gateway, token, args.pairs, until, stats) for _ in range(args.count)))
    latencies = sorted(stats["latencies"])
    async with httpx.AsyncClient(base_url=args.gateway, headers={"Authorization": f"Bearer {token}"}) as client:
        metrics = (await client.get("/gw/v1/metrics")).json()
    return {
        "clients": args.count,
        "seconds": args.seconds,
        "requests": len(latencies),
        "status": stats["status"],
        "events": stats["events"],
        "request_ms_p50": round(statistics.median(latencies), 1) if latencies else None,
        "request_ms_p95": round(latencies[int(0.95 * len(latencies))], 1) if latencies else None,
        "request_ms": [round(value, 2) for value in stats["latencies"]],
        "metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:8090")
    parser.add_argument("--out", help="also write the JSON result to this file")
    sub = parser.add_subparsers(dest="command", required=True)
    fill = sub.add_parser("fills")
    fill.add_argument("--bot", default="http://127.0.0.1:8082")
    fill.add_argument("--pair", default="BTC/IDR")
    fill.add_argument("--cycles", type=int, default=8)
    fill.add_argument("--hold", type=float, default=10.0)
    load = sub.add_parser("clients")
    load.add_argument("--count", type=int, default=5)
    load.add_argument("--seconds", type=int, default=600)
    load.add_argument("--pairs", nargs="+", default=["BTC/IDR", "ETH/IDR", "SOL/IDR"])
    args = parser.parse_args()
    result = asyncio.run(fills(args) if args.command == "fills" else clients(args))
    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")


if __name__ == "__main__":
    main()
