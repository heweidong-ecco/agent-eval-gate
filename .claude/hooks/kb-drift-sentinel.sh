#!/bin/sh
# kb-drift-sentinel:避坑库变动提醒 —— 防止「指针指向已改名/已移动/已过期的知识库」。
#
# 动机:避坑库(`知识库/18.Agent避坑库-问题解决策略/`)是**跨项目、可能跨机器同步**的,
#      而项目里的指针是**写死的路径**。库一旦改名/移动/在别的电脑上增删,指针就会静默失效 ——
#      这正是「纪律只有文字、没有触发点」的翻版,故按同一原则补一处结构(见避坑库 §1)。
#
# 事件选用 **SessionStart**(而非 Stop):一次开工查一次 ——
#      ① 能覆盖「在别的电脑上改过、本机同步过来」;② 不会每轮刷屏。
# 状态:`.claude/.kb-avoid-manifest`(每台机器各自维护,已 gitignore)。
#
# opt-in:设 KB_SENTINEL=1 才生效(注册处已内联设置);可用 KB_AVOID_PITFALLS_DIR 覆盖库路径。
[ "$KB_SENTINEL" = "1" ] || exit 0

KB="${KB_AVOID_PITFALLS_DIR:-$HOME/Desktop/知识库/18.Agent避坑库-问题解决策略}"
ROOT="$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)" || exit 0
MANIFEST="$ROOT/.claude/.kb-avoid-manifest"

if [ ! -d "$KB" ]; then
  printf '[避坑库] ⚠ 目录不存在:%s\n' "$KB"
  printf '         → 项目/母体里的指针可能已失效(被改名、被移动,或本机未同步)。请核对并更新指针。\n'
  exit 0
fi

now=$(cd "$KB" && find . -type f ! -name '.DS_Store' | LC_ALL=C sort | while IFS= read -r f; do
  printf '%s %s\n' "$(wc -c < "$f" | tr -d ' ')" "$f"
done)

tmp=$(mktemp) || exit 0
printf '%s\n' "$now" > "$tmp"

if [ -f "$MANIFEST" ] && ! cmp -s "$MANIFEST" "$tmp"; then
  printf '[避坑库] 有变动(与上次会话相比):\n'
  diff "$MANIFEST" "$tmp" 2>/dev/null | sed -n 's/^> /  + /p; s/^< /  - /p'
  printf '         → 请确认:① 指针路径是否仍有效;② 新策略是否需同步进本项目 / 母体 Kit。\n'
fi

mv "$tmp" "$MANIFEST" 2>/dev/null
exit 0
