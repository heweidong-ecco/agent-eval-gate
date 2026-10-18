#!/usr/bin/env bash
# 离线自证:good → exit 0,bad → exit 1。
# 不联网、不需要任何 key。用法:./examples/offline-demo.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || {
  echo "先安装 dev 环境:python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
}

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
EVALS="$ROOT/eval/mini_rag_qa.evals.json"

echo "== good(期望 exit 0)=="
"$PY" -m eval_gate run --evals "$EVALS" --mode good --offline --report-dir "$OUT"
GOOD=$?

echo "== bad(期望 exit 1)=="
"$PY" -m eval_gate run --evals "$EVALS" --mode bad --offline --report-dir "$OUT"
BAD=$?

echo
echo "good=$GOOD(期望 0)· bad=$BAD(期望 1)"
if [ "$GOOD" -eq 0 ] && [ "$BAD" -eq 1 ]; then
  echo "✅ 自证通过:门能拿到 0,也能拦住劣化"
  exit 0
fi
echo "❌ 退出码不符合预期 —— 先查环境/安装,不要当成被测问题" >&2
exit 1
