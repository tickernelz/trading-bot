import argparse
import json
import os
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-2k"
MODEL_ID = "NeoQuasar/Kronos-mini"
MAX_CONTEXT = 2048
COLUMNS = ["open", "high", "low", "close", "volume", "amount"]


def synthetic_candles(count: int, seed: int) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    rng = np.random.default_rng(seed)
    closes = 1_000_000_000 * np.exp(np.cumsum(rng.normal(0, 0.004, count)))
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.002, count)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.002, count)))
    volume = rng.lognormal(3.0, 0.5, count)
    stamps = pd.date_range("2026-01-01", periods=count, freq="1h")
    frame = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume})
    frame["amount"] = frame["volume"] * frame[["open", "high", "low", "close"]].mean(axis=1)
    return frame, stamps


class PathCapture:
    """Stands in for numpy inside kronos.py to capture the per-path array before it is averaged."""

    def __init__(self) -> None:
        self.paths: np.ndarray | None = None

    def __getattr__(self, name: str):
        return getattr(np, name)

    def mean(self, array, axis=None, **kwargs):
        if axis == 1 and getattr(array, "ndim", 0) == 4:
            self.paths = np.array(array)
        return np.mean(array, axis=axis, **kwargs)


def load(kronos_src: str):
    sys.path.insert(0, kronos_src)
    from model import Kronos, KronosPredictor, KronosTokenizer
    from model import kronos as kronos_module

    started = time.perf_counter()
    tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID)
    model = Kronos.from_pretrained(MODEL_ID)
    tokenizer.eval()
    model.eval()
    load_s = time.perf_counter() - started
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=MAX_CONTEXT)
    return predictor, kronos_module, load_s, model, tokenizer


def per_path_summary(capture: PathCapture, history: pd.DataFrame, averaged: pd.DataFrame, pred_len: int) -> dict | None:
    if capture.paths is None:
        return None
    columns = history[COLUMNS].values.astype(np.float32)
    mean, std = columns.mean(axis=0), columns.std(axis=0)
    paths = capture.paths[0, :, -pred_len:, :] * (std + 1e-5) + mean
    recomputed = paths.mean(axis=0)[:, 3]
    returns = (paths[:, -1, 3] / float(history["close"].iloc[-1]) - 1) * 100
    return {
        "shape": list(capture.paths.shape),
        "mean_matches_predict_close": bool(np.allclose(recomputed, averaged["close"].to_numpy(), rtol=1e-4)),
        "paths_close_return_pct": {
            "median": round(float(np.median(returns)), 4),
            "mean": round(float(returns.mean()), 4),
            "p10": round(float(np.percentile(returns, 10)), 4),
            "p90": round(float(np.percentile(returns, 90)), 4),
        },
    }


def run_config(args: argparse.Namespace) -> dict:
    torch.set_num_threads(args.threads)
    predictor, kronos_module, load_s, model, tokenizer = load(args.kronos_src)
    frame, stamps = synthetic_candles(args.lookback + args.pred_len, seed=7)
    history = frame.iloc[: args.lookback]
    x_stamps = pd.Series(stamps[: args.lookback])
    y_stamps = pd.Series(stamps[args.lookback :])

    def forecast(sample_count: int) -> pd.DataFrame:
        return predictor.predict(
            df=history,
            x_timestamp=x_stamps,
            y_timestamp=y_stamps,
            pred_len=args.pred_len,
            T=1.0,
            top_p=0.9,
            sample_count=sample_count,
            verbose=False,
        )

    for _ in range(args.warmup):
        forecast(args.sample_count)
    times = []
    for _ in range(args.repeats):
        started = time.perf_counter()
        forecast(args.sample_count)
        times.append(time.perf_counter() - started)

    capture = PathCapture()
    original_np = kronos_module.np
    kronos_module.np = capture
    try:
        torch.manual_seed(1)
        averaged = forecast(args.sample_count)
    finally:
        kronos_module.np = original_np

    ordered = sorted(times)
    return {
        "device": "cpu",
        "torch": torch.__version__,
        "threads": args.threads,
        "lookback": args.lookback,
        "pred_len": args.pred_len,
        "sample_count": args.sample_count,
        "repeats": args.repeats,
        "load_s": round(load_s, 3),
        "params_model": sum(p.numel() for p in model.parameters()),
        "params_tokenizer": sum(p.numel() for p in tokenizer.parameters()),
        "latency_s": {
            "median": round(statistics.median(times), 4),
            "min": round(ordered[0], 4),
            "p90": round(ordered[min(len(times) - 1, int(0.9 * len(times)))], 4),
            "mean": round(statistics.mean(times), 4),
        },
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "per_path": per_path_summary(capture, history, averaged, args.pred_len),
    }


def machine() -> dict:
    cpu = ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            cpu = next(line.split(":", 1)[1].strip() for line in handle if line.startswith("model name"))
    except (OSError, StopIteration):
        cpu = platform.processor()
    return {"cpu": cpu, "logical_cpus": os.cpu_count(), "python": platform.python_version()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kronos-src", required=True)
    parser.add_argument("--lookback", type=int, default=512)
    parser.add_argument("--pred-len", type=int, default=1)
    parser.add_argument("--sample-count", type=int, default=1)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = run_config(args)
    result["machine"] = machine()
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
