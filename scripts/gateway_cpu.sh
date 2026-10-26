#!/usr/bin/env bash
set -euo pipefail

[ $# -eq 3 ] || {
  echo "usage: $0 <container> <seconds> <label>" >&2
  exit 2
}
container=$1
seconds=$2
label=$3
id=$(docker inspect -f '{{.Id}}' "$container")
stat=$(find /sys/fs/cgroup -maxdepth 4 -type d -name "docker-$id.scope" | head -1)/cpu.stat
usage() { awk '/^usage_usec/ {print $2}' "$stat"; }
before=$(usage)
started=$(date -u +%FT%TZ)
sleep "$seconds"
after=$(usage)
awk -v l="$label" -v c="$container" -v s="$seconds" -v a="$before" -v b="$after" -v t="$started" 'BEGIN {
  printf "{\"label\": \"%s\", \"container\": \"%s\", \"started_at\": \"%s\", \"seconds\": %d, ", l, c, t, s
  printf "\"usage_usec_before\": %d, \"usage_usec_after\": %d, ", a, b
  printf "\"cpu_seconds\": %.3f, \"cpu_pct_one_core\": %.4f}\n", (b - a) / 1e6, (b - a) / (s * 1e6) * 100
}'
