#!/bin/sh
# subagent-guard —— 把仓库纪律**注入子 Agent 的上下文**(SubagentStart)。
#
# 缘起(2026-09-11,盲测 1/2/3 实证 + 母体 KD-9 / KD-10):
#   子 Agent **拿不到会话锚点(CLAUDE.md)、不触发 SessionStart/Stop hook、不继承会话纪律**,
#   它只认仓库层的东西。此前唯一的承载是一句**文字纪律**("派子 Agent 时把纪律写进任务描述"),
#   **没有任何结构兜底** —— 漏了不会红。本 hook 要补的就是这一层。
#
# 【为什么是 SubagentStart,而不是 PreToolUse(Agent)】
#   · SubagentStart 的 additionalContext **能真正到达**子 Agent —— 2026-09-11 实机验证:
#     它以 `hook_additional_context` system-reminder 的形式进入子 Agent 的上下文;
#   · 它**看不到任务 prompt**(实测 stdin 字段仅 agent_id/agent_type/cwd/prompt_id/session_id/
#     transcript_path),所以判据只能按 `agent_type` 分级,**不做 prompt 语义判断**
#     (自动判定"该用哪个 skill"需要语义,规则引擎给不出);
#   · PreToolUse(Agent) 的 updatedInput 在本版本被静默丢弃 → **不存在改写 prompt 这条路**。
#
# 【为什么这不算"无条件提醒"(会被忽略的那种)】
#   ① 收件人是**每单全新**的子 Agent,不存在"同一个 Agent 反复被告知同一件事"的疲劳;
#   ② **有判据**:只读型(不改码、不提交)**一个字都不发**;
#   ③ **人和主 Agent 都看不见** —— 不进主会话上下文,不占任何人的注意力;
#   ④ 有长度与动作约束:≤8 行,每条是"做什么 + 调哪个 skill",不是复述纪律。
#
# opt-in:设 SUBAGENT_GUARD=1 才生效(注册处内联);可随时在 settings.json 移除。
# 只读型集合可扩展:SUBAGENT_GUARD_READONLY_TYPES="my-reader,another-reader"

[ "$SUBAGENT_GUARD" = "1" ] || exit 0

payload=$(cat 2>/dev/null || true)
[ -n "$payload" ] || exit 0

# 取 agent_type(不依赖 jq)
atype=$(printf '%s' "$payload" | sed -n 's/.*"agent_type"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)

# 只读型 → 不发(防噪音)。可经 SUBAGENT_GUARD_READONLY_TYPES 追加(逗号分隔)。
readonly_types="Explore Plan claude-code-guide"
if [ -n "${SUBAGENT_GUARD_READONLY_TYPES:-}" ]; then
  readonly_types="$readonly_types $(printf '%s' "$SUBAGENT_GUARD_READONLY_TYPES" | tr ',' ' ')"
fi
for t in $readonly_types; do
  [ "$atype" = "$t" ] && exit 0
done
# 未知类型**默认发**(fail-safe):宁可多发,不可漏发。

# ⚠️ JSON 必须用**带引号的 heredoc** 输出。
#    用 printf/echo 时 sh/zsh 会处理参数转义 → `\n` 变成**裸换行** → 产出非法 JSON → hook 静默失效。
#    (这个坑已在 session-context.sh 里踩过一次,此处照抄其写法。)
cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"SubagentStart","additionalContext":"【仓库纪律 · 自动附加 v1】(REPO-DISCIPLINE-V1)\n你没有本仓的会话锚点,以下约束由仓库层自动注入:\n1) 改实现代码前先写会失败的测试,并调用 Skill(test-driven-development)。\n2) 声称完成/修好前调用 Skill(verification-before-completion)。\n3) 提交前调用 Skill(留痕-checks);提交信息遵守 Conventional Commits。\n4) 不要用 git commit --no-verify,不要用 [no-test]/[no-skill] 绕过门禁;确需豁免必须在提交信息里写明理由。\n5) 改了 app/ 却没改 tests/ → .githooks/commit-msg 会拒绝提交。这不是故障,是门禁在起作用:去补测试,不要绕。\n6) 完成后报告:改了哪些文件 / 跑了什么命令 / 有没有被门拦过。"}}
JSON
exit 0
