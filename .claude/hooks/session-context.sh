#!/bin/sh
# session-context:会话启动时把「skill 入口 + 对应表」**注入上下文**(SessionStart)。
#
# 依据:母体 KD-9 —— 「skills 装了却从不调用」。L1 虽把对应表写进 CLAUDE.md,
#   但它与"我读到并照做"之间仍隔着人的自觉。本 hook 用 SessionStart 的
#   `hookSpecificOutput.additionalContext` 把入口与表**每会话推到眼前**,
#   把"文件里有"提升为"上下文里有"。
#
# 说明:这是**中等强度**手段 —— 进了上下文 ≠ 一定会照做;真正可机器检测的硬门是
#   `.githooks/commit-msg`(改实现未改测试 → 拒绝提交)与 CI 的 skill 覆盖检查。
#
# 实现注:JSON 用**带引号的 heredoc** 输出 —— 避免 sh/zsh 的 printf/echo 对参数做转义
#   处理(曾因此产出含裸换行的非法 JSON)。
#
# opt-in:设 SESSION_CTX=1 才生效(注册处内联);可随时在 settings.json 移除。
[ "$SESSION_CTX" = "1" ] || exit 0

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"【skill 入口 · 每会话一次】开工前先调用 Skill 工具加载入口触发器 using-superpowers;下表【命中即必须调用】,不是『可以调用』:\n  写码/改码 → test-driven-development\n  声称『完成/修好/通过』 → verification-before-completion\n  请人评审代码 → requesting-code-review;收到评审意见 → receiving-code-review\n  阶段门验收 → gate-review;每次 commit/PR 前 → 留痕-checks\n  排查 bug/测试失败 → systematic-debugging;定调/优先级/压测方案 → grilling\n  写/执行实施计划 → writing-plans|executing-plans;需要隔离工作区 → using-git-worktrees\n  改 settings.json → update-config;新建/修改 skill 本身 → writing-skills;Kit 自身缺陷 → kit-feedback\n  完整 20 行分组表见 CLAUDE.md『纪律』段。\n  硬门提醒:本轮若改了 app/ 却没改 tests/,commit-msg hook 会拒绝提交(除非提交信息显式写 [no-test])。"}}
JSON
exit 0
