#!/usr/bin/env bash
# 激活本仓的本地门禁钩子(`.githooks/commit-msg`、`.githooks/post-commit`)。
#
# **为什么需要这一步**:`.githooks/` 里的脚本**不会自动生效** —— git 只会看
# `core.hooksPath` 指向哪里。而那是**本机 git 配置**,**克隆不携带**。
# 于是:新克隆/新机器上,本地硬门(门 1 TDD 痕迹、门 2 skill 调用)**静默失效**,
# 提交照常通过,**没有任何提示**。这与 KD-8「hook 静默失效」是同一类问题。
#
# **谁跑它**:
#   · 开发者:克隆后跑一次(README「快速开始」/ `docs/部署.md` 有指引);
#   · CI:`.github/workflows/eval-gate.yml` 也跑 —— 这样 `tests/test_hooks.py` 里
#     那条「core.hooksPath 必须指向 .githooks」的断言才是**在验证本脚本有效**,
#     而不是在验证"某台机器碰巧配过"。
#
# 幂等:重复执行无副作用。退出码:0 成功 / 1 环境不对。
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$ROOT" ]; then
  echo "[setup-hooks] ✗ 当前目录不在 git 仓库内" >&2
  exit 1
fi
cd "$ROOT"

if [ ! -d .githooks ]; then
  echo "[setup-hooks] ✗ 找不到 .githooks/ 目录(应位于仓库根:$ROOT)" >&2
  exit 1
fi

git config core.hooksPath .githooks

echo "[setup-hooks] ✅ core.hooksPath = $(git config core.hooksPath)"
echo "[setup-hooks]    已激活: $(cd .githooks && ls | tr '\n' ' ')"
