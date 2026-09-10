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
# 输出目录可注入(测试用临时目录,不碰生产路径 —— 见 F1)
TRACE_DIR="${SKILL_TRACE_DIR:-$ROOT/.claude/traces}"
mkdir -p "$TRACE_DIR" 2>/dev/null || exit 0

# 主会话 transcript
main=$(find "$HOME/.claude/projects" -name "$sid.jsonl" 2>/dev/null | head -1)

# 【F1 修复 · 2026-09-11】定位不到本会话 transcript → **一个字都不写**。
#   反面教训:原先无条件覆写 latest.json,于是**未知 session_id(如测试自身)**
#   把它写成 `skill_calls:0` —— 而 latest.json 正是**门 2 的唯一判定依据**。
#   结果:跑一次 pytest 就毁掉证据链 → 之后所有实现类提交被误判「没调用过 skill」而拦下。
#   **门禁的证据链,不能被任何自动化流程(含它自己的测试)写坏。**
[ -n "$main" ] || exit 0
# 子 Agent transcript(会话目录下的 tasks/*.output 是子 Agent 会话的 JSONL)
subs=$(find /private/tmp /tmp -maxdepth 5 -path "*${sid}*/tasks/*.output" 2>/dev/null | head -50)

skills=""
bash_n=0
edit_n=0
for f in "$main" $subs; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  s=$(grep -o '"name":"Skill","input":{"skill":"[^"]*"' "$f" 2>/dev/null | sed 's/.*"skill":"//; s/"$//')
  [ -n "$s" ] && skills=$(printf '%s\n%s\n' "$skills" "$s")
  # 口径字段的原始素材:次数(量)与种类(覆盖)必须**同时可见** ——
  # 拿「Skill 次数 vs Bash 次数」比是**粒度错位**(Skill 每工作单元一次,Bash 每命令一次),
  # 该比值没有阈值。此处只采集事实,**不设阈值、不做门禁**。
  bash_n=$((bash_n + $(grep -o '"name":"Bash"' "$f" 2>/dev/null | wc -l | tr -d ' ')))
  edit_n=$((edit_n + $(grep -o '"name":"Edit"' "$f" 2>/dev/null | wc -l | tr -d ' ')))
done

# 去重 + 计数(去掉空行)
uniq_skills=$(printf '%s\n' "$skills" | sed '/^$/d' | LC_ALL=C sort | uniq -c | awk '{printf "%s(%s) ", $2, $1}')

count=$(printf '%s\n' "$skills" | sed '/^$/d' | wc -l | tr -d ' ')
# 种类数(去重):**失效判据看这个** —— KD-9 的病是"种类错了"(与工作无关),不是次数少了
kinds=$(printf '%s\n' "$skills" | sed '/^$/d' | LC_ALL=C sort -u | wc -l | tr -d ' ')

json=$(printf '{"session_id":"%s","at":"%s","skill_calls":%s,"kinds":%s,"skills":"%s","bash_calls":%s,"edit_calls":%s,"sources":{"main":"%s","subagents":%s}}\n' \
  "$sid" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$count" "$kinds" "$(printf '%s' "$uniq_skills" | sed 's/ *$//')" \
  "$bash_n" "$edit_n" "${main:-}" "$(printf '%s\n' $subs | sed '/^$/d' | wc -l | tr -d ' ')")

printf '%s' "$json" > "$TRACE_DIR/$sid.json" 2>/dev/null
printf '%s' "$json" > "$TRACE_DIR/latest.json" 2>/dev/null
exit 0
