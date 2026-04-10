# nanobot 系统架构深度分析

## 1. 文档目的与范围

本文基于仓库代码实现，对 nanobot 做面向架构评审的深度分析，重点覆盖：

- 模块边界与职责划分
- 关键调用链与数据流
- 状态与持久化模型
- 并发模型与容错机制
- 扩展点与工程约束
- 关键风险与改进优先级

目标读者：需要进行技术评审、稳定性评估或二次开发的工程团队。

## 2. 总体架构概览

nanobot 是一个事件驱动的轻量级 Agent 运行时，核心是 消息总线 + Agent 循环 + 工具执行 + 多渠道适配器的组合架构。

系统有两种主要运行形态：

- nanobot agent：CLI 直连模式，单次或交互式对话
- nanobot gateway：长驻服务模式，接入聊天渠道并运行 Cron 和 Heartbeat

核心技术特征：

- 统一消息模型：InboundMessage / OutboundMessage
- 异步队列驱动：asyncio.Queue
- 统一 LLM 抽象：LLMProvider（当前主要实现为 LiteLLMProvider）
- 工具可插拔：Tool + ToolRegistry
- 文件化持久化：config/session/memory/cron

## 3. 组件清单与边界图谱

~~~mermaid
flowchart LR
    U[用户或聊天平台] --> CH[Channels]
    CH --> BIN[MessageBus Inbound]
    BIN --> AG[AgentLoop]

    AG --> CTX[ContextBuilder]
    AG --> SES[SessionManager]
    AG --> TOOLS[ToolRegistry]
    AG --> LLM[LiteLLMProvider]

    TOOLS --> FS[文件工具]
    TOOLS --> SH[Shell 执行工具]
    TOOLS --> WEB[Web 搜索与抓取]
    TOOLS --> MSG[message 工具]
    TOOLS --> SP[spawn 工具]

    SP --> SUB[SubagentManager]
    SUB --> BIN

    AG --> BOUT[MessageBus Outbound]
    BOUT --> CH

    GW[gateway 运行时] --> CRON[CronService]
    GW --> HB[HeartbeatService]
    CRON --> AG
    HB --> AG

    WA[Node WhatsApp Bridge] <--> CH
~~~

### 3.1 关键边界

- 编排边界：nanobot/cli/commands.py 负责组装运行时组件。
- 领域边界：agent 关注理解、工具调用与回答，channels 关注协议适配。
- 基础设施边界：bus 负责传递，session/memory/cron 负责状态持久化。
- 外部进程边界：WhatsApp 协议通过 bridge 独立 Node 进程处理。

## 4. 入口与运行模式

### 4.1 入口

- 模块入口：nanobot/__main__.py
- CLI 定义：nanobot/cli/commands.py

### 4.2 运行模式

- onboard：初始化 ~/.nanobot/config.json、workspace 模板和 memory 目录。
- agent：加载配置后直接调用 AgentLoop.process_direct。
- gateway：启动 MessageBus、AgentLoop、ChannelManager、CronService、HeartbeatService。
- channels login：为 WhatsApp Bridge 准备 Node 侧依赖并启动桥接。

## 5. 关键流程与调用链

### 5.1 CLI 直连模式时序

~~~mermaid
sequenceDiagram
    participant CLI as CLI
    participant CFG as ConfigLoader
    participant AG as AgentLoop
    participant LLM as LiteLLMProvider
    participant TO as ToolRegistry

    CLI->>CFG: load_config()
    CLI->>AG: process_direct(message)
    AG->>AG: 构建系统上下文与会话历史
    AG->>LLM: chat(messages, tools)

    alt LLM 返回 tool_calls
        AG->>TO: execute(name, args)
        TO-->>AG: tool result
        AG->>LLM: 追加 tool 结果后再次 chat
    end

    LLM-->>AG: final content
    AG->>AG: 保存 session
    AG-->>CLI: 返回响应
~~~

### 5.2 Gateway 渠道闭环时序

~~~mermaid
sequenceDiagram
    participant CH as Channel
    participant BUS as MessageBus
    participant AG as AgentLoop
    participant CM as ChannelManager

    CH->>BUS: publish_inbound(InboundMessage)
    AG->>BUS: consume_inbound()
    AG->>AG: LLM + 工具迭代
    AG->>BUS: publish_outbound(OutboundMessage)
    CM->>BUS: consume_outbound()
    CM->>CH: send(outbound)
~~~

### 5.3 Subagent 后台任务时序

~~~mermaid
sequenceDiagram
    participant AG as Main Agent
    participant SP as spawn tool
    participant SUB as SubagentManager
    participant BUS as MessageBus

    AG->>SP: spawn(task, label)
    SP->>SUB: 创建后台 asyncio 任务
    SUB->>SUB: 独立执行子循环与工具调用
    SUB->>BUS: publish_inbound(system announce)
    AG->>BUS: 读取 system 消息
    AG->>AG: 二次总结后回复用户
~~~

### 5.4 Cron 与 Heartbeat 触发时序

~~~mermaid
sequenceDiagram
    participant CR as CronService
    participant HB as HeartbeatService
    participant AG as AgentLoop
    participant BUS as MessageBus
    participant CH as Channel

    loop 定时检查
        CR->>CR: 计算到期任务并执行 on_job
        CR->>AG: process_direct(job.payload.message)
        alt 需要投递
            CR->>BUS: publish_outbound(channel,to,content)
            CH->>BUS: consume_outbound()
        end

        HB->>HB: 读取 HEARTBEAT.md
        alt 有可执行内容
            HB->>AG: process_direct(HEARTBEAT_PROMPT)
        else 无任务
            HB->>HB: 跳过
        end
    end
