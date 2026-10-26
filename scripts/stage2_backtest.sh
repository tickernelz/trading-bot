#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: IMAGE=<engine image> $0 <output dir> [since YYYY-MM-DD] [until YYYY-MM-DD]" >&2
  exit 2
}

[ $# -ge 1 ] || usage
out=$(realpath -m "$1")
since=${2:-2023-10-01}
until=${3:-2026-10-26}
root=$(cd "$(dirname "$0")/.." && pwd)
image=${IMAGE:?set IMAGE}
mount=/opt/trading-bot/run
mkdir -p "$out"

run() {
  docker run --rm --memory 2g --memory-swap 2g \
    -v "$out:$mount" \
    -v "$root/config/config.example.yaml:/opt/trading-bot/config/config.yaml:ro" \
    "$@"
}

if [ ! -f "$out/history.json" ]; then
  run --network host --entrypoint python "$image" -m engine.history \
    --since "$since" --until "$until" --datadir "$mount/data/indodax" --manifest "$mount/history.json"
fi
run --network host --entrypoint python "$image" -m engine.backtest_suite \
  --out "$mount" --datadir "$mount/data/indodax"
