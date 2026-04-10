# 海参育苗车间无人化个人助理 一期开发规格书（v1.3 对齐版）

## 1. 文档目标

本文是一期试点的冻结规格，作为开发与验收唯一基线。目标是：

- 在单车间 8 池实现 人决策、助理执行的可运行闭环
- 采用双内核双链路架构，兼顾智能编排与执行安全
- 不修改 nanobot 核心代码，完成可持续演进的集成实施
- 一期先以接口级数字孪生（非 3D）跑通闭环，再灰度接入真实设备


## 2. 一期范围与冻结参数

### 2.1 试点范围

- 车间数量：1
- 池数：8（全量 15 池，先试点 8 池）
- 一期运行模式：sim + shadow 为主，real 按准入门槛灰度开启

### 2.2 采样与任务周期

- 水质采样：30 秒
- 投喂周期：3 小时
- 清粪周期：24 小时

### 2.3 水质阈值与最优区间

- DO：告警 <= 5 mg/L，危险 <= 3 mg/L，最佳 5-8 mg/L
- pH：告警 < 7.5，危险 < 6.5，最佳 7.5-8.5
- 温度：告警 > 28，危险 > 31，最佳 23-29

策略口径：

- 温度 28-29 区间记为告警，不触发危险联锁
- DO 与 pH 的高侧偏离先作为优化提醒，不进入安全联锁

### 2.4 审批与降级

- 高风险动作：本人飞书审批
- 二次提醒：T+2 分钟
- 审批超时：T+3 分钟，触发降级执行
- 降级规则（已冻结）：
- 换水未确认：不换水，仅提升增氧并告警
- 大剂量投喂未确认：降级为基准量 60%
- 其他高风险动作超时：默认不执行并告警

### 2.5 部署与可用性

- 部署模式：边缘 + 云
- 消息总线：边缘本地 MQTT Broker（主），联网后同步云端
- 云策略下发：必须边缘二次审核
- 断网模式：只保命运行
- 断网清粪：暂停
- 断网投喂：降级为 60%
- 告警时效目标：<= 60 秒

### 2.6 视觉能力

- 每池相机：俯拍 1 + 侧拍 1
- 视频接入：RTSP 或 WebRTC
- 推理方式：边缘主机实时 YOLO 检测
- 输出指标：计数、个头分布、活跃度、饥饿度
- 投喂误差容忍：±10%

### 2.7 审计要求

- 必记字段：决策理由、模型版本、审批轨迹、执行回执、trace_id

### 2.8 接口级数字孪生边界（一期冻结）

- 不做 3D 场景，不做复杂物理仿真，仅仿真接口行为与时序
- 仿真对象仅包含两类接口：传感器上报接口、执行命令接口
- 传感器最小字段：do_mg_l（由设备字段 rjy 映射）、pH、temp_c、relay_state
- 执行最小能力：接收标准命令并映射到底层 relay 控制，返回回执
- 场景库最小集合：normal、threshold_breach、device_timeout、network_offline


## 3. 架构总则：双内核 + 双链路

### 3.1 双内核

- 智能编排核（Orchestrator）：目标管理、任务拆解、Agent 分派、多轮重规划、问答解释
- 安全控制核（Safety Kernel）：风险裁决、审批门控、降级策略、命令状态机、执行核验

职责边界：

- 编排核可以提出方案，但不直接控制设备
- 控制核是设备动作的唯一放行入口

### 3.2 双链路

- 读链路：编排核 -> 感知 Agent -> 评估 Agent -> 告警/报告
- 写链路：编排核 -> 决策计划 -> 安全控制核 -> 执行 Agent -> 核验/审计
- 写链路在 sim/shadow/real 三种模式使用同一命令契约


## 4. Agent 职责矩阵

