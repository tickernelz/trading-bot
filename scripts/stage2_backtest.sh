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

docker run --rm --memory 512m --memory-swap 512m \
  -v "$out:$mount" -v "$root/config/config.example.yaml:/tmp/example.yaml:ro" \
  --entrypoint python "$image" -c "
import yaml
raw = yaml.safe_load(open('/tmp/example.yaml', encoding='utf-8'))
raw['strategy'] = {'name': 'SwingEmaRsi'}
yaml.safe_dump(raw, open('$mount/stage2-config.yaml', 'w', encoding='utf-8'), sort_keys=False)
"

run() {
  docker run --rm --memory 2g --memory-swap 2g \
    -v "$out:$mount" \
    -e TRADING_BOT_CONFIG="$mount/stage2-config.yaml" \
    "$@"
}

if [ ! -f "$out/history.json" ]; then
  run --network host --entrypoint python "$image" -m engine.history \
    --since "$since" --until "$until" --datadir "$mount/data/indodax" --manifest "$mount/history.json"
fi
run --network host --entrypoint python "$image" -m engine.backtest_suite \
  --out "$mount" --datadir "$mount/data/indodax"
