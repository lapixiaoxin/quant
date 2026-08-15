#!/bin/sh
set -eu

REPOSITORY="${QUANT_REPOSITORY:-git@github.com:lapixiaoxin/quant.git}"
TARGET="${QUANT_HOME:-$HOME/Quant}"
WITH_TRAECLI=0
WITH_LARKCLI=0

for argument in "$@"; do
  case "$argument" in
    --with-traecli) WITH_TRAECLI=1 ;;
    --with-lark-cli) WITH_LARKCLI=1 ;;
    --target=*) TARGET=${argument#--target=} ;;
    *)
      printf '%s\n' "未知参数：$argument" >&2
      printf '%s\n' "用法：$0 [--target=目录] [--with-traecli] [--with-lark-cli]" >&2
      exit 2
      ;;
  esac
done

command -v git >/dev/null 2>&1 || {
  printf '%s\n' "缺少 git，请先安装 Xcode Command Line Tools。" >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  printf '%s\n' "缺少 Python 3.9 或更高版本。" >&2
  exit 1
}

if [ -d "$TARGET/.git" ]; then
  git -C "$TARGET" pull --ff-only origin main
elif [ -e "$TARGET" ]; then
  printf '%s\n' "目标路径已存在但不是 Git 仓库：$TARGET" >&2
  exit 1
else
  git clone "$REPOSITORY" "$TARGET"
fi

if [ "$WITH_TRAECLI" = "1" ] \
  && ! command -v traecli >/dev/null 2>&1 \
  && [ ! -x "$HOME/.local/bin/traecli" ]; then
  INSTALLER=$(mktemp)
  trap 'rm -f "$INSTALLER"' EXIT
  INTERNAL_INSTALLER="https://code.byted.org/api/tos-proxy/download/adopt_coco.sh"
  PUBLIC_INSTALLER="https://trae.cn/trae-cli/install.sh"
  if [ -n "${TRAECLI_INSTALL_URL:-}" ]; then
    curl -fsSL "$TRAECLI_INSTALL_URL" -o "$INSTALLER"
  elif curl -fsSL "$INTERNAL_INSTALLER" -o "$INSTALLER"; then
    printf '%s\n' "检测到内场网络，安装 TraeCode CLI 内部版。"
  else
    curl -fsSL "$PUBLIC_INSTALLER" -o "$INSTALLER"
    printf '%s\n' "安装 TraeCode CLI 公开版。"
  fi
  sh "$INSTALLER"
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ "$WITH_LARKCLI" = "1" ] && ! command -v lark-cli >/dev/null 2>&1; then
  command -v npm >/dev/null 2>&1 || {
    printf '%s\n' "安装 lark-cli 需要 Node.js 与 npm。" >&2
    exit 1
  }
  npm install -g @larksuite/cli
fi

"$TARGET/scripts/install_macos.sh"

printf '\n%s\n' "部署完成：$TARGET"
printf '%s\n' "下一步请编辑：$TARGET/config/config.toml"
if [ "$WITH_TRAECLI" = "1" ]; then
  printf '%s\n' "首次使用 TraeCode CLI 仍需运行 traecli 完成账号登录。"
fi
if [ "$WITH_LARKCLI" = "1" ]; then
  printf '%s\n' "首次使用飞书长连接仍需运行 lark-cli config init --new。"
fi
