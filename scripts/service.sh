#!/bin/sh
set -eu

LABEL="com.local.etf-monitor"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "${1:-status}" in
  start)
    launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null || true
    launchctl enable "$DOMAIN/$LABEL"
    ;;
  stop)
    launchctl bootout "$DOMAIN/$LABEL"
    ;;
  restart)
    launchctl kickstart -k "$DOMAIN/$LABEL"
    ;;
  run-now)
    launchctl kickstart -k "$DOMAIN/$LABEL"
    ;;
  status)
    launchctl print "$DOMAIN/$LABEL"
    ;;
  *)
    printf '%s\n' "用法：$0 {start|stop|restart|run-now|status}" >&2
    exit 2
    ;;
esac
