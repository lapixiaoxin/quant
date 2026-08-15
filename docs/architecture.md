# 系统架构

## 总览

项目采用模块化单体。它保持本地运行和单命令运维，同时通过协议、注册表和分层配置支持 ETF、股票、指数以及不同研究与通知方式。

```mermaid
flowchart LR
    T[launchd / CLI / 飞书命令] --> I[interfaces 交互入口]
    I --> A[application 用例编排]
    A --> D[domain 领域模型与策略]
    M[行情源] --> X[infrastructure 适配器]
    X --> A
    A --> F[文件与 SQLite 仓储]
    A --> N[自动化与通知路由]
    F --> P[data/latest schema v3]
    F --> H[data/history 日线历史库]
    P --> R[TRAE / TraeCode CLI]
    R --> O[个性化研究报告]
    O --> K[research 研究知识库]
```

依赖只能从外向内。领域层不知道 HTTP、TOML、文件路径、飞书或 TRAE 的存在。

## 行为配置模型

项目不把“ETF 都一样”或“同类标的都一样”写死，而是使用四类可复用画像和单标的覆盖。

```mermaid
flowchart TD
    PT[product_types 产品大类默认值]
    SP[strategy_profiles 策略实现与参数]
    RP[research_profiles 研究内容画像]
    NP[notification_policies 事件路由]
    NC[notification_channels 发送机制]
    IN[instruments 单个标的差异]
    EP[最终执行计划]

    PT --> SP
    PT --> RP
    PT --> NP
    NP --> NC
    PT --> EP
    IN -->|覆盖或追加| EP
    SP --> EP
    RP --> EP
    NP --> EP
```

### 产品大类

`product_types.<type>` 定义默认策略画像、研究画像、通知策略和历史窗口。它表达 ETF、股票、指数等类别的共性，不保存单个代码的特殊要求。

### 策略画像

`strategy_profiles.<id>` 绑定代码中的稳定 `strategy_id` 和少量业务阈值。产品大类或标的引用画像，因此同一算法可以有不同参数组合；评分结构等稳定实现仍留在代码和测试中。

一个标的可以引用多个策略画像。程序独立输出多个 assessment，不对冲突评分做没有依据的平均。

### 研究画像

`research_profiles.<id>` 定义：

- 使用哪个研究 Skill。
- 报告章节和关注项。
- 来源优先级与来源数量上限。
- 对表达和分析方法的约束。

单个标的通过 `research_focus` 和 `research_instructions` 追加独有需求，也可以直接覆盖为专属研究画像。

### 通知策略与通道

`notification_policies.<id>` 定义哪些业务事件发送到哪些通道，以及标题模板。`notification_channels.<id>` 定义飞书等实际机制和凭证入口。

这种分离允许同类产品使用不同推送频率、目标和方式，也允许一个通道被多个策略复用。应用层只发送业务事件，不直接选择飞书。

## 一次研究任务的数据流

```mermaid
sequenceDiagram
    participant C as CLI/定时任务
    participant S as Settings
    participant A as MonitoringService
    participant P as 行情适配器
    participant G as 策略注册表
    participant H as SQLite 历史仓储
    participant R as 文件仓储
    participant T as TRAE Skill
    participant N as NotificationService

    C->>S: 解析产品默认值与标的覆盖
    C->>A: prepare(symbol)
    A->>P: fetch(instrument, history_days)
    P-->>A: MarketBundle
    A->>H: 幂等保存标准化日线
    A->>A: 计算通用指标
    loop 每个策略画像
        A->>G: evaluate(strategy, parameters)
        G-->>A: StrategyAssessment
    end
    A->>R: 保存 schema v3 数据包与提示
    T->>R: 读取 research_plan 和 assessments
    T->>R: 保存个性化报告
    opt 用户明确要求推送
        C->>N: send(symbol, agent_report)
        N->>S: 读取 notification_policy
        N-->>C: 路由到配置通道
    end
```

## 无人值守自动化

`AutomationService` 提供两个运行模式：

- `base`：直接调用 `MonitoringService`、基础报告渲染和通知服务。
- `traecli`：使用 TraeCode CLI 官方非交互 `-p` 模式执行项目命令
  `/instrument-daily <symbol> [push]`。

当 `traecli` 二进制不存在且 `fallback_to_base = true` 时，任务降级为
`base`。如果 Agent 已经启动但返回失败，不再自动发送基础报告，避免一次任务产生重复消息。

工作日 LaunchAgent 调用 `./quant automate --all`。执行时间读取
`app.report_time`，是否发送由 `[automation]` 决定。

macOS 服务不直接运行 Documents 等受隐私保护目录内的开发仓库。安装脚本会将
最小运行副本和 `0600` 本机配置同步到 `~/.local/share/quant-monitor`，
LaunchAgent 只访问该目录；重新安装负责同步新版本，运行数据继续保留。

## 飞书远程命令

远程入口使用 `lark-cli event +subscribe` 建立 Bot WebSocket 长连接，只订阅
`im.message.receive_v1`。交互层依次执行：

1. 消息去重。
2. 发送人或群聊白名单校验。
3. 命令前缀与固定参数校验。
4. 调用监控或自动化应用服务。
5. 通过 lark-cli 回复原消息。

支持的命令固定为 `status`、`analyze`、`base`、`prepare`、
`dashboard` 和 `help`。远程文本不会进入 Shell。

