#!/bin/sh
set -u

DOMAIN="gui/$(id -u)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
DAILY_LABEL="com.local.quant-monitor.daily"
REMOTE_LABEL="com.local.quant-monitor.remote"
ACTION="${1:-status}"
TARGET="${2:-all}"

if [ "$TARGET" = "all" ]; then
  DAILY_STATUS=0
  REMOTE_STATUS=0
  "$0" "$ACTION" daily || DAILY_STATUS=$?
  "$0" "$ACTION" remote || REMOTE_STATUS=$?
  if [ "$DAILY_STATUS" -ne 0 ]; then
    exit "$DAILY_STATUS"
  fi
  exit "$REMOTE_STATUS"
fi

case "$TARGET" in
  daily) LABEL="$DAILY_LABEL" ;;
  remote) LABEL="$REMOTE_LABEL" ;;
  *)
    printf '%s\n' "服务仅支持 daily、remote 或 all。" >&2
    exit 2
    ;;
esac

PLIST="$LAUNCH_AGENTS/$LABEL.plist"

case "$ACTION" in
  start)
    if [ ! -f "$PLIST" ]; then
      printf '%s\n' "$LABEL 未安装，跳过。"
      exit 0
    fi
    launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null || true
    launchctl enable "$DOMAIN/$LABEL" || exit $?
    printf '%s\n' "$LABEL 已启动。"
    ;;
  stop)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    printf '%s\n' "$LABEL 已停止。"
    ;;
  restart)
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1
    RUNNING=$?
    if [ "$RUNNING" -eq 0 ]; then
      launchctl kickstart -k "$DOMAIN/$LABEL" || exit $?
      printf '%s\n' "$LABEL 已重启。"
    else
      printf '%s\n' "$LABEL 未运行。"
    fi
    ;;
  run-now)
    if [ "$LABEL" = "$REMOTE_LABEL" ]; then
      printf '%s\n' "remote 是常驻服务，不支持 run-now。" >&2
      exit 0
    fi
    launchctl kickstart -k "$DOMAIN/$LABEL" || exit $?
    printf '%s\n' "$LABEL 已触发。"
    ;;
  status)
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1
    RUNNING=$?
    if [ "$RUNNING" -eq 0 ]; then
      if [ "$TARGET" = "daily" ]; then
        printf '%s: %s\n' "$LABEL" "已加载，等待定时触发"
      else
        printf '%s: %s\n' "$LABEL" "已加载"
      fi
    elif [ -f "$PLIST" ]; then
      printf '%s: %s\n' "$LABEL" "已安装但未运行"
    else
      printf '%s: %s\n' "$LABEL" "未安装"
    fi
    ;;
  *)
    printf '%s\n' "用法：$0 {start|stop|restart|run-now|status} [daily|remote|all]" >&2
    exit 2
    ;;
esac
