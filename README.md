# agent-workflow

一套面向”一人公司”的 AI 编程助手多角色开发团队工作流。它的目标不是制造复杂流程，而是让同一个人可以按角色启动不同 AI 助手会话，稳定完成从产品定义、架构设计、实现、Review、部署检查到复盘纠错的闭环。

> **内部架构定位**（一人公司 AI 组织操作架构：指挥官—参谋长制·薄公司）：以 Owner 为唯一指挥官（CEO），参谋长打理生态事务，各项目组按统一 SOP 作战，公告板承载跨组沟通；本工作流是**每个作战组的标准作业规程（SOP）**，是公司架构的一层而非全部。三条组织法则：结构跟着物理走、参谋不决策、半自动是设计选择而非缺陷。对外品牌仍为「一人公司 AI 开发团队工作流」。

这套工作流适合复制到 Codex、Claude Code、Trae 或其他支持项目级指令文件（如 `AGENTS.md`）的 AI 编程助手项目中使用。项目自己的业务背景、技术栈、启动方式和业务边界写入 `docs/baseline/project-context.md`，当前迭代状态写入 `docs/progress/INDEX.md` 和 `docs/progress/iterations/`，通用协作规则保持不变。

> **本仓库性质（真源仓库 / single source of truth）**：本仓库本身的用途是**研究和维护这套工作流**，并作为后续所有项目引用的统一真源。仓库内的 `CLAUDE.md`/`AGENTS.md`、`docs/baseline/`、`docs/templates/` 是被开发、被维护的**制品**，不是约束本仓库会话的操作法律。在本仓库工作时默认以普通助手（General）身份直接编辑这些文件，不进入工作流、不写 `docs/progress/`。工作流框架在本仓库统一修改，下游项目通过 coordination 基线修正提案池（`BCR-###`）提报、由真源评估落地后经 sync 回流（见 `docs/baseline/cross-project-collaboration.md`）。入口文件顶部的 `SOURCE-REPO-ONLY` 块只服务本仓库，复制/同步到下游项目时必须整块删除。

## 语言约定

这套工作流默认且必须使用中文进行对话和协作。PRD、设计文档、Review 结论、部署检查、角色日志、纠错记录和基线提案都使用中文；代码标识符、命令、错误信息、第三方 API 名称和必要英文引用可以保留原文。

## 核心角色

| 角色 | 主要职责 | 是否进入标准门禁 |
|------|----------|------------------|
| General（通用助手） | 默认入口角色，处理普通问答、临时文件解释、临时代码修改和一次性命令 | 否 |
| PM（产品经理） | 需求、范围、验收标准、迭代规划、**界面要点（并入 PRD）** | 是 |
| Architect（架构师） | 架构设计、技术边界、ADR、接口/数据流 | 是 |
| Developer（开发工程师） | 代码实现、**自测（接口/自动化+证据）**、修复 Review 问题 | 是 |
| DevOps（运维/部署工程师） | 部署、环境、健康检查、发布就绪 | 是（独立检查，高风险时动态指定确认方） |

> 角色集精简（BCR-004/006，2026-06-25）：原 **UI** 并入 PM（界面要点进 PRD）、原 **Tester** 并入 Developer 自测 + **Owner 验收**（手动点击验收为迭代关闭门禁；验收/边界/回归独立复核由 Architect 或 DevOps 承担）。

> 工作流框架本身（角色设计、基线规则、流程审计、体系完善）由**真源仓库**统一维护，不再设独立的工作流管理角色。下游项目发现问题时写 `BCR-###` 入 coordination 基线修正提案池，由真源评估落地后 sync 回流。

General（通用助手）是默认角色，不读取团队基线、不写进度、不参与 Review 门禁。只有当用户明确或模糊触发工作流角色/流程时，才从 General 切换到 PM、Developer 等工作流角色。

人类用户是项目 Owner（负责人）和实际项目经理，负责最终协调、优先级和流程取舍。工作流不设置常驻 Project Manager（项目经理）Agent，避免把一人公司做成虚假的管理层。

## 非角色机制

Bootstrap 初始化、收尾归档、迭代关闭检查不是角色。它们由当前会话 Agent 在用户要求或检测到触发条件时执行，关键结果由用户确认；流程审计同样由当前会话 Agent 执行。工作流加载后，未初始化项目只能建议 Bootstrap，不能因为用户问候或闲聊就自动创建文件。Bootstrap 只安装团队工作台，不等于启动标准迭代；用户未选择角色或工作类型时，可以保持 General（通用助手）。详细规则见 `docs/baseline/mechanisms.md`。

## 工作流入口

项目入口文件默认使用 General（通用助手）角色，并只做扁平角色切换路由。Codex 与 Trae 使用 `AGENTS.md`（Trae 认 agents.md 开放标准，复用同一份，无需独立入口），Claude Code 使用 `CLAUDE.md`；两个入口文件应保持同一套内容，只负责判断是否从 General 切换到工作流角色。

- 明确触发：用户明确说“进入团队工作流”“以某角色工作”“执行 Bootstrap 初始化流程”“启动标准迭代”“执行收尾归档”等触发语后，从 General 切换到对应工作流角色，并读取 `docs/baseline/runtime.md`。
- 模糊触发：用户提到“产品、开发、测试、架构、UI、部署、管理者”等角色关键词但意图不完整时，General 只做一次确认；用户确认后再切换角色。
- 未触发：普通问答、闲聊、解释文件、临时改代码等请求保持 General，直接按当次请求处理，不读取团队基线、不要求角色、不写 `docs/progress/`。

