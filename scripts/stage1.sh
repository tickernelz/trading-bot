#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: RUN_DIR=<dir> IMAGE=<image> [UNIT_PREFIX=<prefix>] $0 start|stop|status [component...]" >&2
  echo "components: bot-a bot-b shadow-b analyst-b gateway (default: all)" >&2
  exit 2
}

[ $# -ge 1 ] || usage
action=$1
shift
components=("$@")
[ ${#components[@]} -gt 0 ] || components=(bot-a bot-b shadow-b analyst-b gateway)
prefix=${UNIT_PREFIX:-trading-bot-stage1}
run_dir=${RUN_DIR:?set RUN_DIR}
mount=/opt/trading-bot/run

container_args() {
  case $1 in
    bot-a)
      echo "--memory 1g --memory-swap 1g --env-file $run_dir/secrets/ft.env"
      echo "-e TRADING_BOT_CONFIG=$mount/config/$1.yaml -e TRADING_BOT_USERDIR=$mount/$1"
      echo "${IMAGE:?set IMAGE} trade"
      ;;
    bot-b)
      echo "--memory 1g --memory-swap 1g --env-file $run_dir/secrets/ft.env --env-file $run_dir/secrets/shadow.env"
      echo "-e TRADING_BOT_CONFIG=$mount/config/$1.yaml -e TRADING_BOT_USERDIR=$mount/$1"
      echo "${IMAGE:?set IMAGE} trade"
      ;;
    shadow-b)
      echo "--memory 512m --memory-swap 512m --env-file $run_dir/secrets/swarm.env --env-file $run_dir/secrets/shadow.env"
      echo "-e TRADING_BOT_CONFIG=$mount/config/bot-b.yaml -e TRADING_BOT_USERDIR=$mount/bot-b"
      echo "--entrypoint python ${IMAGE:?set IMAGE} -m engine.shadow"
      ;;
    analyst-b)
      echo "--memory 512m --memory-swap 512m --env-file $run_dir/secrets/analyst.env"
      echo "-e TRADING_BOT_CONFIG=$mount/config/bot-b.yaml -e TRADING_BOT_USERDIR=$mount/bot-b"
      echo "--entrypoint python ${IMAGE:?set IMAGE} -m engine.analyst_service"
      ;;
    gateway)
      echo "--memory 512m --memory-swap 512m --env-file $run_dir/secrets/gateway.env"
      echo "-e GATEWAY_CONFIG=$mount/config/gateway.yaml"
      echo "--entrypoint python ${IMAGE:?set IMAGE} -m gateway"
      ;;
    *) usage ;;
  esac
}

for component in "${components[@]}"; do
  unit="$prefix-$component"
  name="$prefix-$component"
  case $action in
    start)
      args=$(container_args "$component" | tr '\n' ' ')
      systemd-run --user --collect --unit "$unit" \
        -p Restart=always -p RestartSec=15 -p TimeoutStopSec=90 \
        bash -c "docker rm -f $name >/dev/null 2>&1; exec docker run --rm --name $name --network host -v $run_dir:$mount $args"
      ;;
    stop) systemctl --user stop "$unit" ;;
    status) systemctl --user --no-pager --lines 0 status "$unit" || true ;;
    *) usage ;;
  esac
done