| Agent | 职责 | 输入 | 输出 | 权限边界 |
|---|---|---|---|---|
| BioPerceptionAgent | 生物感知（计数、个头、活跃、饥饿） | 视频流、标定参数 | 生物感知事件 | 只读，不可控设备 |
| EnvPerceptionAgent | 环境感知（DO/pH/温度/设备心跳） | 传感器流、设备状态 | 环境感知事件 | 只读，不可控设备 |
| StateAssessmentAgent | 融合评估（normal/warn/danger） | 生物与环境事件、阈值规则 | 池状态事件 | 只评估 |
| PolicyDecisionAgent | 生成动作计划与优先级 | 池状态、策略、历史结果 | 决策计划事件 | 只提案，不放行动作 |
| SafetyGuardianAgent | 审批/联锁/降级/超时处理 | 决策计划、审批状态、风险规则 | 可执行命令 | 唯一放行入口 |
| ExecutionAgent | 设备执行与回执 | 可执行命令 | 执行结果事件 | 不可绕过 Safety |
| VerificationAgent | 执行后核验与异常归档 | 回执、回读数据 | 核验事件 | 只核验 |
| AuditAgent | 全链路审计 | 全部事件 | 审计记录 | 强制记录 |
| OrchestratorAgent（nanobot） | 交互、编排、问答 | 用户意图、系统事件 | 工单、说明、报告 | 编排权限，不含设备执行权限 |


## 5. 消息契约（统一事件模型）

### 5.1 Envelope

~~~json
{
  event_id: uuid,
  trace_id: uuid,
  event_type: string,
  schema_version: v1,
  mode: sim|shadow|real,
  ts: 2026-02-06T10:00:00Z,
  site_id: site-001,
  workshop_id: ws-001,
  pool_id: pool-01,
  source: service-name,
  payload: {}
}
~~~

### 5.2 核心主题

- telemetry.water_quality.v1
- perception.bio.v1
- assessment.pool_state.v1
- decision.action_plan.v1
- approval.request.v1
- approval.reply.v1
- command.request.v1
- command.result.v1
- verification.result.v1
- alert.event.v1
- audit.event.v1

### 5.3 字段最小要求

- 感知事件：pool_id、ts、confidence、model_version、sensor_health
- 决策事件：plan_id、actions、risk_level、decision_explanation、model_version
- 命令事件：command_id、idempotency_key、action_type、target、params、preconditions、deadline_sec、degrade_policy、dry_run
- 审批事件：approval_id、timeout_sec、remind_at_sec、decision
- 审计事件：trace_id、operator、reason、model_version、receipt
- 水质映射：设备上报字段 rjy 统一映射为 do_mg_l（单位 mg/L）


## 6. 一期接口（最小可用）

### 6.1 HTTP API 清单

- POST /api/v1/telemetry/water-quality
- POST /api/v1/perception/bio
- GET /api/v1/pools/{pool_id}/state
- POST /api/v1/decisions/plan
- POST /api/v1/approvals/requests
- POST /api/v1/approvals/{approval_id}/confirm
- POST /api/v1/approvals/{approval_id}/reject
- POST /api/v1/commands
- GET /api/v1/commands/{command_id}
- GET /api/v1/audits

### 6.2 HTTP 契约示例（一期冻结）

示例 A：传感器上报（设备原始字段）

~~~json
POST /api/v1/telemetry/water-quality
{
  "site_id": "site-001",
  "workshop_id": "ws-001",
  "pool_id": "pool-01",
  "mode": "sim",
  "ts": "2026-02-07T10:00:00Z",
  "payload": {
    "relay": 0,
    "ph": 7.82,
    "hzd": 3,
    "rjy": 5.91,
    "temp": 24.70
  }
}
~~~

示例 B：平台标准化后的水质事件（内部统一）

