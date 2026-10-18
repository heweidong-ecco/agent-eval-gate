# docs/arch · 当前架构图(C4 视角,2026-10-18)

> **用途**:把「系统现在长什么样」画清楚,避免后来人从历史文档里拼出一个过期架构。
> 事实源:`总纲.md §1`(七层)与 `§3`(E1–E9 模块);本文只画**当前形态**,不重复模块细节。
>
> **图例**:实线 = 已落地并验证;虚线 = **未接线 / 未接入**(不是已实现)。

## 1. C4-L1:系统上下文

```mermaid
flowchart LR
  DEV["开发者 / CI"] --> GATE["agent-eval-gate<br/>CLI 评测门"]
  GATE -->|"HTTP / 快照"| SUT["被测 Agent 系统<br/>fastapi-rag / toolkit"]
  GATE -->|"评分请求"| JUDGE["LLM-as-Judge<br/>OpenAI 兼容端点"]
  CORPUS["评测语料<br/>仓内 manifest + 仓外正文"] -->|"seed(校验 sha256)"| SUT
  GATE --> RPT["报告 + exit code"]
  RPT --> EVID["证据归档<br/>spans.jsonl"]
  RELEASE["真实被测的发版 CI<br/>⬜ 未接入(模板)"] -.-> GATE
```

**当前边界(2026-10-18 结项)**:

- 被测系统由**它自己的**进程/容器运行;本门只通过适配器取输出,**不托管 Agent 运行时**;
- 真实发版 CI **未接入** —— 模板在 `integrations/fastapi-rag-agent/`;
- 评测语料正文**不在公开仓**,只留清单与哈希。

## 2. C4-L2:容器 / 组件

```mermaid
flowchart TB
  subgraph GATE["agent-eval-gate(CLI)"]
    E1["E1 评测集管理<br/>schema / 阈值装载"]
    E2["E2 被测适配器<br/>HTTP / 快照"]
    E3["E3 确定性规则<br/>注入/越权/拒答/禁现"]
    E4["E4 LLM-judge<br/>分数 + 理由"]
    E5["E5 调度/批次<br/>并发 · 熔断 · 重试"]
    E6["E6 聚合与阈值<br/>L2 + exit code"]
    E7["E7 报告与基线<br/>逐条证据/理由"]
    E8["E8 审计与安全<br/>脱敏 · 留痕"]
    E9["E9 观测与成本<br/>trace_id · token"]
  end

  E1 --> E5
  E2 --> E5
  E5 --> E3
  E5 --> E4
  E3 --> E6
  E4 --> E6
  E6 --> E7
  E7 --> E9
  E8 -.-> E7

  H["SUT harness<br/>官方镜像 + 能力探针 + 自证"] --> E2
  C["语料清单 + seed 工具"] --> H
  REPO["eval/runs + eval/cases"] --- E7
  ARCH["证据归档 + 覆盖守卫"] --- E7
```

| 关注点 | 落点 |
|---|---|
| 判据分层(硬层 / 软层 / 第三态) | `DEC-004` · `DEC-022` · `app/eval_gate/rules.py` |
| 调度顺序锁(确定性 → judge) | `runner.py` · 契约测试 |
| 真实被测运行 | `tools/sut-harness/run_sut.sh` |
| 语料复现 | `eval/corpus/manifest.json` + `tools/seed_eval_corpus.py` |
| 证据可重算 | `tools/archive_evidence.py` + `tools/check_evidence_coverage.py` |
| 发版 CI 接入(未做) | `integrations/fastapi-rag-agent/` |

## 3. 一次 live run 的时序

```mermaid
sequenceDiagram
  autonumber
  participant Dev as 开发者 / CI
  participant CLI as eval-gate
  participant Harness as SUT harness
  participant SUT as 被测
  participant Judge as LLM-judge
  participant Disk as 报告 / 证据

  Dev->>CLI: run --evals eval/fastapi_rag_golden.evals.json
  CLI->>CLI: E1 装载 + schema 校验(坏配置零模型调用即失败)
  opt 真实链路(预先执行)
    Dev->>Harness: run_sut.sh(起依赖 + 官方镜像)
    Harness->>SUT: 能力探针(/health 200 ≠ 答得了)
    Dev->>SUT: seed 评测语料(sha256 校验)
  end
  loop 每条 case(E5 分批/并发)
    CLI->>SUT: 适配器请求
    SUT-->>CLI: 输出文本 + sources
    CLI->>CLI: E3 确定性规则(硬层可阻断)
    opt 软层需要
      CLI->>Judge: 问题 + 期望 + 回答
      Judge-->>CLI: 分数 + 理由
    end
  end
  CLI->>CLI: E6 聚合 + 阈值判定
  CLI->>Disk: L2 报告 + trace + 摘要
  CLI-->>Dev: exit 0 / 1 / 2 / 3(见契约)
```

## 4. 与历史图的关系

- `总纲.md §1` 的七层图是**职责适配**层面的蓝图,长期稳定;
- 本文是**当前部署/组件形态**,会随工具链变化(例如将来接入发版 CI);
- **改架构必须同时改两处**:本文 + `总纲.md §1.1`,否则两份图会漂移。

## 变更记录

- 2026-10-18 建立(自用版结项):补上此前只在 `总纲.md` 里被引用、但**目录不存在**的 `docs/arch`;
  当前形态 = 评测内核 + SUT harness + 语料复现 + 证据归档;发版 CI 标为未接入。
