#!/bin/sh
# impl-guard —— **左移**的实现护栏(PreToolUse on Edit|Write)。
#
# 缘起(2026-09-11 盲测 + 业务方指出的设计缺陷):
#   `commit-msg` 是**滞后门** —— 它在"最后提交"时才拦。对长任务这意味着:
#   ① Agent 可能已经做了大量实现决策,却从未被测试驱动 → 事后补测试只是**改装**,不是 TDD;
#   ② 任务若在中途结束/被打断 → **没有任何门触发过**,纪律被无声违反;
#   ③ 结果是"中间全白费"。
#   → **门禁必须左移到"动手那一刻",而不是"提交那一刻"。**
#
# 本 hook 做的是 TDD 的**顺序强制**:要改实现文件,而工作区/暂存区**尚无任何测试改动**
#   → 先问一句(不硬拦:人可以放行)。写了测试之后再改实现,就不再打扰。
#
# 输出语义:`permissionDecision: "ask"` —— 把决定权留给人(左移但不误伤)。
# opt-in:设 IMPL_GUARD=1 才生效(注册处内联);可随时在 settings.json 移除。

[ "$IMPL_GUARD" = "1" ] || exit 0

payload=$(cat 2>/dev/null || true)
[ -n "$payload" ] || exit 0

# 取 file_path(不依赖 jq)
fpath=$(printf '%s' "$payload" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
[ -n "$fpath" ] || exit 0

# 只在"实现目录"上管(按项目实际改)
case "$fpath" in
  */app/*|*/backend/*|*/src/*) : ;;
  *) exit 0 ;;
esac
# 测试文件本身放行(那正是我们要鼓励的)
case "$fpath" in
  */tests/*|*/test_*|*_test.*) exit 0 ;;
esac

# 工作区/暂存区是否已有测试改动?
cd "$(dirname "$0")/../.." 2>/dev/null || exit 0
tst=$( { git diff --name-only HEAD -- '*/tests/*' 'tests/*' 2>/dev/null
         git diff --cached --name-only -- '*/tests/*' 'tests/*' 2>/dev/null; } | sort -u | wc -l | tr -d ' ')
[ "$tst" -gt 0 ] && exit 0

reason='还没写测试就要改实现文件 —— 建议先走 test-driven-development(先写会失败的测试)。
若这是纯重构/配置改动,或你已确认要直接改,请放行即可(本提示不阻断,只把决定权提前给你)。'

printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"%s"}}\n' \
  "$(printf '%s' "$reason" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\n' ' ')"
exit 0