~~~json
{
  "event_id": "0c9f59e8-f4f8-4d5a-b8f6-68a9ebf2d2b1",
  "trace_id": "8e2f4462-d2f6-43e3-a9f4-8e7ca6136f9a",
  "event_type": "telemetry.water_quality.v1",
  "schema_version": "v1",
  "mode": "sim",
  "ts": "2026-02-07T10:00:00Z",
  "site_id": "site-001",
  "workshop_id": "ws-001",
  "pool_id": "pool-01",
  "source": "edge-gateway-01",
  "payload": {
    "do_mg_l": 5.91,
    "ph": 7.82,
    "temp_c": 24.70,
    "relay_state": 0,
    "sensor_health": "online",
    "raw": {
      "rjy": 5.91,
      "temp": 24.70
    }
  }
}
~~~

示例 C：标准命令下发（上层统一，不直绑 relay 细节）

~~~json
POST /api/v1/commands
{
  "command_id": "cmd-20260207-0001",
  "idempotency_key": "pool-01-feed-202602071000",
  "trace_id": "8e2f4462-d2f6-43e3-a9f4-8e7ca6136f9a",
  "mode": "shadow",
  "action_type": "feed",
  "target": {
    "site_id": "site-001",
    "workshop_id": "ws-001",
    "pool_id": "pool-01"
  },
  "params": {
    "ratio": 0.60,
    "duration_sec": 120
  },
  "preconditions": {
    "min_do_mg_l": 5.0,
    "max_temp_c": 29.0
  },
  "deadline_sec": 180,
  "degrade_policy": "feed_60_percent_on_timeout",
  "dry_run": true
}
~~~

示例 D：命令执行回执（sim/shadow/real 通用）

~~~json
{
  "command_id": "cmd-20260207-0001",
  "trace_id": "8e2f4462-d2f6-43e3-a9f4-8e7ca6136f9a",
  "mode": "shadow",
  "status": "Executed",
  "result_code": "OK",
  "started_at": "2026-02-07T10:00:02Z",
  "finished_at": "2026-02-07T10:00:07Z",
  "receipt": {
    "adapter": "relay-adapter-v1",
    "mapped_action": "relay=1",
    "simulated_latency_ms": 520
  }
}
~~~

MQTT 主题（边缘本地 Broker）：

- hatchery/{site_id}/{pool_id}/telemetry
- hatchery/{site_id}/{pool_id}/perception
- hatchery/{site_id}/{pool_id}/command/request
- hatchery/{site_id}/{pool_id}/command/result
- hatchery/{site_id}/{pool_id}/alert
- hatchery/{site_id}/{pool_id}/audit

### 6.3 MQTT 传输约束

- `telemetry`、`perception`、`command/request`、`command/result`：QoS 1
- `alert`：QoS 1，需支持重复投递去重
- `audit`：QoS 1，写入失败必须重试
- 所有主题默认 `retain=false`

### 6.4 action_type 枚举（一期冻结）

| action_type | 含义 | params 最小字段 | 默认风险级别 | 一期 relay 适配 |
|---|---|---|---|---|
| feed | 执行投喂 | ratio、duration_sec | medium/high（按剂量） | `relay=1` 持续 `duration_sec`，结束后 `relay=0` |
| aerate_up | 提升增氧 | duration_sec | medium | `relay=1` 持续 `duration_sec`，结束后 `relay=0` |
| aerate_down | 降低增氧/停止增氧 | 无 | low | `relay=0` |
| sludge_clean | 清理池底粪便 | duration_sec | medium | `relay=1` 持续 `duration_sec`，结束后 `relay=0` |
| water_change | 换水 | ratio、duration_sec | high | `relay=1` 持续 `duration_sec`，结束后 `relay=0` |
| emergency_stop | 紧急停机 | reason | critical | 立即 `relay=0`，并进入 `EmergencyStop` |
| manual_override_on | 启用人工接管 | operator、reason | high | 冻结自动下发，保持当前 `relay` |
| manual_override_off | 解除人工接管 | operator | medium | 恢复自动链路；后续命令需新 `trace_id` |

说明：

- 一期底层执行器按当前设备能力仅支持 `relay` 0/1；上层保留标准 `action_type`，由 adapter 做语义映射
- `feed/aerate_up/sludge_clean/water_change` 在一期 relay 适配层共享同一执行通道，不允许并发执行
- 未识别 `action_type` 必须返回 `E_UNSUPPORTED_ACTION`