## schema v3 数据契约

```text
as_of              带时区采集时间
instrument         身份和最终解析后的画像引用
quote              当前行情快照
metrics            与策略无关的确定性指标
assessments        各策略画像独立给出的基线判断
research_plan      最终研究章节、关注点、来源与指令
notification_plan  无敏感信息的事件和通道路由摘要
portfolio          可选持仓上下文
data_quality       来源、样本量、时间戳和限制
```

`data/latest` 是最终执行计划的运行产物，不是配置源。修改行为应编辑 TOML 配置并重新运行 `prepare`，不要手改 JSON。

## 历史数据与回测边界

每次行情采集成功后，`MonitoringService` 通过 `MarketHistoryRepository`
把标准化日线写入 `data/history/market.sqlite3`。SQLite 负责日期范围查询、
去重和事务；schema v3 JSON 快照继续负责还原单次研究任务，两者职责不同。

历史库当前固定保存前复权日线、来源和采集时间。按“标的代码 + 交易日”幂等更新；
降级源缺少成交额或换手率时，不用零值覆盖已有的非零字段。安装脚本不会删除
运行目录中的历史库。

回测代码位于 `domain/backtesting/`，当前交付的是领域契约而不是完整引擎：

- `BacktestSpecification` 冻结模型版本、参数指纹、区间、成本、滑点和基准。
- `BacktestSignalModel` 只使用当日及以前的数据生成长线目标仓位。
- `BacktestResult` 约束权益曲线、指标和限制说明。
- 当前 `AnalysisStrategy` 只表达研究关注度，不可直接作为买卖信号回测。

未来撮合、参数优化和样本外评估由应用层编排，数据从历史仓储协议读取，
领域层不得直接导入 `sqlite3`。

## 研究知识库

`research/` 保存人与 Agent 讨论后的整理结果，不复制运行数据：

- `research/private/`：具体标的、持仓和个人计划，默认被 Git 忽略。
- `research/library/`：经过复核与脱敏的跨标的经验，可随代码版本管理。
- `research/methods/`：数据、策略和回测方法的 HTML 报告。

研究记录必须区分事实和推断，并包含数据时间、来源、反例、风险和失效条件。

## TRAE 与 TraeCode CLI

- `.trae/skills/instrument-analyst` 是产品无关的研究执行器。
- `.trae/commands/instrument-daily.md` 是 TRAE 项目命令入口。
- `.traecli/commands/instrument-daily.md` 是 TraeCode CLI 的同语义适配器。

命令和 Skill 不再硬编码 ETF 内容。它们以 `research_plan.skill`、`sections`、`focus`、`source_priorities` 和 `instructions` 为准；通知以 `notification_plan` 为准。

## 核心边界

| 边界 | 当前实现 | 扩展方式 |
|---|---|---|
| 投资标的 | ETF、股票、指数统一模型 | 扩展 `InstrumentType` |
| 行情入口 | 东方财富失败后降级腾讯 | 实现 `MarketDataProvider` |
| 通用指标 | 收益、均线、回撤、波动、流动性 | 新增纯计算模块 |
| 策略 | `strategies/etf|stock|index` 产品子包 | 新增独立模块并注册 `AnalysisStrategy` |
| 回测 | 版本化输入、信号与结果契约 | 实现 `BacktestSignalModel` 和应用层执行器 |
| 研究 | schema 驱动的通用 Skill | 新增研究画像或专用 Skill |
| 通知 | 事件策略 + 飞书通道 | 实现 `NotificationChannel` |
| 存储 | 原子文件 + SQLite 日线仓储 | 实现对应仓储协议 |
| Agent | TraeCode CLI 非交互模式 | 实现 `ResearchAgentRunner` |
| 入口 | CLI、launchd、TRAE、飞书 | 调用应用用例，禁止复制业务 |

## 技术决策

### 模块化单体而非服务化

当前数据量和并发不足以抵消服务化成本。协议边界允许未来替换行情、存储、通知或入口，而无需重写领域逻辑。

### SQLite 与 JSON 并用

JSON 对单次研究透明、可审计，但不适合跨年范围查询和回测取数。SQLite 是当前
日线历史主存储：无需服务进程，支持事务、索引和备份，复杂度适合个人中长线研究。
只有多设备并发写入、多人远程访问或分钟级海量数据出现后，才评估 PostgreSQL
或专用时序存储。

### 策略、研究和通知相互独立

策略回答“确定性规则怎么看”，研究画像回答“还需要了解什么”，通知策略回答“什么事件发到哪里”。三者可独立复用和覆盖，避免单个大配置对象或产品专用分支。

### 远程入口不开放 Shell

未来飞书或 HTTP 命令必须映射为经过认证的白名单应用事件，并记录审计信息。任何外部输入都不能直接成为 Shell。

## 演进触发条件

- 标的和跨年数据增长：继续使用 SQLite，增加索引、质量检查和增量同步。
- 多设备同时写入或多人远程访问：评估 PostgreSQL 与单写者服务。
- 分钟级海量行情：重新评估分区、列式文件或时序存储。
- 开放外网访问：先实现认证、授权、审计和限流。
- 策略影响真实资金动作：增加回测、版本冻结、审批和人工确认。
- 通知通道增加：拆分 `infrastructure/notifications` 为独立适配器包。
