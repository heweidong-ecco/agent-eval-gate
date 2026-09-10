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
ROOT="${GATE_REPO:-$PWD}"          # GATE_REPO 为测试缝(对临时仓跑)
git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

payload=$(cat 2>/dev/null || true)

# ---------- 本地门禁的**单一失效点**:core.hooksPath 被改走 ----------
# 改一行 git config,门 1 / 门 2 / post-commit **全部不再运行**,而不会有任何提示。
# 与 F1/F2 同型:机制的失效必须可被察觉。
hp=$(git -C "$ROOT" config --get core.hooksPath 2>/dev/null || true)
if [ "$hp" != ".githooks" ]; then
  printf '⚠ core.hooksPath = "%s"(应为 .githooks)→ 门 1 / 门 2 / post-commit **全部不生效**。\n' "$hp"
  printf '  恢复:git config core.hooksPath .githooks\n'
fi

# ---------- 绕过留痕:有记录就必须被看见 ----------
# `.githooks/post-commit` 在提交**被绕过**时记一笔(它不受 --no-verify 抑制)。
# 只写进日志没人看 = 等于没留 —— 故在此主动暴露。核对无误后清理该文件即可消警。
bypass="$ROOT/.claude/traces/bypass.jsonl"
if [ -f "$bypass" ]; then
  n=$(grep -c . "$bypass" 2>/dev/null || echo 0)
  printf '⚠ 绕过留痕:%s 条提交本应被门禁拦下却被绕过。最近一条:\n  %s\n' "$n" "$(tail -1 "$bypass" 2>/dev/null)"
  printf '  核对后清理 %s 以消警。\n' "$bypass"
fi

# ---------- 到达性:纪律注入是否真的到了子 Agent ----------
# 缘起(2026-09-11):`subagent-guard.sh`(SubagentStart)把纪律注入子 Agent,但**注入失效时
# 不会有任何东西变红** —— 子 Agent 照常工作,只是没人告诉它纪律。与 F1(门 2 证据链被写坏)
# 同型:机制的失效必须可被察觉。**判据 = 本会话派过子 Agent,却一份 transcript 都不含签名。**
# 无子 Agent 时不提醒(不误报、不刷屏)。
sid=$(printf '%s' "$payload" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
if [ -n "$sid" ]; then
  py="$ROOT/.venv/bin/python"
  [ -x "$py" ] || py=python3
  "$py" "$ROOT/tools/check_subagent_injection.py" "$sid" >/dev/null 2>&1 || \
    printf '⚠ 纪律注入未到达子 Agent(subagent-guard 可能已失效):本会话派过子 Agent 却无一含注入签名。\n'
fi

# ---------- 防漏:该用的 skill 都用了吗 ----------
# 仅当工作区确实有改动(说明本轮做了事)才提醒,避免静默轮次刷屏
git -C "$ROOT" status --porcelain 2>/dev/null | grep -q . || exit 0

printf 'skills: 本轮命中下表了吗(命中即【必须调用】)?'
printf ' 写码→test-driven-development · 称完成→verification-before-completion ·'
printf ' 阶段门→gate-review · 提交前→留痕-checks · 排查故障→systematic-debugging\n'
exit 0
