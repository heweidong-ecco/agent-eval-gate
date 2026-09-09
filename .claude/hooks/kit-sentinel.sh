#!/bin/sh
# kit-feedback 哨兵:提醒"是否该跑 Kit 缺陷判定"(防漏,不做推理)。
# opt-in:设环境变量 KIT_SENTINEL=1 才生效(避免每轮 Stop 噪音);可随时在 settings.json 移除。
[ "$KIT_SENTINEL" = "1" ] || exit 0

cd "$(dirname "$0")/../.." || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
if git status --porcelain 2>/dev/null | grep -q .; then
  printf 'kit-feedback: 刚过触发点了吗?自查是否暴露母体 Kit 缺陷——是则提请回写母体 product-agent-dev-os/docs/kit-缺陷登记.md(项目内不留表)。\n'
fi
exit 0
