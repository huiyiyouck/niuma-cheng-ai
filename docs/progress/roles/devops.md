# DevOps 角色日志

## 2026-07-27 — v0.2 PRD R3 DevOps 复审 + C-6 实证安排

- 本次角色：DevOps
- 动作：Review（PRD R3 复审 · 运行形态 / 探活与优雅停机 / 凭据注入 / async 后的部署形态）+ 接手 C-6 行锁实证执行安排；另代收并提交了此前滞留工作区的两方 R1 Review 产出（`b8fc087`）
- 涉及文档：`docs/progress/iterations/v0.2-prd.md`（追加 §R3 DevOps 复审 + 订正 Review 状态表本角色行）、`docs/progress/iterations/v0.2.md`（阶段门禁 R3 行 + Review 记录表）、`docs/progress/INDEX.md`（当前阶段 / 外部依赖两项 / 下一步入口）；实查 `uname -s`（**Darwin**）、`ls -d /root`（**不存在**）、`ls .env`（**不存在**）、`lsof 8100/8001/5432`（**均无监听**）、`ls scripts/ deploy/`（**均不存在**）、`.gitignore` / `requirements.txt` / `.env.example` / `src/agent_hub/{config,main}.py`
- 结论：**未通过**（3 高 2 中，需 PM 修改后 R4）。**R1 七条已全部收敛**，其中 3 条被 PM 写得强于原建议（AC-9.3 抗阻塞探活断言 / AC-6.2 错误口令验证法 / AC-5.7 优雅停机验证法）。本轮新问题：高①**§5「唯一剩余外部依赖是口令」不成立** —— 三条实查事实（本机 macOS 无 `/root`、`5432` 无监听、v0.1 全程本机）指向 PRD 说的「同机」是一台 Linux 服务器，即 ai 运行位置要从开发机迁过去，而该部署环境整块缺失，AC-3.6 的 C-6 实证当前不可执行；高②**AC-5.7 宽限期只有上限没有下限、未覆盖 ASGI 与托管层** —— 单批 N≤8 串行最坏 632s，配 90s 完全"合规"却必然中途强杀，systemd 默认 `TimeoutStopSec` 90s 会让 v0.3 托管化当天优雅停机失效；高③**回滚被写成 ai 单方"改配置重启"，实为双侧协同且有顺序** —— DB 模式下 xiaobao 不再发 HTTP，ai 单方切回会让队列静默积压，比不回滚更糟。中④`last_poll_at` 无陈旧阈值（整批处理 632s 内不更新，健康与卡死表现相同）；中⑤同机直读引入**口令副本漂移**（两份、无同步、无热加载）且 root 授权形式未定。
- 关联迭代：v0.2（PRD 阶段 R3，Review中；Developer 同日亦判未通过，Architect 待复审）
- 关联非迭代工作：无
- 关联 Change Note：无
- 遗留问题/风险：① **服务器部署环境是当前最大运维缺口**——不解决则 C-6 实证、联调冒烟、部署就绪检查全部无从谈起，且 v0.2 至今没有部署就绪检查的定义 ② C-6 实证方案已备好（6 步、事务内 `ROLLBACK`），只等环境 + 口令；xiaobao 预判列级 GRANT 可能不满足 `FOR UPDATE`，若失败其改授表级 ③ 实证纪律：`news_test` 仅 5 条预置 `queued`，实证绝不能把任何一条推进到 `running`，否则自测样本减少 ④ 结论回帖 coordination 归 PM，跨仓 `communications/` 写入不在本角色权限内 ⑤ 托管化仍顺延 v0.3，v0.2 只能人工看护灰度、不得无人值守（§4 已写明）
- 下一步入口：Architect 补做 R3 复审（最后一方）；PM 按两方意见出 R4（DevOps 侧三条必改见上）；本角色待 Owner 授权服务器访问后，备部署环境 + 注入口令 + 执行 C-6 实证。
- 收尾状态：已收尾

## 2026-07-25 — v0.2 PRD R1 DevOps Review（主线 REQ-003）

