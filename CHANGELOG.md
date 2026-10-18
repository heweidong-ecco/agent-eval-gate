# Changelog

本文件记录**面向使用者**的变化。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

> ⚠️ **`v0.4.0` 是自用版**;`v1.0.0` 的前置是「真实发版 CI 接入 + 外部使用者验证」,
> 目前都还没满足(见 `docs/结项报告-自用版-2026-10-18.md`)。

## [0.4.0] - 2026-10-18

### Added

- **`DEC-019` 完整 live 回归**:48 条真实评测,47/48 通过(0.9792)、`exit 0`;
  `rule_hit_judge_fail = 0` ⇒ 判分器收紧后**未观测到误伤**
  (报告:`docs/reports/DEC-019-live回归-2026-10-18.md`)。
- **评测语料可复现**:`eval/corpus/manifest.json`(sha256/125 行/来源计数)+
  `tools/export_eval_corpus.py` + `tools/seed_eval_corpus.py`;正文放仓外,seed 前强制校验哈希。
- **当前架构图**:`docs/arch/README.md`(C4 上下文 / 组件 / 时序)。
- **发版 CI 接入模板**:`integrations/fastapi-rag-agent/`(⬜ 未接入;不改另一个仓)。
- **文档面**:`docs/FAQ.md`、`docs/CLI.md`、`docs/README.md`(索引)、`examples/`;
  `.github/ISSUE_TEMPLATE/`、`.github/PULL_REQUEST_TEMPLATE.md`。
- **仓库健康文件**:`LICENSE`(MIT)、`CONTRIBUTING.md`、`SECURITY.md`、`SUPPORT.md`、本文件。

### Changed

- **判分器提示词收窄**(`DEC-019` α):豁免句只在**拒答语境**下生效,并给非拒答反例。
- **门 2(提交门)判据改为时序**(`DEC-020`):「自上次提交以来、动手之前调过 TDD」,
  不再是一次满足后永久满足。
- **L2 阈值 0.80 → 0.95**(`DEC-013`)。
- **`tools/sut-harness/run_sut.sh` 适配新被测**:
  `api/` → `app/`、官方镜像 `fastapi-rag-agent:latest`;
  源码只读挂 `/src` → 容器内复制到可写 `/app`;新增 `EVAL_SUT_DB` / `EVAL_SUT_SESSION_TOKEN_LIMIT`。
- **能力探针失败退出码 1 → 2**(与 README / 故障手册的契约一致)。
- 版本号 `0.3.0` → **`0.4.0`**。

### Fixed

- 被测结构变化后 **旧 harness 直接跑不起来**(仍要求 `api/` + 旧镜像)。
- 只读挂载 `/app` 导致被测启动失败(应用要写 `/app/.mem0/qdrant/.lock`)。
- 判分器输入 `deterministic` 字段去掉(`DEC-015 B1`)。
- 重试在产物里不可见 → `sut.call` span 记 `attempts/http_status/last_error`。
- `_run_id` 同秒撞名导致产物互相覆盖。

### Known limitations / deferred

- **U2 未闭环**:评测门**没有**接进任何真实项目的发版 CI(模板已备)。
- **M3 抽取类判据**仍是「含其一即符」;正式判抽取需单独 DEC。
- **`id=20`** 是被测检索失败(`eval/cases/fastapi-rag-2026-10-18.json`,status=open)。
- 轮间 2× 延迟悬案(16 轮内 1 次,成因未指名)。

## [0.3.0] - 2026-09-11

### Added

- 阶段3 收口:评测门 CLI、契约、真实被测适配器、CI 示例。
- 门店禁硬化:门 1/门 2、`impl-guard` 左移门、子 Agent 纪律注入。

### Fixed

- skills 不触发、子 Agent 拿不到纪律(两个严重问题);
- `rag-api` 旧镜像导致的“能通过 `/health` 但答不了”被能力探针拦住。

## [0.2.0] - 2026-09-09(未打 tag)

- 七层架构适配(`总纲.md`)、E1–E9 模块注册表、评测执行状态机、评测集 schema 草案。

## [0.1.0] - 2026-09-09(未打 tag)

- 初始脚手架:需求基线、ROADMAP、目录骨架。
