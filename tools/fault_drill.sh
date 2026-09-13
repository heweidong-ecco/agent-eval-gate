#!/bin/sh
# 故障演练 —— 逐场景注入,校验「退出码 + 可观测信号」是否与《故障场景应对手册》一致。
#
# 为什么要有它(而不只是单元测试):
#   `tests/test_resilience.py` 是 **CI 级断言**(离线、快、每次提交都跑);
#   本脚本是 **运行级演练** —— 用**真实 CLI 子进程**跑一遍故障路径,
#   给人和 B 阶段5 门禁一个"演练通过"的可复跑证据。
#
# **零外网、零 token**:所有场景走 `--offline`(FakeJudge)或把端点指向**不可达地址**
# (连接被拒,不会发出真实模型请求)。
#
# 用法:tools/fault_drill.sh [--verbose]
# 退出码:0 全部符合预期 · 1 有场景不符(逐条打印实得 vs 期望)
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
EVALS="$ROOT/eval/mini_rag_qa.evals.json"
GOLDEN="$ROOT/eval/fastapi_rag_golden.evals.json"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
VERBOSE=${1:-}

pass=0; fail=0
# drill <名称> <期望exit> <期望stderr子串|-> <命令...>
drill() {
  name=$1; want_rc=$2; want_msg=$3; shift 3
  out="$TMP/out.$$"; err="$TMP/err.$$"
  "$@" >"$out" 2>"$err"; rc=$?
  ok=1
  [ "$rc" = "$want_rc" ] || ok=0
  if [ "$want_msg" != "-" ]; then
    grep -q "$want_msg" "$err" "$out" 2>/dev/null || ok=0
  fi
  if [ "$ok" = 1 ]; then
    note=""   # ⚠️ 用 ${} 界定:多字节引号紧跟 $var 时,部分 shell 会把引号字节吞进变量名
    [ "$want_msg" = "-" ] || note="(含「${want_msg}」)"
    pass=$((pass+1)); printf '  ✅ %-28s exit=%s %s\n' "$name" "$rc" "$note"
  else
    fail=$((fail+1)); printf '  ❌ %-28s 期望 exit=%s/含「%s」,实得 exit=%s\n' "$name" "$want_rc" "$want_msg" "$rc"
    [ "$VERBOSE" = "--verbose" ] && { echo "     --- stderr ---"; tail -5 "$err" | sed 's/^/     /'; }
  fi
}

printf '\n[fault-drill] 故障演练(离线/零 token)· 期望值取自 docs/故障场景应对手册.md\n\n'

printf '  ── 基线(对照组)──\n'
drill "good 离线 → 全绿" 0 - \
  env EVAL_TRACE=1 EVAL_DOTENV=0 "$PY" -m eval_gate run --evals "$EVALS" --mode good --offline --report-dir "$TMP/r1"
drill "bad 离线 → 劣化被拦" 1 - \
  env EVAL_TRACE=1 EVAL_DOTENV=0 "$PY" -m eval_gate run --evals "$EVALS" --mode bad --offline --report-dir "$TMP/r2"

printf '\n  ── 阈值配置故障 ──\n'
drill "阈值文件缺失(显式指定)→ exit 3" 3 "不可读" \
  env EVAL_TRACE=1 EVAL_DOTENV=0 "$PY" -m eval_gate run --evals "$EVALS" --mode good --offline \
      --threshold "$TMP/不存在.json" --report-dir "$TMP/r3"
printf '{ not json' > "$TMP/bad.json"
drill "阈值形状不合法(显式指定)→ exit 3" 3 "不可读" \
  env EVAL_TRACE=1 EVAL_DOTENV=0 "$PY" -m eval_gate run --evals "$EVALS" --mode good --offline \
      --threshold "$TMP/bad.json" --report-dir "$TMP/r4"

printf '\n  ── 被测 / 判分器故障 ──\n'
# 端点指向不可达地址(端口 9)——连接被拒,不会发出真实模型请求
drill "被测不可达 → 逐条 fail 不崩" 1 - \
  env EVAL_TRACE=1 EVAL_DOTENV=0 EVAL_SUT_FASTAPI_BASE_URL=http://127.0.0.1:9 \
      EVAL_SUT_BACKOFF_S=0 EVAL_SUT_429_BACKOFF_S=0 \
      "$PY" -m eval_gate run --evals "$GOLDEN" --offline --report-dir "$TMP/r5"
drill "judge 不可达 → 不崩" 1 "judge" \
  env EVAL_TRACE=1 EVAL_DOTENV=0 EVAL_JUDGE_BASE_URL=http://127.0.0.1:9 \
      EVAL_JUDGE_API_KEY=drill EVAL_JUDGE_MODEL=drill \
      "$PY" -m eval_gate run --evals "$EVALS" --report-dir "$TMP/r6"

printf '\n  ── 门自身 / 环境故障 ──\n'
drill "评测集不存在 → exit 3" 3 - \
  env EVAL_TRACE=1 EVAL_DOTENV=0 "$PY" -m eval_gate run --evals "$TMP/没有.json" --offline --report-dir "$TMP/r7"
printf 'x' > "$TMP/not-a-dir"
drill "产物目录是文件 → exit 3(非 1)" 3 "配置/运行错误" \
  env EVAL_TRACE=1 EVAL_DOTENV=0 "$PY" -m eval_gate run --evals "$EVALS" --mode good --offline --report-dir "$TMP/not-a-dir"
drill "EVAL_TRACE=0 → L1 不可测即阻断" 1 "绕过口" \
  env EVAL_TRACE=0 EVAL_DOTENV=0 "$PY" -m eval_gate run --evals "$EVALS" --mode good --offline --report-dir "$TMP/r8"

printf '\n[fault-drill] 通过 %s / 不符 %s\n' "$pass" "$fail"
[ "$fail" = 0 ] || { echo "[fault-drill] ⚠️ 有场景与手册不一致 —— 先修不一致,别改手册去迁就实现"; exit 1; }
echo "[fault-drill] ✅ 全部场景与《故障场景应对手册》一致"
