#!/bin/sh
# 灾备演练 —— 「门的灾」= **证据链丢失**(DEC-014 §5 阶段5-4)。
#
# 为什么"灾"是这个:
#   `eval/runs/*.trace.jsonl` 与 `*.local.json` 都被 gitignore(`.gitignore:24`),
#   只有脱敏 summary 进 git ⇒ 机器丢失时 **L1 基线无法重算**、报告/复盘引用失效。
#
# 本演练**不移动任何现有数据**(早期版本会 `mv eval/runs`,风险不必要)——
# 而是构造一个「**只剩 git 内容**」的目录,直接回答那个真问题:
#     "如果本地产物全没了,只靠 git,我们能不能把结论重算出来?多久?"
#
# 步骤:① 盘点 ② 构造"只剩 git"的恢复源 ③ 从它重算并计时 ④ 与已提交基线对比
# 用法:tools/dr_drill.sh     退出码:0 演练完成(无论恢复成败 —— 演练本身成功即可)
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
REC="$TMP/recovered"
RUNS_X=20260912-171456-f5c4a6ec,20260912-180913-432c0daa,20260912-182720-ee9c3495

echo
echo "══ 灾备演练:「门的灾」= 证据链丢失 ══"
echo
echo "① 盘点(证据在哪)"
tracked=$(cd "$ROOT" && git ls-files eval/runs | wc -l | tr -d ' ')
spans=$(cd "$ROOT" && git ls-files 'eval/runs/*.spans.jsonl' | wc -l | tr -d ' ')
trace_n=$(ls -1 "$ROOT/eval/runs"/*.trace.jsonl 2>/dev/null | wc -l | tr -d ' ')
local_n=$(ls -1 "$ROOT/eval/runs"/*.local.json 2>/dev/null | wc -l | tr -d ' ')
echo "   git 跟踪的 eval/runs 文件      : $tracked  (脱敏 summary)"
echo "   其中**归档的 span 摘录**        : $spans   (DEC-014 §4.1 的补救)"
echo "   仅在本地的 trace               : $trace_n"
echo "   仅在本地的报告原文             : $local_n  (含被测答案原文 —— 刻意不入库)"
echo
echo "② 构造「只剩 git 内容」的恢复源(不动 eval/runs)"
mkdir -p "$REC"
n=0
for id in $(echo "$RUNS_X" | tr ',' ' '); do
  if (cd "$ROOT" && git show "HEAD:eval/runs/$id.spans.jsonl") > "$REC/$id.trace.jsonl" 2>/dev/null; then
    n=$((n+1))
  else
    echo "   ⚠️ 缺归档:$id.spans.jsonl ⇒ 先跑 tools/archive_evidence.py"
  fi
done
echo "   已从 git 取出 $n 份(改名为 .trace.jsonl)"
[ "$n" -gt 0 ] || { echo "   ⇒ 无归档可用,演练到此为止(结论:不可恢复)"; exit 0; }
echo
echo "③ 从恢复源重算(计时 = MTTR 的恢复段)"
t0=$(date +%s)
"$PY" -m eval_gate stats --runs "$RUNS_X" --trace-dir "$REC" --out "$TMP/restored.json" >"$TMP/o" 2>&1
rc=$?
t1=$(date +%s)
echo "   exit=$rc · 耗时 $((t1-t0))s"
tail -2 "$TMP/o" | sed 's/^/   /'
echo
echo "④ 与**已提交的** eval/l1_baseline.json 对比(fastapi-rag)"
cd "$ROOT" || exit 1
"$PY" - "$TMP/restored.json" <<'PYEOF'
import json, sys
from pathlib import Path
commit = json.loads(Path("eval/l1_baseline.json").read_text(encoding="utf-8"))
try:
    rec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception as e:
    print("   ❌ 恢复产物读不到:", e); sys.exit(0)
def s(d):
    x = d["by_sut"]["fastapi-rag"]["sut_latency_ms"]
    return (x["n"], round(x["p50"], 3), round(x["p95"], 3), round(x["max"], 3))
a, b = s(commit), s(rec)
print(f"   已提交 : n={a[0]} p50={a[1]} p95={a[2]} max={a[3]}")
print(f"   恢复后 : n={b[0]} p50={b[1]} p95={b[2]} max={b[3]}")
print("   ⇒", "✅ **逐字一致** —— 归档摘录够重算" if a == b else "❌ 对不上(归档字段不足)")
PYEOF
echo
echo "── 演练结论 ──"
if [ "$rc" = 0 ]; then
  echo "   MTTR(**本次实测**):从"发现丢失"到"可重算" ≈ **$((t1-t0))s**(纯恢复段:从 git 取归档 + 重算)"
  echo "   对比:**补救前无界**(2026-09-13 首测:直接重算 → exit 3,证据不可恢复)。"
  echo "   补的就是 DEC-014 §4.1 的归档纪律 + tools/archive_evidence.py。"
else
  echo "   MTTR:**仍不可用** —— 归档不足以重算,回去补 tools/archive_evidence.py 的字段白名单。"
fi
echo
