# nanobot 仓库协作指引

你正在 `F:\Projects\nanobot` 中工作。

本文件是该仓库面向 Codex / Claude Code / 其他代码代理的项目级协作说明。除非用户明确要求其他语言，默认使用中文沟通、说明问题和撰写文档。

## 项目概览

`nanobot` 是一个超轻量的个人 AI 助手框架，核心价值是用尽可能小、可读、可研究的代码规模，提供 Agent、工具调用、会话、渠道接入、定时任务等能力。

当前仓库还包含一条本地扩展开发线：`hatchery`。它是近期开启的一期业务子系统，目标是为“海参育苗车间无人化个人助理”提供接口级数字孪生、安全审批、执行核验、审计与桥接能力。后续大部分新增需求如果没有特别说明，通常都是围绕 `hatchery` 继续完善。

## 当前重点

- `nanobot/` 是主框架，优先保持其轻量、稳定、向后兼容。
- `hatchery/` 是业务子系统，当前处于“快速迭代 + 强约束”阶段。
- 本仓库最近存在大量未提交改动，尤其集中在 `hatchery/`、`scripts/`、`docs/`、`tests/`。除非用户明确要求，不要回退、覆盖、整理或格式化无关改动。
- `workspace/AGENTS.md` 是运行时给 nanobot 自身使用的提示文件，不等同于仓库级协作规则。除非任务明确要求，不要把仓库规范改写进 `workspace/AGENTS.md`，也不要把 `workspace/` 当作通用开发文档目录。

## 优先阅读顺序

涉及 `hatchery` 的任务，优先阅读这些文件再动手：

- `PHASE1_SPEC.md`
- `docs/hatchery-gui-acceptance-guide.zh-CN.md`
- `docs/hatchery-deployment-ops-guide.zh-CN.md`
- `docs/plans/2026-03-22-hatchery-hardening-plan.md`
- 相关测试文件：`tests/test_hatchery_*.py`

涉及 `nanobot` 主框架的任务，优先阅读这些文件：

- `README.md`
- `ARCHITECTURE.md`
- `pyproject.toml`
- 目标模块对应源码与测试

## 代码结构

- `nanobot/`
  `nanobot` 主框架，包含 agent、tools、channels、providers、cli、cron、heartbeat、session 等模块。
- `hatchery/`
  业务子系统，一期服务实现。
- `hatchery/app/`
  FastAPI 应用入口、GUI 页面加载。
- `hatchery/container/`
  依赖装配与服务容器。
- `hatchery/contracts/`
  API / 事件契约。这里是跨模块边界，变更要谨慎。
- `hatchery/ingest/`
  水质与生物感知接入、池状态更新。
- `hatchery/policy/`
  动作规划。
- `hatchery/safety/`
  审批、降级、命令状态机，是写链路的核心边界。
- `hatchery/execution/`
  执行适配层，包含 `real_adapter`。
- `hatchery/adapters/`
  MQTT 运行时与桥接。
- `hatchery/orchestrator_bridge/`
  给上层编排器暴露的白名单业务工具和 bridge runner。
- `scripts/`
  启动、备份恢复、E2E、MQTT smoke 等运维和联调脚本。
- `tests/`
  现有测试以 `test_hatchery_*.py` 为主，也包含 `nanobot` 原始测试。
- `docs/`
  验收、部署、计划等文档。

## 工作方式

- 先读规格、接口、测试，再改实现。不要凭感觉重写业务规则。
- 优先做最小闭环修改：契约、实现、测试、文档只改与当前需求直接相关的部分。
- 新增行为时，优先补测试，再改代码；修 bug 时，先定位根因，再决定最小修复点。
- 修改 `hatchery` 时，优先沿既有分层前进：`contracts -> service -> app/runner -> tests/docs/scripts`。
- 修改 `nanobot` 主框架时，优先保持轻量，不把 `hatchery` 的业务假设反向污染到通用层。

## 关键业务边界

### nanobot 主框架

- `nanobot` 是通用 Agent 框架，不要把海参育苗业务规则硬编码进 `nanobot/` 主路径。
- 如果必须让主框架感知 `hatchery`，优先通过独立入口、可选依赖、白名单工具或惰性导入实现。
- 包级 `__init__.py` 尽量避免重依赖导入副作用。导入一个轻量模块时，不应被迫要求 `fastapi`、`uvicorn`、MQTT 等整套业务依赖已经安装。