### 6.5 错误码与处理策略（一期冻结）

| result_code | HTTP 状态 | 含义 | 可重试 | 处理策略 |
|---|---|---|---|---|
| OK | 200 | 同步执行成功 | 否 | 进入后续核验 |
| ACCEPTED_ASYNC | 202 | 已受理，异步执行中 | 否 | 轮询 `GET /commands/{command_id}` |
| E_INVALID_PARAM | 400 | 参数不合法/缺失 | 否 | 修正参数后重提 |
| E_PRECONDITION_FAILED | 412 | 前置条件不满足 | 视场景 | 先调整环境再执行 |
| E_RISK_NOT_APPROVED | 403 | 高风险动作未审批通过 | 否 | 走审批或降级分支 |
| E_DUPLICATE_IDEMPOTENCY | 409 | 幂等键重复 | 否 | 复用已有结果 |
| E_MODE_FORBIDDEN | 409 | 当前 mode 不允许该动作 | 否 | 切换 mode 或调整策略 |
| E_UNSUPPORTED_ACTION | 422 | adapter 不支持该动作 | 否 | 升级 adapter 或修改动作 |
| E_DEVICE_OFFLINE | 503 | 设备离线 | 是 | 重试并触发告警 |
| E_DEVICE_TIMEOUT | 504 | 设备执行超时 | 是 | 触发降级/回退策略 |
| E_EXECUTION_FAILED | 500 | 设备回执失败 | 视场景 | 记录审计并人工确认 |
| E_INTERNAL | 500 | 系统内部错误 | 是 | 指数退避重试并告警 |

### 6.6 通用约束

- 高风险动作必须先拿到 approval 或进入 timeout-degrade 分支
- /commands 只接受 Safety Kernel 放行后的命令
- 同一 `idempotency_key` 的命令只能生效一次


## 7. 命令状态机（一期）

状态集合：

- Requested
- RiskChecked
- PendingApproval
- Approved
- Rejected
- TimedOut
- Degraded
- Dispatched
- Executing
- Executed
- Verified
- Failed
- ManualOverride
- EmergencyStop
- Cancelled
- Closed

关键流转：

1. Requested -> RiskChecked
2. 低中风险：RiskChecked -> Dispatched
3. 高风险：RiskChecked -> PendingApproval
4. 审批通过：PendingApproval -> Approved -> Dispatched
5. 审批拒绝：PendingApproval -> Rejected -> Closed
6. T+2：发送二次提醒（状态不变）
7. T+3：PendingApproval -> TimedOut -> Degraded -> Dispatched
8. 执行链路：Dispatched -> Executing -> Executed -> Verified -> Closed
9. 异常链路：任一阶段 -> Failed（触发告警与审计）
10. 人工接管：任一待执行/执行中状态 -> ManualOverride -> Cancelled -> Closed
11. 紧急停机：任一状态 -> EmergencyStop -> Closed
12. ManualOverride/EmergencyStop 后恢复自动执行，必须以新 trace_id 重新走 RiskChecked


## 8. 与 nanobot 的集成策略（不改核心）

冻结决策：一期不修改 nanobot 核心代码。

### 8.1 nanobot 角色

- 作为智能编排核与问答层
- 通过业务白名单工具调用外部 TaskCenter/Safety Kernel

### 8.2 实施方式

- 新建业务项目（建议独立仓库）
- 以依赖方式引入 nanobot（固定版本或固定 commit）
- 自定义 runner 实例化 AgentLoop 并注册业务工具
- 禁止通用 exec 直接控制设备

### 8.3 白名单业务工具

- dispatch_perception_task
- create_action_plan
- request_high_risk_approval
- submit_safe_command
- query_command_status
- query_pool_state
- generate_shift_report


## 9. 模块拆分（业务项目）

