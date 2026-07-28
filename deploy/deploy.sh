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

echo "==== [5/6] 重启服务 ===="
systemctl daemon-reload
# RUN_MODE 由 unit 决定（见 unit 内 Environment=RUN_MODE），此处按启用状态重启
for unit in "$WORKER_UNIT" "$HTTP_UNIT"; do
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    echo "  restart $unit"
    systemctl restart "$unit"
  else
    echo "  跳过 $unit（未 enable）"
  fi
done

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
