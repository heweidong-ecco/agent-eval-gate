# 贡献指南

> **项目状态**:`v0.4.0`(自用版,2026-10-18 结项)。欢迎 issue / PR,但单人维护、无 SLA;
> 外部贡献前请先开 issue 对齐,避免做完才发现方向不一致。

## 1. 开发环境

```bash
git clone https://github.com/heweidong-ecco/agent-eval-gate.git
cd agent-eval-gate
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
./tools/setup-hooks.sh          # 必做:激活本地门禁(克隆不携带 git hooksPath)
```

要求:Python **≥ 3.10**(CI 用 3.11);运行时**零依赖**,dev 依赖只有 pytest / coverage / pyyaml。

## 2. 测试与门禁

```bash
.venv/bin/python -m pytest -q                  # 全量,离线
.venv/bin/python -m pytest -q --cov=eval_gate  # 覆盖率(CI 硬门 85%)
```

本仓的提交门禁(`.githooks/`)会检查:

| 门 | 规则 | 豁免 |
|---|---|---|
| 门 1 | 改了 `app/`、`tools/`、`.claude/hooks/`、`.githooks/` 却没改 `tests/` → 拒绝 | 提交信息写 `[no-test: <理由>]` |
| 门 2 | 自上次提交以来、动手之前**没有调用 `test-driven-development`** → 拒绝 | 提交信息写 `[no-skill: <理由>]` |

> **两条都是结构门,不是建议**。理由见 `CLAUDE.md` 的「纪律」段与 `DEC-020`。
> **先写测试、看它红、再写实现** —— 这是本仓的默认工作方式。

## 3. 改动的前置规则

| 你要改什么 | 先做什么 |
|---|---|
| Prompt / 判据 / 评估集 / 阈值 | 跑 eval 回归;失败即补 `eval/cases/`(带 `regression.root_cause`) |
| 选型 / 口径 / 架构决策 | 写 `docs/decisions/DEC-nnn-*.md`(备选方案 / 依据 / 反悔成本) |
| 接入新被测 | 读 `docs/接入新被测.md`;适配器 3 处改动 + 数据 |
| 改评测语料 | 读 `eval/corpus/README.md`;正文不入本仓,更新 `manifest.json` 的 sha256 |
| 改 CLI / 契约 | 同步 `contracts/` 与 `docs/CLI.md`,并补契约测试 |
| 改门禁 / hook | **必须配测试**,并做突变验证(拿掉守卫应变红) |

## 4. Commit 与 PR

- **Conventional Commits**:`feat|fix|docs|refactor|test|chore|perf|ci(scope): 描述`;
- 一个 PR = **一个完整任务**(不是一个小节);同一任务的多条 commit 走同一个 PR;
- 分支:`feat/<短名>` / `fix/<短名>` / `docs/<短名>`;
- PR 描述用 `.github/PULL_REQUEST_TEMPLATE.md`,必须写清:
  - 改了什么 / 为什么;
  - 验证命令与结果(测试、覆盖率、eval);
  - 是否改 Prompt / 评测集 / 契约;
  - 风险与回滚。
- **合并**:单人仓里"点合并"是唯一人工审核位;PR 开好后由维护者确认再合
  (见 `CLAUDE.md` D-23:自开 PR 不自合)。

## 5. 目录与文档

- 文档导航:**`docs/README.md`**
- 当前架构:**`docs/arch/README.md`**
- 项目状态与暂缓项:**`docs/结项报告-自用版-2026-10-18.md`**
- 新增文档时:**必须同时更新 `docs/README.md` 索引**;架构变化同时更新 `总纲.md §1.1`。

## 6. 发布

- 版本号在 `pyproject.toml` 与 `app/eval_gate/__init__.py` **两处同步**;
- 发布前:全量测试 + 覆盖率 + (若改评测件)eval 回归;
- 更新 `CHANGELOG.md` → 打 tag `vX.Y.Z` → 推送;
- `v1.0.0` 的前置 = U2 真实发版 CI 接入 + 外部使用者验证(当前未满足)。

## 7. 行为准则

本项目**暂未采用正式的行为准则**(单人维护、无社区治理流程)。
基本要求:就事论事、不人身攻击;维护者有权关闭不合适的 issue/PR。
若将来开放外部维护者,**先补 `CODE_OF_CONDUCT.md`**。

## 8. 许可

贡献即表示同意以 **MIT** 许可(见 `LICENSE`)发布。暂不要求 DCO / CLA。