这样可以保留各类 AI 编程助手的自由使用方式，也能在需要时进入标准化团队协作。

加载工作流后仍然要继续分流：未初始化先走 Bootstrap；已初始化后先判断是非迭代自主任务还是标准迭代。非迭代任务可以由相关角色直接处理；标准迭代只能由 PM（产品经理）创建 PRD 后启动，其他角色只能提出迭代建议。

## 工作模式

不是所有工作都进入标准迭代。Bug 修复、线上故障、产品方案沉淀、UI 草案、技术预研、外部/开源项目部署等，可以按非迭代工作处理，记录在 `docs/progress/ad-hoc/`。详细规则见 `docs/baseline/work-modes.md`。

用户说“今天收尾”“下班”“先停一下”时，当前 Agent 执行收尾归档：更新当前角色日志、当前工作记录、项目索引、必要的知识库条目和下一步入口；其他角色只登记待补充或待确认。

## Review 机制

标准迭代采用动态 Review 计划，不采用固定全员 Review。产出方根据本次影响领域指定 Review 方并写明理由；核心产出默认至少指定 2 个 Review 方，少于 2 个需用户确认。文档定稿后发现问题，按实现取舍、轻量变更、重大变更三档处理。轻量变更通过 Change Note 由受影响角色确认，执行完成后必须归档。

## 团队知识库和上下文

可复用知识沉淀在 `docs/knowledge/`，例如产品机会、重构机会、Bug 根因、部署经验和复盘结论。详细规则见 `docs/baseline/knowledge-base.md`。

为避免上下文膨胀，Agent 默认以 General 工作，不读取 `docs/baseline/runtime.md`。只有确认切换到工作流角色或执行工作流流程后，才读取 `runtime.md`，再按场景顺序加载需要的规则文件。工作流加载后默认只读项目事实、进度索引、当前角色手册和相关摘要；标准迭代、非迭代、收尾归档、知识库和模板文件都按触发条件再读取。角色日志过长时按 `docs/baseline/context-policy.md` 摘要归档。

## 推荐安装方式

### 方式 A：安装脚本（推荐）

在**真源仓库**目录下运行，把工作流安装到目标项目目录（产出一份干净副本）：

```bash
scripts/install-downstream.sh <目标目录>
```

脚本会：剥离入口文件顶部的 `SOURCE-REPO-ONLY` 块；只复制工作流运行所需文件（`CLAUDE.md` / `AGENTS.md`、`docs/baseline/`、`docs/templates/`、空的 `docs/knowledge/` 骨架）；铺一份 `docs/baseline/project-context.md` 占位待填；**不带**真源专属文件（`docs/ROADMAP.md`、`docs/regression-cases.md`、`scripts/`、`docs/progress/`）。目标目录必须不存在或为空，否则脚本拒绝产出、不覆盖你已有的文件。

安装后：

1. 填写 `docs/baseline/project-context.md`（项目事实层，安装时已铺占位，**与 Bootstrap 无关**）。
2. 首次加载工作流时若无 `docs/progress/INDEX.md`，说 `执行 Bootstrap 初始化流程`，由 Bootstrap 创建 `docs/progress/` 工作台与进度索引。**Bootstrap 只装 `docs/progress/` 工作台，不创建 `project-context.md`**。
3. Bootstrap 后可指定角色或工作类型，例如 `这次以 Architect（架构师）角色工作`；暂不工作也可保持 General（通用助手）。

### 方式 B：手动复制（fallback）

1. 将工作流文件复制到新项目：入口文件（Codex 用 `AGENTS.md`、Claude Code 用 `CLAUDE.md`，两者都用则都保留并保持内容一致）、`docs/baseline/`、`docs/templates/`、空的 `docs/knowledge/` 骨架。**复制后必须删除入口文件顶部的 `SOURCE-REPO-ONLY` 块**（只适用于真源仓库）。不要复制 `docs/ROADMAP.md`、`docs/regression-cases.md`、`scripts/`、真源的 `docs/progress/`。
2. 将 `docs/baseline/project-context.template.md` 复制为 `docs/baseline/project-context.md` 并填写项目事实（项目事实层，独立于 Bootstrap）。
3. 空项目首次加载工作流时若无 `docs/progress/INDEX.md`，说 `执行 Bootstrap 初始化流程`，由 Bootstrap 创建 `docs/progress/` 工作台目录和进度索引（不创建迭代、角色日志或 `project-context.md`）。
4. Bootstrap 后可指定角色或工作类型；暂不工作也可保持 General 继续闲聊。

## 基本原则

- `AGENTS.md` / `CLAUDE.md` 只做入口索引，不塞长篇流程。
- `runtime.md` 只做工作流加载后的路由，不写完整规范。
- `project-context.md` 只写项目事实，不写通用流程。
- `multi-agent-workflow.md` 是完整协作规范；标准 / 非迭代速查为 `standard-iteration-quick.md` / `non-iteration-quick.md`，均不写具体项目业务。
- 每个阶段必须先定稿再进入下一阶段。
- Review 方只审自己职责边界内的问题。
- 发现流程问题时先写提案，不能直接改基线。
