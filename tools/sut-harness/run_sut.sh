#!/usr/bin/env bash
# 在容器里跑真实被测(`01.FastAPI RAG Agent`),供评测门做真实链路评测用。
#
# 定位:**评测门的运行适配层**,不是被测的一部分。**被测仓零改动** ——
# 只读挂载它的 `api/`,所有补丁都在容器运行时(见 README「退出条件」)。
#
# 用法:
#   tools/sut-harness/run_sut.sh                    # 用默认被测路径
#   EVAL_SUT_REPO=/path/to/sut tools/sut-harness/run_sut.sh
#
# 退出码:0 = 就绪且**能力探针通过**;1 = 起不来;2 = 起来了但答不了(见 README §陷阱)
set -euo pipefail

SUT_REPO="${EVAL_SUT_REPO:-/Users/heweidong/Desktop/ai-learning/重点教学内容/01.FastAPI RAG Agent}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${EVAL_SUT_IMAGE:-my-fixed-name-api}"
CONTAINER="${EVAL_SUT_CONTAINER:-rag-api-eval}"
NETWORK="${EVAL_SUT_NETWORK:-my-fixed-name_app-net}"
DEPS_VOLUME="${EVAL_SUT_DEPS_VOLUME:-sut-pydeps}"
PORT="${EVAL_SUT_PORT:-8000}"
API_KEY="${EVAL_SUT_FASTAPI_API_KEY:-}"

log() { printf '[sut-harness] %s\n' "$*"; }
die() { printf '[sut-harness] ✗ %s\n' "$*" >&2; exit 1; }

[ -d "$SUT_REPO/api" ] || die "被测仓路径不对(缺 api/):$SUT_REPO —— 用 EVAL_SUT_REPO 指定"
[ -f "$SUT_REPO/.env" ] || die "被测仓缺 .env(容器要用它做 env-file):$SUT_REPO/.env"

# 1) Docker 与依赖容器 -------------------------------------------------------
docker info >/dev/null 2>&1 || die "Docker daemon 未运行(先启动 Docker Desktop)"
log "启动 postgres/redis(若已在跑则忽略)…"
docker start postgres-rag redis-rag >/dev/null 2>&1 || true
for _ in $(seq 1 30); do
  docker exec postgres-rag pg_isready >/dev/null 2>&1 && break
  sleep 3
done
docker exec postgres-rag pg_isready >/dev/null 2>&1 || die "postgres-rag 未就绪"

# 2) 起被测容器 --------------------------------------------------------------
# ⚠️ 必须显式 -e 覆盖这两个变量:docker run --env-file **不剥离行内注释**,
#    被测 .env 里 `LLM_MODEL_FAST=deepseek-v4-flash   # 轻量角色:…` 会把注释整段当值。
log "重建容器 $CONTAINER(只读挂载被测 api/,跑仓库当前代码)…"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker volume create "$DEPS_VOLUME" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" \
  --network "$NETWORK" -p "$PORT:8000" \
  --env-file "$SUT_REPO/.env" \
  -e DOCKER_ENV=true \
  -e LLM_MODEL_FAST=deepseek-v4-flash \
  -e LLM_MODEL_CHAT=deepseek-v4-flash \
  -e PYTHONPATH=/deps:/scaffold \
  -v "$SUT_REPO/api:/app:ro" \
  -v "$DEPS_VOLUME:/deps" \
  -v "$HERE:/scaffold:ro" \
  "$IMAGE" \
  sh -c "pip install --quiet --target=/deps python-multipart ddgs langchain-classic 2>&1 | tail -1; python /scaffold/sut_run.py" \
  >/dev/null || die "docker run 失败(镜像 $IMAGE 是否存在?)"

# 3) 等就绪 ------------------------------------------------------------------
for _ in $(seq 1 36); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$PORT/health" || true)" = "200" ]; then
    log "✅ /health 200"
    break
  fi
  sleep 5
done
curl -s --max-time 5 "http://127.0.0.1:$PORT/health" | grep -q '"status"' \
  || { docker logs --tail 20 "$CONTAINER" >&2; die "服务未就绪(日志见上)"; }

# 4) 能力探针(**必需**)------------------------------------------------------
# 教训(2026-09-11):/health 返回 200(database ok / redis ok)**不代表被测答得了** ——
# 当时被测的查询改写因 max_tokens 被推理吃满而返回空,检索退回垃圾文档,
# 只会表现为「无法回答」。不打这一枪,跑完的结果会被读成"被测质量崩了"。
if [ -z "$API_KEY" ]; then
  log "⚠ 未设 EVAL_SUT_FASTAPI_API_KEY,跳过能力探针(README 警告:不要跳过)"
else
  log "能力探针:发一条真实问答…"
  RESP="$(curl -s --max-time 120 -X POST "http://127.0.0.1:$PORT/api/v1/rag/search?mode=accurate_norerank" \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d '{"question":"Python 是一门什么样的编程语言？","top_k":3,"generate_answer":true,"citations":true}' || true)"
  echo "$RESP" | grep -q '"answer"' \
    || { echo "$RESP" | head -c 300 >&2; die "能力探针失败:被测无法作答(不要据此判质量,先归因环境)"; }
  log "✅ 能力探针通过(被测能作答)"
fi

log "就绪:被测在 http://127.0.0.1:$PORT(容器 $CONTAINER)"
