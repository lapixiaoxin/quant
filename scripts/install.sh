#!/bin/sh
# 仅在当前工作区安装依赖，不创建运行副本或后台服务。
set -eu
QUANT_PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
QUANT_PYTHON="${PYTHON:-python3}"
"$QUANT_PYTHON" -c 'import sys; assert sys.version_info >= (3, 9), "需要 Python 3.9+"'
if [ -L "$QUANT_PROJECT_ROOT/.venv" ]; then
  printf '%s\n' ".venv 是旧环境的符号链接，请核对后移除链接再安装。" >&2
  exit 1
fi
"$QUANT_PYTHON" -m venv "$QUANT_PROJECT_ROOT/.venv"
"$QUANT_PROJECT_ROOT/.venv/bin/python" -m pip install -e "$QUANT_PROJECT_ROOT[dev]"
"$QUANT_PROJECT_ROOT/quant" doctor
printf '%s\n' "工作区安装完成。研究入口与飞书归档流程见 README.md。"