### hatchery 一期

- 以 `PHASE1_SPEC.md` 为冻结基线。任何与规格冲突的实现改动，都必须显式说明原因。
- 写链路必须经过 `safety`。编排层不能直接控制设备，也不能绕过审批与降级逻辑。
- `orchestrator_bridge` 只能暴露业务白名单工具，不允许把通用 `exec`、任意文件读写、高危工具直接暴露给编排层。
- `real` 模式必须保守。真实执行适配器未就绪时，不能伪装成成功，也不能静默回退成 `sim` 成功。
- 高风险动作的审批、超时提醒、降级、审计是一期关键能力。改动状态机时必须同步检查测试与文档。
- MQTT topic、事件类型、结果码、动作枚举尽量与规格保持一致；如果不得不新增，优先扩展，不要随意改名。
- GUI 是验收台，不是正式业务前端。优化时优先服务验收路径，不要无端重构成复杂前端工程。

## 修改约束

- 不要主动删除未使用文件，除非用户明确要求清理。
- 不要顺手重命名大量字段、目录、接口路径。
- 不要因为“更优雅”而把当前明确可读的流程抽象成过度复杂的框架。
- 不要把脚本逻辑偷偷挪进运行时主路径，除非用户要求产品化。
- 不要修改 `workspace/` 下的运行时记忆、用户数据、数据库和日志，除非任务明确要求处理这些内容。
- 不要假设本地依赖齐全。运行失败时先区分是代码问题还是环境缺依赖。

## 测试与验证

常用环境准备：

```powershell
pip install -e .[dev]
```

常用测试命令：

```powershell
pytest tests -k hatchery
pytest tests/test_hatchery_api.py
pytest tests/test_hatchery_security.py
pytest tests/test_hatchery_real_adapter.py
pytest tests/test_hatchery_bridge_integration.py
```

常用本地运行命令：

```powershell
python -m hatchery.service_runner --host 127.0.0.1 --port 8090
python -m hatchery.orchestrator_bridge.runner --service-url http://127.0.0.1:8090 --host 127.0.0.1 --port 8190
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_hatchery_stack.ps1 -WithBridge
python .\scripts\e2e_hatchery.py --service-url http://127.0.0.1:8090 --bridge-url http://127.0.0.1:8190
python .\scripts\mqtt_live_smoke.py --service-url http://127.0.0.1:8090 --broker-host 127.0.0.1 --broker-port 1883
```

验证时遵循以下规则：

- 能跑相关测试时，优先跑最小相关测试，再决定是否扩大范围。
- 不能跑测试时，明确说明原因，例如缺少 `fastapi`、`pytest-asyncio`、MQTT broker、Docker Desktop 等。
- 改动 API、状态机、bridge、auth、real adapter、MQTT 时，至少补一类对应测试。
- 改动运维脚本或文档时，至少检查命令示例、环境变量名、端口、路径是否与代码一致。

## 文档同步

以下情况应同步更新文档或计划文件：

- API 契约、事件模型、动作枚举、结果码发生变化。
- GUI 验收流程、部署方式、脚本参数发生变化。
- `real adapter`、认证、桥接、MQTT 行为发生变化。
- 新增了开发者后续必然踩坑的环境前提或限制条件。

优先更新位置：

- 规格冻结变化：`PHASE1_SPEC.md`
- 验收路径变化：`docs/hatchery-gui-acceptance-guide.zh-CN.md`
- 部署运维变化：`docs/hatchery-deployment-ops-guide.zh-CN.md`
- 当前迭代计划变化：`docs/plans/`

## 提交前自检

- 变更是否只触及当前任务必要范围。
- 相关测试是否运行，或未运行原因是否已记录。
- 是否破坏了 `sim/shadow/real` 的模式边界。
- 是否破坏了审批、降级、审计、幂等性。
- 是否引入了不必要的包级重依赖导入。
- 是否误改了 `workspace/` 里的运行时文件。

## 输出要求

- 向用户汇报时先说结果，再补测试和风险。
- 引用文件时给出清晰路径。
- 如果发现仓库存在与当前任务冲突的未提交改动，先停下来说明冲突点，不要擅自覆盖。
- 如果只能做部分验证，明确说“我验证了什么、没验证什么、为什么没验证”。

## 一句话原则

在这个仓库里，优先做“围绕规格的最小安全增量”，而不是“看起来更通用的重写”。
