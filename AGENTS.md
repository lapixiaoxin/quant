# AGENTS.md

给代码代理（AI coding agent）的项目说明。改代码前先读这份文件，细节见 `README.md`。

## 项目是什么

qtrader：基于 akfamily 的 **A 股量化程序骨架** —— AKShare 取数 + AKQuant 引擎（Rust 撮合内核 + Python 策略 API）。
同一份策略代码同时支持**回测**与**实盘**。Python ≥ 3.11，包管理用 uv。

## 常用命令

```bash
uv sync                       # 安装/对齐环境（必须用 uv sync；不要 uv pip install，会绕过 uv.lock）
cp .env.example .env          # 按需修改配置

.venv/bin/python -m pytest -q # 跑测试（等价 uv run pytest）

uv run qtrader data-sync --symbols sh600000,sz000001 --start 20230101 --end 20240630
uv run qtrader backtest --symbols sh600000 --start 20230101 --end 20240630 --report reports/bt.html
uv run qtrader live --symbols sh600000 --start 20230101 --end 20231231 --duration 30s
```

## 目录结构

```
src/qtrader/
├── settings.py            # 配置入口：QT_ 环境变量 / .env，通过 get_settings() 读取
├── data/
│   ├── akshare_source.py  # fetch_daily / get_daily / load_universe（自带缓存）
│   └── store.py           # ParquetStore：data/bars/{freq}/{symbol}.parquet
├── strategy/
│   └── ma_cross.py        # 示例策略：双均线（回测/实盘同一份代码）
├── backtest/runner.py     # 回测封装：统一费率/滑点/T+1，产出 BacktestResult 与 HTML 报告
├── live/runner.py         # 实盘封装：paper(回放仿真) / broker_live(真实柜台)
└── cli.py                 # 命令行入口：data-sync / backtest / live
tests/test_smoke.py        # 冒烟测试：合成数据跑通回测与 paper 链路，不联网
```

## 约定（写代码必须遵守）

### 策略层
- 新策略放 `src/qtrader/strategy/`，继承 `akquant.Strategy`。
- 可调参数用**类体内联字段**声明（如 `fast: int = 5`），akquant 参数优化框架会直接扫描这些字段。
- `get_history` 之前必须 `set_history_depth(...)`，并设置 `warmup_period`；不声明回溯长度会直接报错。
- 策略必须能同时在 `run_backtest` 与 `run_live` 下运行，不要写只有回测能跑的代码。

### 数据层
- AKShare 符号口径带交易所前缀：`sh600000`、`sz000001`。
- 行情规范列固定为 `date/open/high/low/close/volume` 六列（AKQuant `dataframe_to_bars` 的要求）。
- 取数一律走 `load_universe` / `get_daily`（自带 Parquet 缓存），不要在策略里直接调 akshare。
- 日期参数格式为 `YYYYMMDD` 字符串。
- 复权口径由 `adjust` 参数控制：`""` 不复权 / `qfq` 前复权 / `hfq` 后复权，默认不复权。`ParquetStore` 按该参数分文件缓存（如 `sh601088.qfq.parquet`），不同口径互不覆盖。**高分红标的回测必须显式传 `qfq`**，否则除权除息跳空会让收益被低估、回撤被高估。
- CLI 对应参数为 `--adjust`，三个子命令（`data-sync` / `backtest` / `live`）都支持；`data-sync` 与 `backtest` 需使用同一 `--adjust` 值，否则会读到不同口径的缓存。

### 配置与回测
- 费率、滑点、初始资金、T+1 等一切配置进 `settings.py` 的 `Settings`，经 `get_settings()` 读取；环境变量统一 `QT_` 前缀。不要硬编码这些数值。
- 回测统一走 `qtrader.backtest.run` 封装；不要绕开封装直接调 `run_backtest`，否则会丢费率与 T+1 口径。
- `uv.lock` 保证回测结果可复现。不要随手升级依赖或改动 `uv.lock`；确需升级用 `uv lock --upgrade-package <包名>` 单点进行，并重跑 pytest 与对账测试。

### 实盘层
- 默认 `paper` 模式（回放本地行情 + 仿真撮合），改动策略后先在 paper 模式验证全链路。
- `broker_live` 会触碰真实资金：相关改动必须谨慎，并在修改说明中明确写清风险。
- QMT/PTrade 在开源包内仅为占位 stub，需另装券商插件或 SDK；CTP 为引擎原生支持。

## 测试要求

- 测试不得联网：行情用合成数据，参考 `tests/test_smoke.py` 的 `_synthetic()`。
- 新增策略、数据源，或改动 `backtest/runner.py`、`live/runner.py` 时，必须补/改冒烟测试并运行：

```bash
.venv/bin/python -m pytest -q
```

## 已知边界

- AKShare 是目标网站的非官方接口，站点改版会导致接口失效，需保持升级；数据仅供学术研究，商用请自行评估。
- 多标的时数据以 `{symbol: df}` 字典传入 `run_backtest` / `run_session`，单标的可用 `DataFrame`。
- AKQuant 的 bar 时间戳为 UTC ISO 8601，做日期对齐时注意时区。