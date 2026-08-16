#!/bin/sh
set -eu

SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUNTIME_ROOT="${QUANT_RUNTIME_HOME:-$HOME/.local/share/quant-monitor}"
RUNTIME_DATA_MODE="${QUANT_RUNTIME_DATA_MODE:-preserve}"
PYTHON="${PYTHON:-python3}"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
DAILY_LABEL="com.local.quant-monitor.daily"
REMOTE_LABEL="com.local.quant-monitor.remote"
DAILY_PLIST="$LAUNCH_AGENTS/$DAILY_LABEL.plist"
REMOTE_PLIST="$LAUNCH_AGENTS/$REMOTE_LABEL.plist"
DOMAIN="gui/$(id -u)"
SERVICE_PATH="$HOME/.local/bin:$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

case "$RUNTIME_DATA_MODE" in
  preserve|replace) ;;
  *)
    printf '%s\n' "QUANT_RUNTIME_DATA_MODE 仅支持 preserve 或 replace。" >&2
    exit 2
    ;;
esac

"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' || {
  printf '%s\n' "需要 Python 3.9 或更高版本。"
  exit 1
}

if [ ! -f "$SOURCE_ROOT/config/config.toml" ]; then
  cp "$SOURCE_ROOT/config/config.example.toml" \
    "$SOURCE_ROOT/config/config.toml"
fi

# 安装和数据接管期间不能让 LaunchAgent 同时写运行副本。
launchctl bootout "$DOMAIN/$DAILY_LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN/$REMOTE_LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN/com.local.etf-monitor" 2>/dev/null || true

mkdir -p "$RUNTIME_ROOT"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '*.egg-info/' \
  --exclude 'config/config.toml' \
  --exclude 'data/dashboard/' \
  --exclude 'data/analysis/' \
  --exclude 'data/backtests/' \
  --exclude 'data/control/' \
  --exclude 'data/latest/*.json' \
  --exclude 'data/latest/*.md' \
  --exclude 'data/latest/*.txt' \
  --exclude 'data/reports/*/' \
  --exclude 'data/selections/' \
  --exclude 'data/snapshots/' \
  --exclude 'data/history/' \
  --exclude 'logs/*.log' \
  --exclude 'research/private/' \
  --exclude 'research/selections/' \
  "$SOURCE_ROOT/" "$RUNTIME_ROOT/"

# 私有仓库中的研究资产只用于补齐新设备，绝不覆盖运行目录已有的新数据。
for relative_dir in \
  data/analysis \
  data/backtests \
  data/control \
  data/dashboard \
  data/history \
  data/latest \
  data/reports \
  data/selections \
  data/snapshots \
  research/private \
  research/selections
do
  if [ -d "$SOURCE_ROOT/$relative_dir" ]; then
    mkdir -p "$RUNTIME_ROOT/$relative_dir"
    rsync -a --ignore-existing \
      --exclude '*.sqlite3-shm' \
      --exclude '*.sqlite3-wal' \
      --exclude '*.sqlite3-journal' \
      "$SOURCE_ROOT/$relative_dir/" "$RUNTIME_ROOT/$relative_dir/"
  fi
done

if [ "$RUNTIME_DATA_MODE" = "replace" ]; then
  # 仅用于单写者设备交接：仓库版本覆盖同名运行数据，但保留目标端独有文件。
  for relative_dir in \
    data/analysis \
    data/backtests \
    data/control \
    data/dashboard \
    data/history \
    data/latest \
    data/reports \
    data/selections \
    data/snapshots \
    research/private \
    research/selections
  do
    if [ -d "$SOURCE_ROOT/$relative_dir" ]; then
      rsync -a \
        --exclude '*.sqlite3-shm' \
        --exclude '*.sqlite3-wal' \
        --exclude '*.sqlite3-journal' \
        "$SOURCE_ROOT/$relative_dir/" "$RUNTIME_ROOT/$relative_dir/"
    fi
  done
fi

