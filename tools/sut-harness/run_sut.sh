#!/usr/bin/env bash
# 在容器里跑真实被测(`01.FastAPI RAG Agent`),供评测门做真实链路评测用。
#
# 定位:**评测门的运行适配层**,不是被测的一部分。被测仓零改动 ——
# 只读挂载它的源码目录(`app/`,兼容旧的 `api/`),所有补丁都在容器运行时。
#
# 🔴 2026-10-18:被测仓结构已从 `api/` 改为 `app/`,并有了**官方镜像**
#    `fastapi-rag-agent:latest`(由被测仓 `app/Dockerfile` 构建)
#    ⇒ 达到本 harness README 的「退出条件」,改走官方镜像;
#      旧的 `pip 补装 /deps 卷 + sut_run.py` 启动路径**退役**(文件保留,不再使用)。
#
# 用法:
#   tools/sut-harness/run_sut.sh
#   # 评测隔离库 / 放宽会话预算(新版被测默认 5 万,单轮会触顶)
#   EVAL_SUT_DB=rag_eval_20261018 EVAL_SUT_SESSION_TOKEN_LIMIT=200000 tools/sut-harness/run_sut.sh
#
# 退出码:0 = 就绪且**能力探针通过**;1 = 起不来;2 = 起来了但答不了(见 README §陷阱)
set -euo pipefail

SUT_REPO="${EVAL_SUT_REPO:-/Users/heweidong/Desktop/Product/agent-projects/projects/fastapi-rag-agent}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
IMAGE="${EVAL_SUT_IMAGE:-fastapi-rag-agent:latest}"
CONTAINER="${EVAL_SUT_CONTAINER:-rag-api-eval}"
NETWORK="${EVAL_SUT_NETWORK:-fastapi-rag-agent_app-net}"
PORT="${EVAL_SUT_PORT:-8000}"
API_KEY="${EVAL_SUT_FASTAPI_API_KEY:-}"
IDENTITY="${EVAL_SUT_IDENTITY:-$ROOT/eval/runs/.sut-harness.env}"
LOGS_DIR="${EVAL_SUT_LOGS_DIR:-$ROOT/eval/runs/sut-logs}"

log() { printf '[sut-harness] %s\n' "$*"; }
die() { printf '[sut-harness] ✗ %s\n' "$*" >&2; exit 1; }

# 0) 源码目录:优先新结构 `app/`,兼容旧结构 `api/` ----------------------------
if [ -d "$SUT_REPO/app" ]; then
  SUT_SRC="$SUT_REPO/app"
elif [ -d "$SUT_REPO/api" ]; then
  SUT_SRC="$SUT_REPO/api"
else
  die "被测仓路径不对(缺 app/,也没有旧 api/):$SUT_REPO —— 用 EVAL_SUT_REPO 指定"
fi
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

# 2) 起被测容器(官方镜像 + 只读挂载当前源码)----------------------------------
# ⚠️ 必须显式 -e 覆盖这两个变量:docker run --env-file **不剥离行内注释**,
#    被测 .env 里 `LLM_MODEL_FAST=deepseek-v4-flash   # …` 会把注释整段当值。
log "重建容器 $CONTAINER(官方镜像 $IMAGE;只读挂载 $SUT_SRC → /src → 复制到可写 /app)…"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
mkdir -p "$LOGS_DIR"   # 应用要往 /app/logs 写文件 ⇒ 单独给可写目录(且不写进被测仓)

# ⚠️ 不直接把源码只读挂到 /app:应用会在 /app/.mem0/qdrant 等路径写运行时状态
#    (2026-10-18 实测:只读挂载 ⇒ OSError [Errno 30] Read-only file system: '/app/.mem0/qdrant/.lock')
# ⇒ 只读挂 /src,容器启动时复制到可写 /app,再跑 uvicorn。这样既跑**当前代码**,也不碰被测仓。

# 可选覆盖:评测隔离库 / 会话预算(未设置则沿用 .env / 应用默认值)
EXTRA_ENV=()
[ -n "${EVAL_SUT_DB:-}" ] && EXTRA_ENV+=(-e "POSTGRES_DB=$EVAL_SUT_DB")
[ -n "${EVAL_SUT_SESSION_TOKEN_LIMIT:-}" ] && EXTRA_ENV+=(-e "SESSION_TOKEN_LIMIT=$EVAL_SUT_SESSION_TOKEN_LIMIT")

docker run -d --name "$CONTAINER" \
  --network "$NETWORK" -p "$PORT:8000" \
  --env-file "$SUT_REPO/.env" \
  -e DOCKER_ENV=true \
  -e LLM_MODEL_FAST=deepseek-v4-flash \
  -e LLM_MODEL_CHAT=deepseek-v4-flash \
  ${EXTRA_ENV[@]+"${EXTRA_ENV[@]}"} \
  -v "$SUT_SRC:/src:ro" \
  -v "$LOGS_DIR:/app/logs" \
  "$IMAGE" \
  sh -c 'cp -a /src/. /app/ && exec uvicorn main:app --host 0.0.0.0 --port 8000' \
  >/dev/null || die "docker run 失败(镜像 $IMAGE 是否存在?先 docker images | grep fastapi-rag)"

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
  if ! echo "$RESP" | grep -q '"answer"'; then
    echo "$RESP" | head -c 300 >&2
    printf '[sut-harness] ✗ 能力探针失败:被测无法作答(不要据此判质量,先归因环境)\n' >&2
    exit 2   # 契约:2 = 起来了但答不了(与 README / 故障手册一致)
  fi
  log "✅ 能力探针通过(被测能作答)"
fi

log "就绪:被测在 http://127.0.0.1:$PORT(容器 $CONTAINER)"

# ── 被测侧自证(DEC-016)────────────────────────────────────────
# 门**不可能**自己知道被测的 commit,也不该去问 ⇒ 由本层(唯一知道被测仓与探针结果的一层)导出。
# 写出而非 export:本脚本是子进程,export 传不回调用者的 shell。
# 用法:跑评测前 `set -a; . eval/runs/.sut-harness.env; set +a`
SUT_COMMIT="$(git -C "$SUT_REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)"
PROBE_RESULT="ok"
[ -z "$API_KEY" ] && PROBE_RESULT="skipped"
mkdir -p "$(dirname "$IDENTITY")"
cat > "$IDENTITY" <<EOF
# 由 tools/sut-harness/run_sut.sh 自动生成(勿手改);DEC-016 的被测侧自证
EVAL_SUT_VERSION=$SUT_COMMIT
EVAL_SUT_PROBE=$PROBE_RESULT
EOF
log "被测自证已写入 $IDENTITY(commit=$SUT_COMMIT · 探针=$PROBE_RESULT)"
log "⇒ 跑评测前先:set -a; . $IDENTITY; set +a"
