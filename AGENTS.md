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
uv run qtrader screen --out reports/candidates.csv   # 四层漏斗筛选波段标的（默认走全市场快照）
uv run qtrader screen --symbols sh510300 --asset etf  # 基金口径（免印花税，缓存独立）
uv run qtrader screen --period daily                  # 日线口径（默认是周线口径）
uv run qtrader screen --validate --train-years 3 --test-years 2   # 样本外验证
```

## 远程仓库与推送规范

- 远程：`git@github.com:lapixiaoxin/quant.git`；主分支 `main`；本地 `main` 跟踪 `origin/main`。
- **每次改动都及时推送**：完成一次修改后立即 `git add` → `git commit` → `git push`，不要攒批。新增、修改、删除代码/配置/文档都算一次改动。
- 提交信息用中文，采用 `feat:` / `fix:` / `refactor:` / `chore:` / `docs:` 前缀。
- 入库范围：源码、`pyproject.toml`、`uv.lock`、`README.md`、`AGENTS.md`，以及 `data/` 下的行情数据（随代码入库，保证回测可复现且不依赖 AKShare 联网）。`.venv/`、`reports/`、`.env`、`__pycache__/`、`.pytest_cache/` 不推送。
- `data/` 中同时保留不复权（`{symbol}.parquet`）与前复权（`{symbol}.qfq.parquet`）两套数据，两者都要入库。
- `legacy-quant-monitor` 分支保存了 2026-10 之前的旧项目 `quant_monitor`（24 个提交），**不要删除**，仅作历史备份。
- 强制推送 `main` 属高危操作，仅在你明确要求时执行。

## 目录结构

```
src/qtrader/
├── settings.py            # 配置入口：QT_ 环境变量 / .env，通过 get_settings() 读取
├── data/
│   ├── akshare_source.py  # 个股：fetch_daily / get_daily / load_universe（自带缓存）
│   ├── etf_source.py      # ETF：快照 + 日线（缓存独立在 data/etf/）
│   └── store.py           # ParquetStore：data/bars/{freq}/{symbol}.parquet
├── strategy/
│   └── ma_cross.py        # 示例策略：双均线（回测/实盘同一份代码）
├── screening/             # 筛选层：四层漏斗筛出适合做波段的标的
│   ├── metrics.py         # 指标计算（按日线/周线周期），不含未来函数
│   ├── universe.py        # 第0层：个股/ETF 候选池过滤
│   └── screen.py          # 漏斗判定 + 打分 + run_screen / run_out_of_sample
├── backtest/runner.py     # 回测封装：按资产类型套费率，产出 BacktestResult 与 HTML 报告
├── live/runner.py         # 实盘封装：paper(回放仿真) / broker_live(真实柜台)
└── cli.py                 # 命令行入口：data-sync / backtest / live / screen
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
- ETF 走独立接口与缓存：池用 `fund_etf_category_sina`、历史用 `fund_etf_hist_sina`，函数在 `data/etf_source.py`，缓存放 `data/etf/bars/`（与个股隔离）。东财 ETF 源在部分网络下不可用，不要改回去。
- **已知限制**：新浪 ETF 历史是**不复权**价，ETF 分红会造成除息跳空；做长周期指标时要知晓这一偏差。

### 筛选层
- 入口：`qtrader screen`（CLI）或 `qtrader.screening.run_screen` / `run_out_of_sample`（代码）。
- **周期维度**：`--period weekly`（默认，面向以周为最小决策单位的中期波段）或 `daily`。指标在所选周期上计算，年化因子取 252（日线）/ 52（周线）。两套预设见 `FunnelConfig.for_period`：
  - 周线：窗口 5 年、zigzag 阈值 12%、周期振幅 ≥ 4%、水下 ≤ 104 周、入场回撤 ≥ 20%
  - 日线：窗口 3 年、zigzag 阈值 15%、周期振幅 ≥ 2%、水下 ≤ 504 日、入场回撤 ≥ 15%
- 四层漏斗（阈值集中在 `FunnelConfig`）：
  - 第 0 层 流动性：成交额 > 1 亿、换手率区间（周线放宽到 1%~30%），剔除 ST / 退市 / 北交所
  - 第 1 层 波段弹性：年化波动 25%~50%、周期振幅下限、年均波段次数 ≥ 3
  - 第 2 层 可做性：最大回撤 < 45%、最长水下根数上限
  - 第 3 层 入场时点：距 52 周高点回撤 ≥ 门槛（周线 20% / 日线 15%）
- `trend_ratio`（周期收盘站上周期均线的占比）、`autocorr_1`、`variance_ratio_5` 只参与打分，**不作为硬门槛**。
- 个股 `max_candidates` 按成交额降序截断，**会偏向高波动投机标的**，通过率偏低；需要更全面候选就把它调大。
- **ETF 特有限制**：没有可用的 ETF 流动性快照（新浪 ETF 分类接口成交额恒为 0，东财不可达），因此第 0 层不做流动性过滤，改为拉取历史后用「成交量 × 收盘价」判定成交额；`max_candidates` 按代码排序截断（**不代表流动性排序**），做全市场 ETF 筛选要调大或直接用 `--symbols`。
- `run_out_of_sample` 做样本外验证：前段窗口筛选、后段窗口检验，返回 `survived`。
- `metrics.py` 只依赖行情序列、不含未来函数；新增指标必须同步补纯函数测试（不联网）。
- 评分是候选集内的百分位，只用于组内排序，不要跨批次比较。

### 配置与回测
- 费率、滑点、初始资金、T+1 等一切配置进 `settings.py` 的 `Settings`，经 `get_settings()` 读取；环境变量统一 `QT_` 前缀。不要硬编码这些数值。
- **费率按资产类型生效**：`Settings.asset_type`（`stock` / `etf`）经 `fee_params()` 决定口径——个股收佣金万 3 + 印花税千 0.5（仅卖出）+ 过户费十万分之一；**ETF 免印花税与过户费**。回测时还会显式声明资产类型，ETF 使用 0.001 的最小变动价位（个股 0.01）。
- 印花税默认 `0.0005`（2023-08-28 起由 0.1% 减半）。改动费率前按自己的券商口径核对，不要沿用旧值。
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