#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: RUN_DIR=<dir> IMAGE=<image> [UNIT_PREFIX=<prefix>] $0 start|stop|status [component...]" >&2
  echo "components: bot-a bot-b shadow-b analyst-b gateway pwa (default: all)" >&2
  exit 2
}

[ $# -ge 1 ] || usage
action=$1
shift
components=("$@")
[ ${#components[@]} -gt 0 ] || components=(bot-a bot-b shadow-b analyst-b gateway pwa)
prefix=${UNIT_PREFIX:-trading-bot-stack}
run_dir=${RUN_DIR:?set RUN_DIR}
mount=/opt/trading-bot/run
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
pwa_dir=$repo/pwa
gateway_url=${GATEWAY_URL:-http://127.0.0.1:8090}

data_dirs() {
  case $1 in
    bot-a) echo bot-a ;;
    bot-b | shadow-b | analyst-b) echo bot-b ;;
    gateway) echo gateway bot-a bot-b ;;
    pwa) ;;
    *) usage ;;
  esac
}

cpu_cap() {
  case $1 in
    bot-a | bot-b) echo 1.0 ;;
    shadow-b | analyst-b | gateway) echo 0.5 ;;
    pwa) echo 50% ;;
    *) usage ;;
  esac
}

mount_args() {
  printf '%s' "-v $run_dir/config:$mount/config:ro"
  for dir in $(data_dirs "$1"); do
    printf '%s' " -v $run_dir/$dir:$mount/$dir"
  done
}

container_args() {
  case $1 in
    bot-a)
      echo "--cpus $(cpu_cap "$1") --memory 1g --memory-swap 1g --env-file $run_dir/secrets/ft.env"
      echo "-e TRADING_BOT_CONFIG=$mount/config/$1.yaml -e TRADING_BOT_USERDIR=$mount/$1"
      echo "${IMAGE:?set IMAGE} trade"
      ;;
    bot-b)
      echo "--cpus $(cpu_cap "$1") --memory 1g --memory-swap 1g --env-file $run_dir/secrets/ft.env --env-file $run_dir/secrets/shadow.env"
      echo "-e TRADING_BOT_CONFIG=$mount/config/$1.yaml -e TRADING_BOT_USERDIR=$mount/$1"
      echo "${IMAGE:?set IMAGE} trade"
      ;;
    shadow-b)
      echo "--cpus $(cpu_cap "$1") --memory 512m --memory-swap 512m --env-file $run_dir/secrets/swarm.env --env-file $run_dir/secrets/shadow.env"
      echo "-e TRADING_BOT_CONFIG=$mount/config/bot-b.yaml -e TRADING_BOT_USERDIR=$mount/bot-b"
      echo "--entrypoint python ${IMAGE:?set IMAGE} -m engine.shadow"
      ;;
    analyst-b)
      echo "--cpus $(cpu_cap "$1") --memory 512m --memory-swap 512m --env-file $run_dir/secrets/analyst.env"
      echo "-e TRADING_BOT_CONFIG=$mount/config/bot-b.yaml -e TRADING_BOT_USERDIR=$mount/bot-b"
      echo "--entrypoint python ${IMAGE:?set IMAGE} -m engine.analyst_service"
      ;;
    gateway)
      echo "--cpus $(cpu_cap "$1") --memory 512m --memory-swap 512m --env-file $run_dir/secrets/gateway.env"
      echo "-e GATEWAY_CONFIG=$mount/config/gateway.yaml"
      echo "--entrypoint python ${IMAGE:?set IMAGE} -m gateway"
      ;;
    *) usage ;;
  esac
}

start_pwa() {
  local node_bin
  node_bin=$(dirname "$(command -v npm)")
  if [ ! -d "$pwa_dir/node_modules" ]; then
    npm --prefix "$pwa_dir" ci
  fi
  npm --prefix "$pwa_dir" run build
  systemd-run --user --collect --unit "$1" \
    -p Restart=always -p RestartSec=15 -p TimeoutStopSec=30 \
    -p Nice=10 -p "CPUQuota=$(cpu_cap pwa)" -p "WorkingDirectory=$pwa_dir" \
    -p "Environment=PATH=$node_bin:/usr/local/bin:/usr/bin" \
    --setenv=GATEWAY_URL="$gateway_url" \
    npm run preview
}

for component in "${components[@]}"; do
  unit="$prefix-$component"
  name="$prefix-$component"
  case $action in
    start)
      if [ "$component" = pwa ]; then
        start_pwa "$unit"
        continue
      fi
      args=$(container_args "$component" | tr '\n' ' ')
      mounts=$(mount_args "$component")
      for dir in $(data_dirs "$component"); do mkdir -p "$run_dir/$dir"; done
      systemd-run --user --collect --unit "$unit" \
        -p Restart=always -p RestartSec=15 -p TimeoutStopSec=90 \
        bash -c "docker rm -f $name >/dev/null 2>&1; exec docker run --rm --name $name --network host $mounts $args"
      ;;
    stop) systemctl --user stop "$unit" ;;
    status) systemctl --user --no-pager --lines 0 status "$unit" || true ;;
    *) usage ;;
  esac
done
