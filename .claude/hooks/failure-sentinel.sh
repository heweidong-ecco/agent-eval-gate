#!/bin/sh
# failure-sentinel:「失败即补 case」哨兵 —— 提醒"本轮失败入库了吗"(防漏,不做推理)。
#
# 依据:B `05-独立模块工作流/05-模块-评估与测试-v1.0.md:84`「失败即补 case」;
#      本仓 `eval/cases/README.md`(被测失败)与 `docs/复盘/`(我方过程错误)。
# 动机:2026-09-10 复盘发现——该纪律原先只写在 `eval/README.md`,不在每会话必读的
#      `CLAUDE.md` 锚点里、也无任何触发点 → 整个阶段3「零执行」(17 条错误散落 5 处)。
#      **纪律靠"记得",结构靠"躲不掉"** —— 本 hook 就是那处结构。
#
# opt-in:设 FAILURE_SENTINEL=1 才生效(避免每轮噪音);可随时在 settings.json 移除。
[ "$FAILURE_SENTINEL" = "1" ] || exit 0

cd "$(dirname "$0")/../.." || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

runs_dir=eval/runs
latest_run=$(ls -t "$runs_dir"/*.local.json 2>/dev/null | head -1)
[ -n "$latest_run" ] || exit 0

# 最近一轮评测有失败吗(summary.failed > 0)
grep -q '"failed": *[1-9]' "$latest_run" 2>/dev/null || exit 0

# 失败报告之后,失败集/复盘目录里有没有更新过?
newer=$(find eval/cases docs/复盘 -type f -newer "$latest_run" 2>/dev/null | head -1)
[ -n "$newer" ] && exit 0

printf '失败即补 case:最近一轮评测有失败(%s),但 eval/cases/ 与 docs/复盘/ 之后都没有更新。\n' "$latest_run"
printf '  → 被测的失败 → eval/cases/(带 regression.root_cause);我方过程错误 → docs/复盘/。\n'
exit 0