~~~

## 6. 状态与存储梳理

### 6.1 路径与数据

- 配置文件：~/.nanobot/config.json
- 工作目录：agents.defaults.workspace（默认 ~/.nanobot/workspace）
- 会话：~/.nanobot/sessions/*.jsonl
- 记忆文件：workspace/memory/MEMORY.md
- 每日记忆：workspace/memory/YYYY-MM-DD.md
- 定时任务：~/.nanobot/cron/jobs.json
- Telegram 媒体缓存：~/.nanobot/media/*

### 6.2 状态模型特征

- 强文件化、弱服务化：无需外部数据库，但多实例能力有限。
- 队列与缓存是进程内状态：重启会丢失未落盘的在途消息。
- Cron 和 Heartbeat 假设单实例所有权：未提供分布式协调机制。

## 7. 并发模型与容错机制

### 7.1 并发模型

- 主体基于 asyncio。
- 并发任务来源：Agent 主循环、出站分发循环、Cron 定时器、Heartbeat 循环、Subagent 后台任务。
- Feishu 使用线程回调与主事件循环桥接。

### 7.2 容错机制现状

已有机制：

- 多处 try/except 阻断局部异常扩散
- Agent 工具迭代有 max_iterations 上限
- Tool 执行前进行参数 schema 校验
- WhatsApp 渠道具备重连逻辑

缺口：

- 无统一重试和退避策略
- 无死信队列
- 无全局幂等键体系（Feishu 仅本地消息去重缓存）
- 无持久消息队列

## 8. 扩展点与约束

### 8.1 新增工具

流程：

1. 在 nanobot/agent/tools 下实现 Tool 子类
2. 定义 name、description、parameters、execute
3. 在 AgentLoop._register_default_tools 注册

约束：

- 返回值要求为字符串，复杂结构需自行序列化。
- 工具权限模型目前由工具自身负责，缺少统一策略层。

### 8.2 新增 Provider

流程：

1. 扩展 ProvidersConfig 与配置映射
2. 在 schema.py 的 provider 选择和 api_key/api_base 解析逻辑中接入
3. 扩展 LiteLLMProvider 归一化逻辑，或新增 LLMProvider 实现

约束：

- Provider 选择逻辑与 CLI 初始化存在耦合，接入新 provider 需要跨层改动。

### 8.3 新增渠道

流程：

1. 实现 BaseChannel（start、stop、send）
2. 在 ChannelManager._init_channels 注入
3. 增加 schema 配置项

约束：

- 出站路由依赖 msg.channel 精确匹配，不支持动态路由策略。

### 8.4 Bridge 依赖与替代

当前 WhatsApp 依赖 Node + Baileys，Python 与 Node 通过 websocket 通信。

替代方向：

- 保留桥接但抽象协议层，允许替换为其他 WhatsApp 网关
- 改为远程桥接服务，降低本机 Node 依赖

## 9. 架构风险清单（评审视角）

### P0

1. 文件工具默认可访问任意路径
- read_file/write_file/edit_file 未默认限制到 workspace。
- 风险：提示词注入或模型误判会造成敏感路径读写。

2. Shell 安全策略以 denylist 为主
- 正则黑名单可被命令变体绕过。
- 风险：本机高危命令执行。

### P1

3. 直连模式 session_key 使用不一致
- process_direct(session_key=...) 参数未完整进入会话键路由。
- 风险：上下文连续性与会话持久化行为偏离预期。

4. 出站分发存在双路径潜在分叉
- MessageBus 内有订阅分发能力，同时 ChannelManager 也在消费出站队列。
- 风险：后续演进中行为分叉、维护成本上升。

5. 定时调度的多实例一致性不足
- 单进程 timer + 文件存储，无锁与主从机制。
- 风险：多实例场景可能重复触发或漏触发。

### P2

6. 可观测性不足
- 以日志为主，无指标与追踪。
- 风险：线上故障定位慢，难以量化 SLA/SLO。

7. Skill frontmatter 解析鲁棒性一般
- 当前解析逻辑非完整 YAML 解析器。
- 风险：复杂 metadata 下可能静默解析错误。

## 10. 改进建议与优先级

1. 默认启用 workspace 作用域策略
- 为文件工具和 shell 工具提供统一路径策略层。

2. Shell 从 denylist 升级到策略化 allowlist
- 按环境区分策略：开发模式与生产模式。

3. 修复直连会话键一致性
- 保证 --session 和持久化 session key 一致映射。

4. 统一出站分发架构
- 保留一种机制，清理冗余路径。

5. 增加运行时遥测
- 增加 provider 延迟、tool 失败率、队列长度、cron 执行状态指标。

6. 增加端到端集成测试
- 覆盖 CLI 直连、gateway 闭环、cron、heartbeat、spawn announce。

## 11. 运行拓扑建议

### 11.1 个人本地使用

- 单进程 nanobot gateway
- 文件持久化足够，运维成本最低

### 11.2 团队内部机器人

- Python 主服务 + Node WhatsApp Bridge 分离部署
- 引入进程守护与日志聚合

### 11.3 多实例生产化

当前架构不建议直接 active-active 上线，需要先补齐：

- 持久消息队列
- 分布式锁或主节点选举
- 调度所有权管理
- 统一可观测性体系

## 12. 结论

nanobot 当前架构在可读性、轻量化、快速迭代上实现较好，适合个人自动化与研究场景。

若目标升级为高可靠多实例服务，优先级最高的工程化方向是：

- 执行安全收敛
- 会话与调度一致性
- 分发路径收敛
- 可观测性补齐