- 本次角色：DevOps
- 动作：Review（PRD R1 · 运行形态变更 / 环境变量与凭据注入 / 探活与健康检查 / 发布风险与回滚条件）
- 涉及文档：`docs/progress/iterations/v0.2-prd.md`（追加 R1 DevOps Review）、`docs/progress/iterations/v0.2.md`（阶段门禁 + Review 记录）、`docs/progress/INDEX.md`；实读 coordination `contracts/news-l1-db.md` v1 + `communications/REQ-003-db-boundary-async.md`、本项目 `.env.example` / `.gitignore` / `requirements.txt` / `src/agent_hub/{config,main}.py`；运行实查 `lsof 8100/8001/5432`、`ls .env`
- 结论：**未通过**（需 PM 修改后 R2）。4 高：① DB 模式探活面缺失（进程级开关下 `/health` 消失，worker 静默死亡与空转不可区分，AC 无覆盖）② 优雅停机/回滚时残留 `processing` 锁无验收（AC-5 只覆盖被杀死的被动路径，主动停机必然发生却没写，一次不优雅停机 = N 条延迟 ≥30 分钟）③ AC-6 脱敏未覆盖最主要泄漏路径（DB 连接异常带 DSN/口令）④ 测试库造数依赖未列 §5 前置（ai 对 `raw_items` 只读、无法自行造数，会直接卡部署就绪检查）。2 中：日志 sink 与轮转未定；托管化顺延需在范围边界写明「人工看护灰度、不得无人值守」。1 低：未提新增 DB 驱动与 `.env.example` 更新。同时给出 **O-7 凭据注入结论**（口令只进已被 gitignore 的 `.env`；变量按字段拆分 `AI_DB_HOST/PORT/NAME/USER/PASSWORD` 而非整串 DSN；无热加载故轮换须重启；口令走带外交付）与 **O-3 运维侧约束**（`N × 79s < 1800s` → 单批 N ≤ 22 绝对上限、建议 N ≤ 8；轮询 10~30s；灰度期单实例）。认可项：AC-1 fail-safe 默认、AC-4 单事务、AC-5 不越权回收他人锁、logging 未随托管化一并顺延。
- 关联迭代：v0.2（PRD 阶段 R1，Review中）
- 关联非迭代工作：无
- 关联 Change Note：无
- 遗留问题/风险：① **测试环境已不在**——`.env` 不存在、`8100` 无监听、本机 `5432` 无监听，v0.2 是环境重建 + 新增共享库外部依赖，部署面大于 v0.1，需在设计/部署阶段按新形态重建 ② coordination R-1/R-2/R-3（`ai_worker` GRANT 就绪 / schema 迁移落地 / 连接信息与凭据渠道）仍待 xiaobao 与 Owner 回应，其中 R-3 是 O-7 落地前置 ③ 造数依赖需 PM 在 coordination REQ-003 待跟进表追加一行 ④ 托管化顺延 v0.3 的代价是 v0.2 worker 崩溃不自动拉起、队列静默积压 ⑤ O-1（P0）未决，PRD 无论如何不能定稿。
- 下一步入口：Architect / Developer 补做 PRD R1 Review；PM 按本轮意见修改进 R2；DevOps 待 R-3 回应后落地凭据注入 + 重建测试环境。
- 收尾状态：已收尾

## 2026-07-04 — 实现 R1 DevOps Review

- 本次角色：DevOps
- 动作：Review（实现 R1 部署 / 环境变量 / 密钥注入 / 健康检查 / 发布风险 / 回滚条件）
- 涉及文档：`docs/progress/iterations/v0.1.md`、`docs/progress/iterations/v0.1-test-report.md`、`docs/progress/iterations/v0.1-design.md`；实读 `.env.example` / `src/agent_hub/{config,main}.py` / `src/agent_hub/llm/client.py` / `src/agent_hub/tools/{web_search,kb,link_reader}.py` / `requirements.txt`；运行实查 `curl 8100/health`、`lsof 8100/8001`、`ps uvicorn`
- 结论：**通过**（实现 R1 从 DevOps 视角可定稿；附 4 条发布检查项跟踪到部署阶段，不阻塞）。设计 DevOps R1 三条发布检查项落实：`.env.example` 已补全 ✅、生产 ≥2 provider ⏳、健康检查 / 发布冒烟 🟡（2026-07-01 真实冒烟 succeeded + Tavily 通，多 provider 真实 fallback 未冒烟）。密钥注入边界、总 timeout budget、provider fallback 矩阵、Tavily/KB 未配置降级均与设计一致。两方通过，实现 R1 定稿，进入 Owner 验收 / 部署就绪检查。
- 关联迭代：v0.1（实现阶段 R1 定稿）
- 关联非迭代工作：无
- 关联 Change Note：CN-002
- 遗留问题/风险：① 当前服务实际未运行（`8100` / `8001` 无监听、`nohup` 非托管、重启不自动拉起）→ 部署阶段补 systemd/supervisor/launchd 托管 ② 日志可观测性缺失（`main.py`/`llm/client.py`/`tools/*` 均无 `logging`）→ 部署阶段补结构化脱敏 logging ③ 生产 ≥2 provider 未验证 ④ 单条 ~104s 偏长（reasoning 模型 + 工具串行）⑤ Architect 5 条非阻塞观察项按优先级在 R2 或下一迭代处理。
- 下一步入口：Owner 验收 / 部署就绪检查（处理 4 条发布检查项）；Architect 同步 test-report 状态表 Architect 行；Developer 同步 test-report 结论段「36 passed」→「40 passed」。
- 收尾状态：已收尾

