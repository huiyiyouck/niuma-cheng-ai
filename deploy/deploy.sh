#!/usr/bin/env bash
# niuma-cheng-ai 部署脚本（幂等）
#
# 架构（对齐 xiaobao 的「去软链接化 + 全隔离」，2026-07-28 起）：
#   构建源 /opt/niuma-cheng-ai（git 工作区，只负责 pull + 测试）
#     └─rsync（排除 .env/.git/.venv）─▶ 运行目录 /srv/niuma-ai/{test,prod}
#                                          └─ systemd WorkingDirectory
#
#   .env 不在分发范围（rsync 显式排除），由部署机本地维护，内含 ai_worker 口令
#   与 LLM 凭据。运行目录本身不是 git 工作区，故 .env 天然在仓外——这同时满足
#   PRD §5「.env 应在仓外」，且 config.py 的无参 load_dotenv() 无需任何改动。
#
# 用法: ./deploy.sh [test|prod]    默认 test
#
# 不在本脚本内：数据库迁移（schema 归 xiaobao 权属，ai 不建表不改表）。

set -euo pipefail

ENV_NAME="${1:-test}"
case "$ENV_NAME" in
  test|prod) ;;
  *) echo "用法: $0 [test|prod]" >&2; exit 2 ;;
esac

SRC=/opt/niuma-cheng-ai
RUN=/srv/niuma-ai/$ENV_NAME
WORKER_UNIT="niuma-ai-worker@$ENV_NAME"
HTTP_UNIT="niuma-ai-http@$ENV_NAME"

echo "==== [1/6] 构建源同步 ($SRC) ===="
cd "$SRC"
git fetch origin
git pull --rebase
git log --oneline -1

echo "==== [2/6] 自测闸门 ===="
# xiaobao 的 deploy.sh 没有这道闸。ai 必须有：async 改造期（O-8，本迭代最大
# 技术风险）任何一次回归都可能悄悄改变处理行为，不能带着红灯上线。
PYTHONPATH="$SRC/src" "$SRC/.venv/bin/pytest" -q

echo "==== [3/6] 分发到运行目录 ($RUN) ===="
mkdir -p "$RUN"
rsync -a --delete \
  --exclude='.env' --exclude='systemd.env' \
  --exclude='.git' --exclude='.venv' \
  --exclude='__pycache__' --exclude='.pytest_cache' \
  "$SRC/" "$RUN/"

echo "==== [4/6] 运行环境 ===="
[ -d "$RUN/.venv" ] || python3 -m venv "$RUN/.venv"
"$RUN/.venv/bin/pip" install --quiet --upgrade pip
"$RUN/.venv/bin/pip" install --quiet -r "$RUN/requirements.txt"

# 配置文件必须已存在（含凭据，不由本脚本创建、不由 rsync 分发）
for f in .env systemd.env; do
  [ -f "$RUN/$f" ] || { echo "缺少 $RUN/$f，请先在部署机准备（内含凭据，不入 git）" >&2; exit 1; }
done
chmod 600 "$RUN/.env"
chown -R niuma-ai:niuma-ai "$RUN"

echo "==== [4.5/6] 三层停机时限校验 ===="
# 设计 R1 · DevOps Review 问题 2：应用启动校验只能覆盖应用侧的量，
# 读不到 unit 里的 TimeoutStopSec——三层关系的强制点只能在部署层。
# 漂移场景：把 L1_CLAIM_BATCH_SIZE 调大后应用侧强制 grace 变大、启动成功，
# 而 TimeoutStopSec 是 unit 常量不会跟着变 → systemd 照样提前 SIGKILL，
# 且应用侧所有校验都是绿的，比不配更隐蔽。
GRACE_MS=$(grep -E '^L1_SHUTDOWN_GRACE_MS=' "$RUN/.env" | cut -d= -f2 || true)
GRACE_MS=${GRACE_MS:-260000}
GRACE_SEC_ENV=$(grep -E '^SHUTDOWN_GRACE_SEC=' "$RUN/systemd.env" | cut -d= -f2 || true)
GRACE_SEC_EXPECT=$(( GRACE_MS / 1000 ))

