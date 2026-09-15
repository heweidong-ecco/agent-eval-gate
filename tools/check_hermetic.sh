#!/bin/sh
# 密闭性自检 —— 证明**测试不依赖"本机恰好存在的产物"**。
#
# 为什么需要它(2026-09-13 实证):
#   新写的 `tests/test_archive_evidence.py` 去 glob `eval/runs/*.trace.jsonl` ——
#   而那些文件**被 gitignore**,**CI 上根本不存在** ⇒ 该测试**本地绿、CI 红**(`StopIteration`)。
#   这类"只在我机器上通过"的测试,靠人记得去查是不可靠的 ⇒ 做成可复跑的自检。
#
# 做法(**从不碰工作区**):`git archive HEAD` 导出**只含 git 跟踪文件**的树 ——
#   那正是 CI 看到的那棵树;在其中跑全量测试。任何"依赖本地被忽略产物"的测试在这里必红。
#   ⚠️ 刻意**不**用"把本地产物移开再跑、跑完移回"—— 那条路一旦中断就留下残局
#      (`tools/dr_drill.sh` 的早期版本正栽在这上面)。
#
# 用法:tools/check_hermetic.sh        退出码:0 通过 · 1 有测试依赖本地产物
set -u

ROOT="${GATE_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"   # GATE_REPO = 测试缝(对临时仓跑)
PY="${GATE_PY:-$ROOT/.venv/bin/python}"                  # GATE_PY   = 测试缝(指定解释器)
[ -x "$PY" ] || PY=python3
TMP=$(mktemp -d)
# ⚠️ 解析软链:macOS 上 /var 是指向 /private/var 的软链,而 python 报的是**已解析**路径 ⇒
# 不解析的话,下面"自证用的确实是临时树"那一步会**误判**(本自检第一版即栽在这)。
TMP=$(cd "$TMP" && pwd -P)
trap 'rm -rf "$TMP"' EXIT

echo
echo "══ 密闭性自检:测试是否依赖本地产物 ══"
echo

# 被忽略项的数量(只报数,不动它)
n_ignored=$(cd "$ROOT" && git status --ignored --porcelain 2>/dev/null | grep -c '^!!' || true)
echo "① 工作区里有 $n_ignored 个 git **忽略**项 —— 正是本自检要排除的东西"

echo "② 导出「只含 git 跟踪文件」的树(= CI 看到的那棵)"
git -C "$ROOT" archive HEAD | tar -x -C "$TMP" || { echo "  ❌ git archive 失败"; exit 1; }
echo "   已导出到临时树(不含任何本地产物)"
# ⚠️ **临时树必须是个真 git 仓**,否则模型不忠实 ⇒ 会**假报不密闭**。
#    第一版就栽在这:`skill-sentinel.sh` 第 15 行「不在 git 工作树里就 exit 0」⇒
#    两条 hook 测试红了 —— 而 CI 是**真克隆**,根本不会这样。
#    这里补齐 CI 的两件事:`git init` + `setup-hooks.sh` 的效果(`core.hooksPath`)。
git -C "$TMP" init -q
git -C "$TMP" config core.hooksPath .githooks
# ⚠️ **索引必须填充**(2026-09-15 实证):`git archive` 只**导出文件**,**不建索引** ⇒
#    临时树是个"有工作区、没索引"的仓。而**真 clone 的索引是满的** ⇒
#    任何用 `git ls-files` 判断"这个文件在不在 git 里"的检查,在这里看到**空仓** ——
#    于是它**CI 绿、自检红**,自检**假报不密闭**(把忠实的环境说成不忠实)。
#    触发实例:`tools/check_evidence_coverage.py`(DEC-018)用 `git ls-files` 判归档是否存在。
git -C "$TMP" add -A
echo "   已初始化 git 仓、设 core.hooksPath、并填充索引(对齐 CI 的 clone + setup-hooks.sh)"

# ⚠️ 自检必须先证明"它测的确实是那棵树" —— 否则它自己就是又一个"看起来在测"的检查
echo "③ 自证:确认 import 的是**临时树里的** eval_gate,不是本机安装的那份"
got=$(cd "$TMP" && PYTHONPATH="$TMP/app" "$PY" -c 'import eval_gate,os;print(os.path.realpath(eval_gate.__file__))' 2>/dev/null)
case "$got" in
  "$TMP"/*) echo "   ✅ 用的是 $got" ;;
  *) echo "   ❌ 用的是 $got(不在临时树里)—— 本自检无效,先修它"; exit 2 ;;
esac

echo "④ 在临时树里跑全量测试"
out=$(cd "$TMP" && PYTHONPATH="$TMP/app" "$PY" -m pytest -q 2>&1)
rc=$?          # ⚠️ 直接取命令退出码;不要从管道或 tail 取(今日 C1 教训)
echo "$out" | tail -4 | sed 's/^/   /'

echo
if [ "$rc" = 0 ]; then
  echo "── 结论:✅ 密闭 —— 全量测试在「只含 git 跟踪文件」的树上通过"
else
  echo "── 结论:❌ **不密闭** —— 有测试依赖了本地产物(CI 会红)"
  echo "   自查法:看上面失败项是否读了 eval/runs/ 等被忽略路径;改成自造 fixture。"
fi
echo
[ "$rc" = 0 ] || exit 1