## 2026-07-02 — 同步最新 + 收尾复核
- 本次角色：DevOps
- 动作：同步 / 收尾 / 运行状态复核
- 涉及文档：`docs/progress/INDEX.md`、`docs/progress/iterations/v0.1.md`、`docs/progress/roles/devops.md`
- 结论：`git fetch` + `git pull --rebase` 完成，远端已是最新；工作区收尾前干净。运行状态复核：`127.0.0.1:8100` 由 uvicorn 监听，`/health` 返回 `{"status":"ok","service":"niuma-cheng-ai"}`；`127.0.0.1:8001` 当前也在监听。
- 关联迭代：v0.1（实现 R1 Review中，迭代未关闭）
- 关联非迭代工作：无
- 关联 Change Note：CN-002
- 遗留问题/风险：① KB/端到端仍需 xiaobao 配置确认与真实调用证据 ② 测试环境服务仍为 uvicorn 常驻，长期运行需 systemd/supervisor ③ 生产发布仍需多 provider、鉴权、日志脱敏和耗时调优复核。
- 下一步入口：xiaobao 确认 `AI_HUB_BASE_URL` / `KB_ADMIN_TOKEN` 后跑 KB/端到端联调；Architect/DevOps 复核实现 R1。
- 收尾状态：已收尾

## 2026-07-01 — ai 测试环境部署 + news-l1 真实冒烟
- 本次角色：DevOps
- 动作：部署 / 冒烟 / 回填
- 涉及文档：`.env`（不入库，key 取自 openclaw）、`docs/progress/iterations/v0.1.md`（部署就绪检查）、`docs/progress/INDEX.md`；coordination `communications/REQ-001-news-l1.md`、`STATUS.md`
- 结论：ai 服务部署到测试环境 `127.0.0.1:8100`（当前机器 uvicorn `nohup` 常驻，pid 运行中）。LLM=openclaw 火山 `doubao-seed-2.0-pro`（`LLM_PROVIDERS_JSON` 单 provider），Tavily key 取自 openclaw；鉴权测试环境不启用（Owner 定）。冒烟：`/health` 200；真实 `POST /v1/runs/news-l1` `succeeded`（run `run_bcf24393b947`，`tool_summary` web=1/link=0/kb=1，KB 因 xiaobao 8001 未起降级、整体 succeeded）。已回填 coordination（`97ae5e0`）。
- 关联迭代：v0.1（部署就绪检查，部分通过）
- 关联 Change Note：CN-002
- 遗留问题/风险：① 服务 `nohup` 起，非托管，重启不自动拉起 → 长期常驻需 systemd/supervisor ② 生产要求 ≥2 provider，当前测试仅火山单 provider ③ KB 端到端当前已见 xiaobao `8001` 监听，仍待配置确认 + 真实调用证据 ④ 单条约 104s 偏长（reasoning 模型），可评估换更快模型 / 工具并发 ⑤ 日志脱敏、Tavily 是否需代理未专项验证。
- 下一步入口：xiaobao 起服务 + 配 `AI_HUB_BASE_URL` 做端到端验收；上线阶段做服务托管 + 多 provider + 鉴权。
- 收尾状态：已收尾

## 2026-07-01 — 会话摘要
- 本次角色：DevOps
- 动作：启动 / Review
- 涉及文档：`docs/progress/iterations/v0.1-design.md`、`docs/progress/iterations/v0.1.md`
- 结论：v0.1 设计 R1 DevOps Review 通过，设计阶段三方通过并定稿；已同步 INDEX 进入实现阶段
- 关联迭代：v0.1
- 关联非迭代工作：无
- 关联 Change Note：CN-001
- 遗留问题/风险：实现阶段需补 `.env.example` 的多 provider / backup key / `TAVILY_API_KEY` 示例；部署阶段需验证生产至少 2 个 provider、fallback、Tavily 未配置降级与日志脱敏
- 下一步入口：Developer 根据 `v0.1-prd.md` / `v0.1-design.md` 启动实现阶段
- 收尾状态：已收尾（2026-07-02 复核补记）
