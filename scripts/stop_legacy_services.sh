#!/bin/sh
# 一次性停用旧服务；保留运行目录、配置、日志及研究数据供人工核对。
set -eu

QUANT_LAUNCH_DOMAIN="gui/$(id -u)"
quant_service_loaded() {
  if QUANT_LAUNCH_STATE=$(launchctl print "$1" 2>&1); then
    return 0
  fi
  case "$QUANT_LAUNCH_STATE" in
    *"Could not find service"*) return 1 ;;
    *)
      printf '%s\n' "无法核验服务状态：$1：$QUANT_LAUNCH_STATE" >&2
      return 2
      ;;
  esac
}

for QUANT_LEGACY_LABEL in \
  com.local.quant-monitor.daily \
  com.local.quant-monitor.remote \
  com.local.etf-monitor
do
  launchctl disable "$QUANT_LAUNCH_DOMAIN/$QUANT_LEGACY_LABEL"
  if quant_service_loaded "$QUANT_LAUNCH_DOMAIN/$QUANT_LEGACY_LABEL"; then
    launchctl bootout "$QUANT_LAUNCH_DOMAIN/$QUANT_LEGACY_LABEL"
  else
    QUANT_STATUS=$?
    [ "$QUANT_STATUS" -eq 1 ] || exit "$QUANT_STATUS"
  fi
  if quant_service_loaded "$QUANT_LAUNCH_DOMAIN/$QUANT_LEGACY_LABEL"; then
    printf '%s\n' "服务仍加载：$QUANT_LEGACY_LABEL" >&2
    exit 1
  else
    QUANT_STATUS=$?
    [ "$QUANT_STATUS" -eq 1 ] || exit "$QUANT_STATUS"
  fi
  printf '%s\n' "已停用且未加载：$QUANT_LEGACY_LABEL"
done