建议目录：

- hatchery/contracts
- hatchery/perception
- hatchery/assessment
- hatchery/policy
- hatchery/safety
- hatchery/execution
- hatchery/verification
- hatchery/audit
- hatchery/adapters
- hatchery/taskcenter
- hatchery/orchestrator_bridge


## 10. 一期 MVP 清单（防过度设计版）

### 10.1 必须项

- 设备健康心跳
- 命令幂等与防重复执行
- 标准命令模型（action_type + target + params）与 relay 适配
- 传感器异常值过滤
- 最小人工接管（停止自动执行开关）
- 最小审计链路（理由、模型版本、审批、回执）
- 8 池采样入库与阈值评估
- 飞书审批与 T+2/T+3 超时降级
- 两条已冻结降级策略
- 断网保命模式
- 接口级数字孪生（sim/shadow）闭环可运行
- 告警时效 <= 60 秒

### 10.2 延后项（不阻塞一期）

- 复杂模型治理体系
- 完整发布灰度平台
- 深度安全治理（分区/密钥轮换全量化）
- 复杂值班升级链路


## 11. 4 周任务清单

### 第 1 周

- 池配置与设备映射建模（含 sim/shadow/real 模式开关）
- 边缘 MQTT Broker 与基础 Topic 打通
- 传感器接口级孪生（DO/pH/温度/relay）与上报入库打通
- 基础告警与飞书通知
- 设备心跳与异常值过滤

验收：

- 8 池 30 秒采样在 sim 模式稳定运行 24 小时
- 单指标异常在 sim/shadow 模式 60 秒内可触达飞书
- telemetry 与 alert 主题可被稳定订阅与回放

### 第 2 周

- Safety Kernel 风险裁决与审批门控
- T+2 二次提醒与 T+3 超时降级
- 命令状态机与幂等执行（含 ManualOverride/EmergencyStop/Cancelled）
- 标准命令模型（action_type + target + params）到 relay 适配
- 两条降级规则联调（sim/shadow）

验收：

- 高风险动作在 sim/shadow 模式 100% 进入审批门控
- 超时分支自动降级可追溯，具备 trace_id 全链路审计
- 人工接管与紧急停机可触发并闭环

### 第 3 周

- 生物感知接入（RTSP/WebRTC 拉流 + 边缘实时 YOLO）
- 视觉事件入总线并参与状态评估（计数/个头分布/活跃度）
- 动态投喂计划联调（shadow）
- 断网保命联调（含清粪暂停、投喂 60%）

验收：

- 视觉到决策链路在 shadow 模式可运行并可回放
- 投喂闭环在 shadow 模式可运行
- 误差统计满足 ±10% 目标口径（shadow 统计）

### 第 4 周

- 全链路压测（审批超时、断网、设备回执异常、人工接管、紧急停机）
- Sim2Real 准入评估与灰度接入（先 1-2 池）
- 审计查询与日报问答
- 试运行问题清单与修复

验收：

- 告警时效、审计完整性、降级策略在 sim/shadow 达标
- 1-2 池 real 灰度运行满足准入门槛并可一键回退 shadow


## 12. 一期验收指标

- 告警时效：P95 <= 60s（统计窗口 >= 7 天，覆盖 sim/shadow 与灰度 real）
- 高风险审批覆盖率：100%（统计窗口内全部高风险命令）
- 超时降级准确率：>= 99.5%（统计窗口内 timeout 样本 >= 200）
- 审计关键字段完整率：>= 99.9%
- 断网保命策略执行成功率：>= 99%
- 投喂误差：<= ±10%（shadow + 灰度 real 统计口径）
- Sim2Real 准入：连续 7 天无 P0 安全事故，且可在 30 秒内切回 shadow


## 13. 变更控制

- 本文冻结后，需求变更必须走变更单
- 任何涉及风险策略的修改必须记录版本号与生效时间
- 云端策略下发默认不开启自动生效，必须边缘二次审核通过
