# eval/ · 评估集骨架(质量门禁)

> 定位:B `05-模块-评估与测试` 的落地骨架——把 Agent「好不好」变成可量化数字,作为发布门禁(eval-gate)。
> 纪律:B「**先定阈值再看结果**」「**版本化一切**」(Prompt/模型 revision/数据集/评测器/harness 同库可回滚)、「失败即补 case」。

## 目录约定

```
eval/
  README.md          本文件
  阈值.md            建议阈值占位(先定阈值,再看结果)
  evals.json         评估用例样例(仿 B agent-system-creator/evals/evals.json;可多文件拆分)
  cases/             评估用例库(标注三类:意图 / 理想工具调用序列 / 标准答案)——逐步按模块建
  runs/              回归运行记录(版本 + 结果 + 阈值对比;支撑统计回归与发布门禁)
```

## 三种评估集 & 标注
- 真实案例(线上回流)+ 边界/对抗/拒答 + 历史事故;每例标注:**意图、理想工具序列、标准答案**。
- 既看最终结果,也看「是否走对了步骤」(理想序列标注,中间过程质量)。

## 门禁(eval-gate)
1. **变更触发**:改 Prompt / 工具 Schema / 记忆策略 / 评估集 / 模型版本 → 必跑评估回归。
2. **判定**:低于 `阈值.md` → 阻断发布(Pass / Conditional / Human Review / Block);CI 里独立成 job,别与代码门合并成一个绿灯。
3. **统计回归**:同版本 A/B 各跑 N 次(参考 50),用 p-value + 效应量判变化,别只看单次好坏。
4. **发布**:release/tag 必附《评估报告 + L1/L2/L3 对比》;线上新失败 → 立即补进 `cases/` 复现。

## 版本纪律
- `evals.json` / `cases/` 随代码同库提交、可 diff、可回滚;`runs/` 记录每次回归的 commit 与结果。
- 工具:DeepEval / Promptfoo / agent-eval / Ragas(评估引擎按需选,参考 B `07-参考-技术选型对比` §五;组织自己定义质量模型)。

## 评测集 schema 草案(阶段2-步骤4 启动 · 总纲 §3.3 落点)
> 骨架先定,字段 P2-5/P3 细化。**消歧**:本文件 `module` 标签 = **被测 Agent 的行为类别**(task/rag/memory/tool-mcp/eval),供回归归因;不是评测门自身模块(评测门模块见 `总纲.md` §3 E1–E9)。

单条(evals.json / cases/*.json):
```jsonc
{
  "id": 1,
  "sut": "mini-rag-qa | fastapi-rag",          // E2 被测适配器 id
  "module": "rag",                              // 被测行为类别(module 标签)
  "tags": ["happy-path", "boundary", "adversarial", "refusal", "regression"],
  "input": { "question": "…", "context": {} },  // 供适配器组请求
  "expected": {
    "answer_contains": ["…"],                   // 含关键点(任意符合即可)
    "answer_not_contains": ["…"],               // 禁现(幻觉/越权话术)
    "must_refuse": false,                        // 拒答负例标记(知识外)
    "ideal_tool_seq": []                         // v1.1 回放用(理想工具序列)
  },
  "checks": { "deterministic_only": true },      // true=红队/注入,只走确定性引擎(E3),不进 LLM-judge
  "source": "01.FastAPI RAG Agent archive eval_dataset.json id:12"  // 外部数据来源标注
}
```
运行级顶层:`_threshold` → `eval/阈值.md`;`_sample` → 上限/随机种子(可复现);`_judge` → `{model, max_tokens, concurrency}`(DEC-002)。

首用规划:
- **mini RAG-QA 自证**:自造 ~10 条(≥2 拒答负例 + ≥1 注入红队),先验工具与管线顺序。
- **真实被测**:✅ **已完成转档(R2a,2026-09-10)= `fastapi_rag_golden.evals.json`**(40 条 = 37 golden + 3 条自造对抗/越权)。来源 `01.FastAPI RAG Agent/archive/artifacts/eval_dataset.json`,`source` 的 `id` 为**数组下标(0 基)**;10 条拒答走 `must_refuse`,3 条对抗/越权走 `deterministic_only`(不进 judge);`answer_contains` 抽取规则见该文件 `_comment`。其 RAGAS 历史基线(faithfulness 0.63/context_recall 0.76)作**参考横向**(来源标注),不作本门断言。
  - 离线预演(`tests/test_golden_rehearsal.py`):忠实被测 40/40 过、劣化被测被拦(红队命中 3 条)。
  - 真实链路冒烟(R1)另需:被测服务在跑 + 契约 `评测-sut-adapter.md:42` 要求的 **golden 文档集 + seed 步骤**(否则检索结果不可复现)。

## 开始使用
1. 阶段2-步骤4 起:每规划一个模块就为它建首批用例(意图/工具序列/答案)。
2. 阶段4-步骤8/9:跑回归,沉淀 L2 基线;发布前跑 `阈值.md` 全部门禁。
3. 上线后:观测回流真实用例,持续补 `cases/`(飞轮入口见 `../飞轮/`)。