cp "$SOURCE_ROOT/config/config.toml" "$RUNTIME_ROOT/config/config.toml"
chmod 600 "$RUNTIME_ROOT/config/config.toml"
chmod +x "$RUNTIME_ROOT/quant" "$RUNTIME_ROOT/scripts/"*.sh
mkdir -p "$RUNTIME_ROOT/logs" "$LAUNCH_AGENTS"

"$PYTHON" -m venv "$RUNTIME_ROOT/.venv"
"$RUNTIME_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$RUNTIME_ROOT/.venv/bin/python" -m pip install -e "$RUNTIME_ROOT[dev]"

if [ ! -e "$SOURCE_ROOT/.venv" ]; then
  ln -s "$RUNTIME_ROOT/.venv" "$SOURCE_ROOT/.venv"
fi

"$RUNTIME_ROOT/quant" doctor
"$RUNTIME_ROOT/quant" site

AUTOMATION_INFO=$("$RUNTIME_ROOT/.venv/bin/python" - "$RUNTIME_ROOT/config/config.toml" <<'PY'
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

with open(sys.argv[1], "rb") as handle:
    config = tomllib.load(handle)
enabled = bool(config.get("automation", {}).get("enabled", False))
report_time = str(config.get("app", {}).get("report_time", "14:00"))
hour, minute = (int(value) for value in report_time.split(":", 1))
if not 0 <= hour <= 23 or not 0 <= minute <= 59:
    raise SystemExit("app.report_time 必须是 HH:MM")
print(f"{int(enabled)} {hour} {minute}")
PY
)
set -- $AUTOMATION_INFO
AUTOMATION_ENABLED=$1
REPORT_HOUR=$2
REPORT_MINUTE=$3

rm -f "$LAUNCH_AGENTS/com.local.etf-monitor.plist"

if [ "$AUTOMATION_ENABLED" = "1" ]; then
  cat >"$DAILY_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$DAILY_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNTIME_ROOT/quant</string>
    <string>automate</string>
    <string>--all</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$RUNTIME_ROOT</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$SERVICE_PATH</string></dict>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>$REPORT_HOUR</integer><key>Minute</key><integer>$REPORT_MINUTE</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>$REPORT_HOUR</integer><key>Minute</key><integer>$REPORT_MINUTE</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>$REPORT_HOUR</integer><key>Minute</key><integer>$REPORT_MINUTE</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>$REPORT_HOUR</integer><key>Minute</key><integer>$REPORT_MINUTE</integer></dict>
    <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>$REPORT_HOUR</integer><key>Minute</key><integer>$REPORT_MINUTE</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>$RUNTIME_ROOT/logs/daily.out.log</string>
  <key>StandardErrorPath</key>
  <string>$RUNTIME_ROOT/logs/daily.err.log</string>
</dict>
</plist>
EOF
  launchctl bootstrap "$DOMAIN" "$DAILY_PLIST"
  launchctl enable "$DOMAIN/$DAILY_LABEL"
  printf '%s\n' "定时研究服务已安装：工作日 $(printf '%02d:%02d' "$REPORT_HOUR" "$REPORT_MINUTE")"
else
  rm -f "$DAILY_PLIST"
  printf '%s\n' "automation.enabled=false，未安装定时研究服务。"
fi

if "$RUNTIME_ROOT/quant" listen --check >/dev/null 2>&1; then
  cat >"$REMOTE_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$REMOTE_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNTIME_ROOT/quant</string>
    <string>listen</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$RUNTIME_ROOT</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$SERVICE_PATH</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key>
  <string>$RUNTIME_ROOT/logs/remote.out.log</string>
  <key>StandardErrorPath</key>
  <string>$RUNTIME_ROOT/logs/remote.err.log</string>
</dict>
</plist>
EOF
  launchctl bootstrap "$DOMAIN" "$REMOTE_PLIST"
  launchctl enable "$DOMAIN/$REMOTE_LABEL"
  printf '%s\n' "飞书远程命令服务已安装。"
else
  rm -f "$REMOTE_PLIST"
  printf '%s\n' "远程命令未启用或 lark-cli 未就绪，未安装监听服务。"
fi

printf '%s\n' "运行目录：$RUNTIME_ROOT"
printf '%s\n' "服务检查：$SOURCE_ROOT/scripts/service.sh status"
