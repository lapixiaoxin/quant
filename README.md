# qtrader

基于 **akfamily** 生态的 A 股量化程序骨架：**AKShare 取数 + AKQuant 引擎**，同一份策略代码同时支持**回测**与**实盘**。

## 它和 akfamily 各组件的关系

| 组件 | 在本项目中的角色 |
|---|---|
| `akshare` | 数据源：抓取股票/指数/基金等行情（本项目已封装日线 + 本地 Parquet 缓存） |
| `akquant` | 引擎：Rust 撮合内核 + Python 策略 API，负责回测、风控、实盘事件循环 |
| `aktools` | （可选）把 AKShare 暴露成 HTTP API，供非 Python 进程使用 |
| `akbroker` / `akracer` / `awesome-data` / `quant` | 教学、动态库补丁、资源清单，本项目不直接依赖 |

## 目录结构

```
src/qtrader/
├── settings.py            # 配置：费率、路径、实盘通道参数
├── data/                  # 数据层：AKShare 采集 + Parquet 缓存
│   ├── akshare_source.py
│   └── store.py
├── strategy/              # 策略层（继承 akquant.Strategy）
│   └── ma_cross.py
├── backtest/              # 回测层：run_backtest 封装 + 报告
│   └── runner.py
├── live/                  # 实盘层：run_live 封装（paper / broker_live）
│   └── runner.py
└── cli.py                 # 命令行入口
```

## 安装

依赖版本由 `uv.lock` 钉死，务必用 `uv sync` 安装（不要用 `uv pip install`，会绕过锁文件）：

```bash
uv sync                     # 按 uv.lock 创建/对齐 .venv，含 dev 依赖
cp .env.example .env        # 按需修改
```

> 回测结果对依赖版本敏感。`uv.lock` 保证任何机器、任何时候重建环境都能复现同样的回测数值。
> 升级依赖时用 `uv lock --upgrade-package akshare` 单点升级，并重跑 `pytest` 与对账测试再提交。

## 使用

```bash
# 1) 抓取并缓存日线
qtrader data-sync --symbols sh600000,sz000001 --start 20230101 --end 20240630

# 2) 回测并生成 HTML 报告
qtrader backtest --symbols sh600000 --start 20230101 --end 20240630 --report reports/bt.html

# 3) 启动实盘/仿真会话（模式由 QT_LIVE_TRADING_MODE 决定）
qtrader live --symbols sh600000 --start 20230101 --end 20231231 --duration 30s
```

## 回测 vs 实盘

- **同一策略代码**：`MaCrossStrategy` 既能在 `run_backtest` 跑，也能在 `run_live` 跑。
- **paper 模式（默认）**：行情用 `replay` 回放本地数据，撮合走引擎内置模拟执行，**无需真实柜台**，用于验证全链路。
- **broker_live 模式**：接真实柜台。CTP 为引擎内置原生适配；QMT/PTrade 在开源包内仅为占位 stub，需另装券商插件或 SDK。
  ```bash
  QT_LIVE_TRADING_MODE=broker_live
  QT_LIVE_MARKET_BROKER=ctp
  QT_LIVE_TRADER_BROKER=ctp
  QT_MD_FRONT=tcp://... QT_TD_FRONT=tcp://... QT_BROKER_ID=... QT_USER_ID=... QT_PASSWORD=...
  ```

## 写自己的策略

在 `src/qtrader/strategy/` 下新增一个继承 `akquant.Strategy` 的类：

```python
from akquant import Strategy

class MyStrategy(Strategy):
    warmup_period = 20

    def on_start(self):
        self.set_history_depth(21)   # 用 get_history 前必须先声明回溯长度

    def on_bar(self, bar):
        amount = 1000 if self.get_position(bar.symbol) == 0 else 0
        if amount:
            self.buy(symbol=bar.symbol, quantity=amount)
```

可调参数用**类体内联字段**声明（如 `fast = 5`），即可被参数优化框架直接扫描。

## 测试

```bash
.venv/bin/python -m pytest -q
```

## 边界提醒

- AKShare 数据仅供学术研究，商用请自行评估数据源风险；目标站点改版会导致接口失效，需保持升级。
- 本项目的费率/滑点/风控参数在 `Settings` 中显式配置，回测结果对参数敏感，落地前请用你自己的券商口径复核。
- 实盘涉及真实资金，务必先在 `paper` 模式充分验证，再小资金灰度。
