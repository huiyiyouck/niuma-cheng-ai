# 部署说明

> DevOps 产出，2026-07-28。方案论证见 `docs/progress/ad-hoc/2026-07-28-ops-server-env-and-credential.md` §6。

## 目录约定（三层分离）

```
/opt/niuma-cheng-ai/       构建源（git 工作区，只 pull + 跑测试，不直接运行）
/srv/niuma-ai/test/        运行目录（rsync 目标，systemd WorkingDirectory）
/srv/niuma-ai/prod/        同上（v0.2 灰度期不启用）
```

**运行目录不是 git 工作区**，故其中的 `.env` 天然在仓外——这同时满足 PRD §5「`.env` 应在仓外」，且 `config.py` 的无参 `load_dotenv()` 无需任何改动。

## 两个配置文件（都不入 git）

| 文件 | 谁读 | 放什么 |
|---|---|---|
| `/srv/niuma-ai/<env>/.env` | 应用（`load_dotenv()`） | 应用配置与凭据：`AI_DB_*`、`LLM_PROVIDERS_JSON`、`VOLC_API_KEY`、`TAVILY_API_KEY` 等。`chmod 600` |
| `/srv/niuma-ai/<env>/systemd.env` | systemd（`EnvironmentFile=`） | **只放简单值**：`PORT=` 与 `SHUTDOWN_GRACE_SEC=`（后者供 uvicorn 的 `--timeout-graceful-shutdown`，须等于 `.env` 里 `L1_SHUTDOWN_GRACE_MS/1000`，由 `deploy.sh` 强制校验）。systemd 的 EnvironmentFile 解析不了 `LLM_PROVIDERS_JSON` 里的嵌套引号，故与上面那份分开 |

`RUN_MODE` 不放这两个文件——它由 unit 的 `Environment=RUN_MODE=` 决定（`load_dotenv()` 默认 `override=False`，systemd 注入的值优先）。这样「一个进程只跑一种模式」由托管层保证，对应 AC-1.4 的进程级开关。

## 首次安装

```bash
# 1. 专用系统用户（不用 root 跑业务进程）
useradd --system --no-create-home --shell /usr/sbin/nologin niuma-ai

# 2. 运行目录与配置
mkdir -p /srv/niuma-ai/test
install -m 600 -o niuma-ai -g niuma-ai /dev/null /srv/niuma-ai/test/.env
printf 'PORT=8100\nSHUTDOWN_GRACE_SEC=260\n' > /srv/niuma-ai/test/systemd.env
#    → 再把 .env 内容准备好（DB 口令按 O-7 拆字段；口令不经对话、不入 git）

# 3. 安装 unit
cp deploy/systemd/niuma-ai-*@.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now niuma-ai-worker@test     # DB 模式
# 或 systemctl enable --now niuma-ai-http@test  # HTTP 模式（二选一，进程级开关）

# 4. 后续部署
./deploy/deploy.sh test
```

## 运维速查

```bash
systemctl status niuma-ai-worker@test
journalctl -u niuma-ai-worker@test -f              # 跟随日志
journalctl -u niuma-ai-worker@test -S -1h -o json  # 结构化日志过滤
curl -s 127.0.0.1:8100/health                      # 探活（含 mode / last_poll_at / worker_alive）
systemctl stop niuma-ai-worker@test                # 优雅停机，最长等 280s
```

## 关键配置为什么是这个值

| 配置 | 值 | 不这么配会怎样 |
|---|---|---|
| `TimeoutStopSec`（worker） | **280** | ADR-0004 定应用层宽限期 260s，而 systemd 默认 90s。不覆盖则**优雅停机每次都被中途 SIGKILL**，留下 `l1_status='processing'` 残留锁，只能等 xiaobao 侧 1800s 卡死回收，每条延迟 ≥30 分钟 |
| **三层关系** | **逐层放大，不是相等** | 应用 260s ≤ ASGI 260s < systemd **280s**。若三者取同一个值，worker 恰好用满 260s 完成最后一次写回时 systemd 同时 SIGKILL，**写回可能在 COMMIT 之前被杀**——正是这套配置本要防的事。`TimeoutStopSec` 不支持 EnvironmentFile 变量展开、只能是常量，故该关系由 `deploy.sh` 在部署时强制校验（应用启动校验读不到 systemd 配置，管不到这一层） |
| `Restart`（worker） | **on-failure** | 用 `always` 时，优雅停机后 worker 正常退出（exit 0）会被立刻拉起重新 claim。**影响正确性，不是策略偏好** |
| `StartLimitIntervalSec/Burst` | 300 / 3 | 崩溃循环会反复 claim、反复制造残留锁。单条预算 240s，故窗口比 xiaobao 的 60s 更长 |
| `After`/`Wants` | `network-online.target` | `network.target` 只表示网络栈启动、**不保证网络可用**，而 ai 启动即连 DB 与外部 LLM API |
| `StandardOutput` | **journal** | append 到文件无轮转——参照反例：xiaobao 的 `/var/log/niuma-news-api.log` 已 13M 且无 logrotate。ai 是 7×24 轮询，更严重 |
| `User` | **niuma-ai** | ai 只需读运行目录、读 `.env`、连本机 5432、出网调 LLM，不需要 root |
| `ProtectSystem=strict` | — | ai 要解析外部 LLM 返回的内容，纵深防御有实际意义 |

## 尚未纳入（有意为之）

- **`Type=notify` + `WatchdogSec`** — 更强的存活保障（进程假死时 systemd 主动重启），但需在代码里调 `sd_notify` 并周期喂狗，属实现阶段改动。建议 v0.3。
- **healthcheck timer** — 可不改代码实现近似效果，**但必须先写死 AC-9.3 的状态码语义**（`running`→200 / `stopping`→**200** / `dead`→非 200）。若 `stopping` 落进非 200，timer 会在优雅停机的 260s 窗口内把它判死重启，反而制造残留锁。**该语义未定死前不要上 timer。**
- **多 worker 实例** — v0.2 灰度期单实例；Architect 已定「v0.3 多实例前必须先解决 C-6」。模板 unit 已为多实例预留形态。
- **prod 环境** — v0.2 只做 test。PRD §5「届时前置 1」明确「不假定生产已就绪」。
