#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: IMAGE=<engine test image> $0 <run dir> <walk-forward|controls|validate|holdout> [args...]" >&2
  exit 2
}

[ $# -ge 2 ] || usage
run_dir=$(realpath -m "$1")
command=$2
shift 2
root=$(cd "$(dirname "$0")/.." && pwd)
image=${IMAGE:?set IMAGE}
sha=$(git -C "$root" rev-parse HEAD)
dirty=$(git -C "$root" status --porcelain -- engine scripts tests | grep -q . && echo yes || echo no)
mkdir -p "$run_dir/out"

exec nice -n 19 docker run --rm --cpus "${CPUS:-2}" --memory "${MEMORY:-3g}" --memory-swap "${MEMORY:-3g}" \
  -e TRADING_BOT_GIT_SHA="$sha" -e TRADING_BOT_GIT_DIRTY="$dirty" \
  -v "$root:/opt/trading-bot" -v "$run_dir:/run-dir" \
  --entrypoint python "$image" -m engine.strategy_search "$command" \
  --datadir /run-dir/data/indodax --fear-greed /run-dir/data/fear_greed.json --out /run-dir/out "$@"
