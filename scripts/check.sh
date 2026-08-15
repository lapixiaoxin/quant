#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

printf '%s\n' "检查 Shell 语法..."
for script in "$ROOT"/scripts/*.sh; do
  sh -n "$script"
done

printf '%s\n' "检查 Python 语法..."
"$PYTHON" -m compileall -q "$ROOT/src" "$ROOT/tests"

printf '%s\n' "运行单元测试..."
"$PYTHON" -m unittest discover -s "$ROOT/tests" -v

if "$PYTHON" -m ruff --version >/dev/null 2>&1; then
  printf '%s\n' "运行 Ruff..."
  "$PYTHON" -m ruff check "$ROOT/src" "$ROOT/tests"
else
  printf '%s\n' "提示：未安装 Ruff，已跳过可选静态检查。"
fi

printf '%s\n' "全部必需检查已通过。"
