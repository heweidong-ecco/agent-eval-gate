#!/bin/sh
# check-skill-coverage —— 确保「已安装的 skill」都被「路由/锚点文档」覆盖。
#
# 动机(母体缺陷 KD-9):skills 装了却从不被调用,根因之一是【没有机制保证新增 skill 被登记】——
#   枚举式硬编码的对应表,Kit 一加新 skill 就会漏。本脚本把
#   「新增 skill 必须同时更新路由与锚点表」变成**可检验的硬门**(CI 可跑)。
#
# 用法:
#   check-skill-coverage.sh <skills_dir>... -- <doc_file>...
#   例(母体):    tools/check-skill-coverage.sh skills -- skills-router.md scaffold/agent/CLAUDE.md
#   例(派生项目): tools/check-skill-coverage.sh .claude/skills -- CLAUDE.md
#
# 判定:skills_dir 下的每个 skill(含 SKILL.md 的子目录)必须在**至少一个** doc_file 里被提及;
#       否则报错并给出「该补哪三处」。另:doc 里若完全没提入口触发器 using-superpowers → 警告。
# 退出码:0 = 全覆盖;1 = 有未登记 skill;2 = 用法错误。

set -u

usage() {
  echo "用法: $0 <skills_dir>... -- <doc_file>..." >&2
  exit 2
}

[ "$#" -ge 3 ] || usage

# 解析 -- 分隔的两组参数
SKILL_DIRS=""
DOC_FILES=""
parsing_skills=1
for arg in "$@"; do
  if [ "$arg" = "--" ]; then parsing_skills=0; continue; fi
  if [ "$parsing_skills" = "1" ]; then SKILL_DIRS="$SKILL_DIRS $arg"; else DOC_FILES="$DOC_FILES $arg"; fi
done
[ -n "$SKILL_DIRS" ] && [ -n "$DOC_FILES" ] || usage

# 收集已安装 skill 名
NAMES=""
for d in $SKILL_DIRS; do
  [ -d "$d" ] || { echo "check-skill-coverage: 目录不存在: $d" >&2; exit 2; }
  for p in "$d"/*/; do
    [ -f "$p/SKILL.md" ] || continue
    NAMES="$NAMES $(basename "$p")"
  done
done

# 校验每个 doc 文件存在
for f in $DOC_FILES; do
  [ -f "$f" ] || { echo "check-skill-coverage: 文档不存在: $f" >&2; exit 2; }
done

missing=""
count=0
for n in $NAMES; do
  count=$((count + 1))
  found=0
  for f in $DOC_FILES; do
    if grep -q -- "$n" "$f" 2>/dev/null; then found=1; break; fi
  done
  [ "$found" = "1" ] || missing="$missing $n"
done

# 入口触发器是否被提及(警告,不阻断)
entry_ok=1
for f in $DOC_FILES; do grep -q -- "using-superpowers" "$f" 2>/dev/null && entry_ok=0; done

if [ "$entry_ok" = "1" ]; then
  echo "::warning::文档里未提及入口触发器 using-superpowers —— 它是让对应表被想起的开关(KD-9)。"
fi

if [ -n "$missing" ]; then
  echo "::error::以下 skill 已安装,但未在任何路由/锚点文档中登记:"
  for n in $missing; do echo "::error::  - $n"; done
  echo "::error::新增 skill 必须【同时】做三件事(否则触发规约失效):"
  echo "::error::  ① 在 skills-router.md 登记「何时用」;"
  echo "::error::  ② 在 CLAUDE.md 的「技能对应表」补一行(插到对应阶段);"
  echo "::error::  ③ 若要强制,补触发(hook)或门禁(CI 检查)。"
  exit 1
fi

echo "✅ skill 覆盖检查通过:$count 个已安装 skill,全部已在路由/锚点文档登记"
exit 0
