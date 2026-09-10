#!/bin/sh
# skill-trace —— 把本会话(**含子 Agent**)的 Skill 调用落成**机器可读 trace**。
#
# 缘起(2026-09-11,更正一处早先的判断):
#   本文档曾写「skill 调用不落 git,CI 看不见 → 无法强制」。**只对了一半**:
#   CI 确实看不见,但 **hook 能看见** —— Skill 调用**落在本机 session transcript 里**
#   (`~/.claude/projects/<sanitized-cwd>/<session_id>.jsonl`),子 Agent 的也在
#   (`<session_dir>/tasks/<agent_id>.output`)。本 hook 把它们抽成仓库内的 trace,
#   于是 `.githooks/commit-msg` 就能**校验 skill 是否真的被调用过** —— 从软变硬。
#
# 产物:`.claude/traces/latest.json`(当前会话,被 commit-msg 读)+ `<session_id>.json`
#   (已 gitignore:它是"本机本次会话"的事实,不是仓库内容)
#
# opt-in:设 SKILL_TRACE=1 才生效(注册处内联)。

[ "$SKILL_TRACE" = "1" ] || exit 0

payload=$(cat 2>/dev/null || true)
sid=$(printf '%s' "$payload" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
[ -n "$sid" ] || exit 0

ROOT=$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd) || exit 0
mkdir -p "$ROOT/.claude/traces" 2>/dev/null || exit 0

# 主会话 transcript
main=$(find "$HOME/.claude/projects" -name "$sid.jsonl" 2>/dev/null | head -1)
# 子 Agent transcript(会话目录下的 tasks/*.output 是子 Agent 会话的 JSONL)
subs=$(find /private/tmp /tmp -maxdepth 5 -path "*${sid}*/tasks/*.output" 2>/dev/null | head -50)

skills=""
for f in "$main" $subs; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  s=$(grep -o '"name":"Skill","input":{"skill":"[^"]*"' "$f" 2>/dev/null | sed 's/.*"skill":"//; s/"$//')
  [ -n "$s" ] && skills=$(printf '%s\n%s\n' "$skills" "$s")
done

# 去重 + 计数(去掉空行)
uniq_skills=$(printf '%s\n' "$skills" | sed '/^$/d' | LC_ALL=C sort | uniq -c | awk '{printf "%s(%s) ", $2, $1}')

count=$(printf '%s\n' "$skills" | sed '/^$/d' | wc -l | tr -d ' ')

json=$(printf '{"session_id":"%s","at":"%s","skill_calls":%s,"skills":"%s","sources":{"main":"%s","subagents":%s}}\n' \
  "$sid" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$count" "$(printf '%s' "$uniq_skills" | sed 's/ *$//')" \
  "${main:-}" "$(printf '%s\n' $subs | sed '/^$/d' | wc -l | tr -d ' ')")

printf '%s' "$json" > "$ROOT/.claude/traces/$sid.json" 2>/dev/null
printf '%s' "$json" > "$ROOT/.claude/traces/latest.json" 2>/dev/null
exit 0
