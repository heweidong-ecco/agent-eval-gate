# 契约 · 评测集与阈值(E1:评测集管理)

- 版本:v0.1(阶段2-步骤5 定稿基线;P3 起实现校验器) · 归属:`总纲.md` §3 **E1** · 事实源草案:`eval/README.md`「评测集 schema 草案」
- 状态:已登记,待契约测试(P3)
- 语义:evals.json 是**版本化评测集文件**(git 同库),坏配置必须**零模型调用即失败**(控成本,`总纲.md` §1 数据流步骤1)。

## 术语
- case = 一条评测用例;run = 一次 `eval-gate run`;threshold = 发布门阈值(键见 report 契约)。

## 数据模型(evals.json 顶层)
```jsonc
{
  "version": 1,                          // 必填 int,评测集结构版本
  "threshold_ref": "eval/阈值.md",       // 必填 str,阈值文件路径(相对仓根)
  "sut_default": "mini-rag-qa",          // 可选 str,缺省被测适配器 id(须已注册,见 E2)
  "sample": { "max_cases": 100, "seed": 42 },   // 可选;超大规模抽样/截断 + 可复现种子
  "judge": { "model": null, "max_tokens": 512, "concurrency": 4 }, // 可选;覆盖默认(DEC-002)
  "evals": [ /* case,见下 */ ]
}
```

## case 字段(必填/枚举/约束)
| 字段 | 类型 | 必填 | 枚举/约束 | 说明 |
|---|---|---|---|---|
| id | int | ✅ | 仓内唯一 | |
| sut | str | 由顶层 sut_default 兜底 | `mini-rag-qa` · `fastapi-rag` | E2 注册的被测适配器 id |
| module | str | ✅ | `rag`·`task`·`memory`·`tool-mcp`·`eval` | 被测行为类别(回归归因;**非**本产品模块) |
| tags | str[] | ☐ | 场景 | happy-path/boundary/adversarial/refusal/regression… |
| input | obj | ✅ | `{question:str 必填, context?:{}, history?:[]}` | 供适配器组请求(E2) |
| expected | obj | ☐(deterministic_only 时部分必填) | `{answer_contains?:[], answer_not_contains?:[], must_refuse?:bool, ideal_tool_seq?:[]}` | 语义期望;**判据分层(DEC-004,签核 D-15)**:`answer_contains` 为"含其一即符"的**语义期望**,由**判分器**裁决 —— 确定性层未命中**不单独构成 fail**;`answer_not_contains` / `must_refuse` 为**硬判据**,由确定性层裁决,**判分器不可翻案** |
| checks | obj | ☐ | `{deterministic_only?:bool}` | `true` = 红队/注入,只走 E3 不进 LLM-judge |
| source | str | ☐ | 外部数据来源标注 | 如 `01.FastAPI RAG Agent archive eval_dataset.json id:12` |

### 校验规则(不变量)
1. `deterministic_only:true` 的 case **必须**能由确定性规则判定:即 `expected.must_refuse` 显式(true/false)或 `answer_not_contains` 非空;否则拒绝(无法表达"禁止出现")。
2. `expected` 为空且非 deterministic_only → 拒绝(judge 无参照则允许但须 `judge.model` 指定且人工基线存在——MVP 前一律要求非空)。
3. **匹配口径随层走(DEC-004 §2.2,签核 D-15)**:`answer_not_contains` 比较前**归一化**
   —— 去所有空白(含全角 `U+3000`)+ 统一小写,方向**偏严**(硬层无兜底,误报比漏报安全);
   可抓住「无 法 回 答」这类插空格 / 改大小写的**规避**。
   `answer_contains` **保持字面匹配**,不得归一化(它已交判分器,归一化不影响 verdict,只会污染观测)。
4. **硬判据的判定权**:`must_refuse` / `answer_not_contains` / 空回答的失败**不可被 judge 翻案**;
   合入规则见 `评测-report.md` 的「判定归属」段。
3. 顶层 `sample.max_cases` 默认全量;抽样必须带 `seed`(可复现)。

## 接口
- `load_and_validate(path) -> {top, cases}` :校验失败抛结构化错误(见下),**不发起任何被测/judge 调用**。
- `resolve_case_sut(case, top)` :回填 `sut_default`。
- 阈值装载与判定见 report 契约(E6)。

## 错误码
| 码 | 含义 | 触发示例 |
|---|---|---|
| `E_SCHEMA_INVALID` | JSON/字段类型不符 | expected 为数组而非对象 |
| `E_UNKNOWN_SUT` | sut 未在 E2 注册 | sut="xyz" |
| `E_CASE_ID_DUP` | id 重复 | 两条 id:3 |
| `E_NO_CASES` | evals 为空 | |
| `E_THRESHOLD_REF_MISSING` | threshold_ref 指不到文件 | |
| `E_DETERMINISTIC_RULE_MISSING` | deterministic_only 但无可判规则 | |
| `E_EXPECTED_EMPTY` | 非 deterministic_only 却 expected 空 | |

## 变更记录
- 2026-09-09 v0.1 定稿(对齐 `eval/README` 草案)。
