#!/bin/sh
set -eu

REPOSITORY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUNTIME_ROOT="${QUANT_RUNTIME_HOME:-$HOME/.local/share/quant-monitor}"
PYTHON="${PYTHON:-python3}"
RESTART_SERVICES=0

if [ ! -d "$RUNTIME_ROOT" ]; then
  printf '%s\n' "运行副本不存在：$RUNTIME_ROOT" >&2
  exit 1
fi
if [ "$REPOSITORY_ROOT" = "$RUNTIME_ROOT" ]; then
  printf '%s\n' "仓库目录与运行目录相同，无需同步。" >&2
  exit 1
fi

restore_services() {
  if [ "$RESTART_SERVICES" -eq 1 ]; then
    "$REPOSITORY_ROOT/scripts/service.sh" start all >/dev/null 2>&1 || true
  fi
}
trap restore_services EXIT HUP INT TERM

if launchctl print "gui/$(id -u)/com.local.quant-monitor.daily" \
  >/dev/null 2>&1 \
  || launchctl print "gui/$(id -u)/com.local.quant-monitor.remote" \
    >/dev/null 2>&1; then
  RESTART_SERVICES=1
fi
"$REPOSITORY_ROOT/scripts/service.sh" stop all >/dev/null

for relative_dir in \
  data/analysis \
  data/backtests \
  data/dashboard \
  data/latest \
  data/reports \
  data/selections \
  data/snapshots \
  research/private \
  research/selections
do
  if [ -d "$RUNTIME_ROOT/$relative_dir" ]; then
    mkdir -p "$REPOSITORY_ROOT/$relative_dir"
    rsync -a \
      --exclude '*.sqlite3-shm' \
      --exclude '*.sqlite3-wal' \
      --exclude '*.sqlite3-journal' \
      "$RUNTIME_ROOT/$relative_dir/" "$REPOSITORY_ROOT/$relative_dir/"
  fi
done

for relative_database in \
  data/history/market.sqlite3 \
  data/control/research.sqlite3
do
  RUNTIME_DATABASE="$RUNTIME_ROOT/$relative_database"
  REPOSITORY_DATABASE="$REPOSITORY_ROOT/$relative_database"
  if [ ! -f "$RUNTIME_DATABASE" ]; then
    continue
  fi
  mkdir -p "$(dirname "$REPOSITORY_DATABASE")"
  "$PYTHON" - "$RUNTIME_DATABASE" "$REPOSITORY_DATABASE" <<'PY'
import os
import sqlite3
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])
temporary_path = target_path.with_name(f".{target_path.name}.sync-{os.getpid()}")

try:
    with sqlite3.connect(source_path) as source:
        source.execute("PRAGMA wal_checkpoint(FULL)")
        with sqlite3.connect(temporary_path) as target:
            source.backup(target)
            result = target.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise RuntimeError(f"SQLite 完整性检查失败：{result}")
    os.replace(temporary_path, target_path)
finally:
    temporary_path.unlink(missing_ok=True)
PY
done

printf '%s\n' "运行数据已导出到私有仓库：$REPOSITORY_ROOT"
printf '%s\n' "提交前仍需执行敏感信息、文件体积和 Git 差异检查。"