# ASGI 层必须与应用层一致（uvicorn 的 --timeout-graceful-shutdown 从这里取值）
if [ "$GRACE_SEC_ENV" != "$GRACE_SEC_EXPECT" ]; then
  echo "!! systemd.env 的 SHUTDOWN_GRACE_SEC=$GRACE_SEC_ENV 与 .env 的 L1_SHUTDOWN_GRACE_MS=$GRACE_MS（=${GRACE_SEC_EXPECT}s）不一致" >&2
  echo "   ASGI 层宽限期须等于应用层，否则 uvicorn 会先于 worker 结束进程" >&2
  exit 1
fi

# 托管层必须【严格大于】应用层——逐层放大，不是相等（DevOps Review 问题 1）
UNIT_CHECKED=0
for unit_file in /etc/systemd/system/niuma-ai-worker@.service; do
  if [ ! -f "$unit_file" ]; then
    echo "  ⚠ $(basename "$unit_file") 尚未安装到 /etc/systemd/system——**托管层未校验**"
    continue
  fi
  TSS=$(grep -E '^TimeoutStopSec=' "$unit_file" | cut -d= -f2)
  MIN=$GRACE_SEC_EXPECT
  if [ "$TSS" -le "$MIN" ]; then
    echo "!! $(basename "$unit_file") 的 TimeoutStopSec=${TSS}s 未严格大于应用层宽限期 ${MIN}s" >&2
    echo "   相等会在边界产生竞态：worker 恰好用满时 systemd 同时 SIGKILL，写回可能在 COMMIT 前被杀 → 残留锁" >&2
    echo "   建议 TimeoutStopSec = ${MIN} + 20 = $(( MIN + 20 ))" >&2
    exit 1
  fi
  echo "  ✓ $(basename "$unit_file"): TimeoutStopSec=${TSS}s > 应用层 ${MIN}s"
  UNIT_CHECKED=1
done
if [ "$UNIT_CHECKED" -eq 1 ]; then
  echo "  ✓ 三层关系完整校验通过：应用 ${GRACE_SEC_EXPECT}s ≤ ASGI ${GRACE_SEC_ENV}s < systemd"
else
  echo "  ✓ 应用层与 ASGI 层一致（${GRACE_SEC_EXPECT}s）；**托管层待装 unit 后由本脚本校验**"
fi

echo "==== [5/6] 重启服务 ===="
systemctl daemon-reload
# RUN_MODE 由 unit 决定（见 unit 内 Environment=RUN_MODE），此处按启用状态重启
RESTARTED=0
for unit in "$WORKER_UNIT" "$HTTP_UNIT"; do
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    echo "  restart $unit"
    systemctl restart "$unit"
    RESTARTED=1
  else
    echo "  跳过 $unit（未 enable）"
  fi
done

# 首次部署时 unit 尚未安装/enable，此时没有任何服务在跑，健康检查必然失败。
# 那不是部署失败，是「代码与环境已就位、等待装 unit」这个中间态。
if [ "$RESTARTED" -eq 0 ]; then
  echo "==== [6/6] 跳过健康检查 ===="
  echo "  未有已 enable 的 unit——代码与运行环境已就位，请先安装并启用 unit："
  echo "    cp $SRC/deploy/systemd/niuma-ai-*@.service /etc/systemd/system/"
  echo "    systemctl daemon-reload && systemctl enable --now niuma-ai-http@$ENV_NAME"
  echo "  装好后重跑本脚本即可完成验证。"
  echo "==== 部署完成（未启动服务）: $ENV_NAME @ $(git -C "$SRC" rev-parse --short HEAD) ===="
  exit 0
fi

echo "==== [6/6] 部署后验证 ===="
PORT=$(grep -E '^PORT=' "$RUN/systemd.env" | cut -d= -f2)
if ! curl -sf --retry-connrefused --retry 20 --retry-delay 1 --max-time 30 \
     "http://127.0.0.1:${PORT}/health"; then
  echo ""
  echo "!! /health 未通过，最近 50 行日志：" >&2
  journalctl -u "$WORKER_UNIT" -u "$HTTP_UNIT" -n 50 --no-pager >&2 || true
  exit 1
fi
echo ""
echo "==== 部署完成: $ENV_NAME @ $(git -C "$SRC" rev-parse --short HEAD) ===="
