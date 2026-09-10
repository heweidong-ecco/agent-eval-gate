#!/bin/sh
# skill-sentinel:节点收尾提醒「该用的 skill 都用了吗」(防漏,不做推理)。
#
# 动机(2026-09-11,KD-9):本仓阶段3 全程 **Skill 调用仅 2 次**,而 Bash 205 / Edit 146 ——
#      写码未走 TDD、阶段门未走 gate-review、提交未走 留痕-checks。
#      根因:CLAUDE.md 原句是「动手前查 skills **是否命中**」(笼统、无对应表、无"必须"),
#      且入口触发器 `using-superpowers` 未随 Kit 进入锚点。
#      **纪律靠"记得",结构靠"躲不掉"** —— 本 hook 即那处触发点;对应表见 CLAUDE.md「纪律」段。
#
# opt-in:设 SKILL_SENTINEL=1 才生效(注册处已内联);可随时在 settings.json 移除。
[ "$SKILL_SENTINEL" = "1" ] || exit 0

cd "$(dirname "$0")/../.." || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# 仅当工作区确实有改动(说明本轮做了事)才提醒,避免静默轮次刷屏
git status --porcelain 2>/dev/null | grep -q . || exit 0

printf 'skills: 本轮命中下表了吗(命中即【必须调用】)?'
printf ' 写码→test-driven-development · 称完成→verification-before-completion ·'
printf ' 阶段门→gate-review · 提交前→留痕-checks · 排查故障→systematic-debugging\n'
exit 0
