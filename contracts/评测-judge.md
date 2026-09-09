# 契约 · LLM-as-Judge(E4)

- 版本:v0.1(阶段2-步骤5 定稿) · 归属:`总纲.md` §3 **E4** · 层 3 · DEC-002(模型可配/防锁仓)
- 状态:已登记
- 语义:judge 是评测内核的判分器——**模型可换,分数跨模型不可比**,报告必带 judge 模型/版本字段(`总纲.md` §1 不变量②)。

## judge 调用接口(统一适配器)
```python
class Judge:
    def __init__(cfg): ...          # cfg: model/base_url/api_key/max_tokens/concurrency(读 config/env)
    async def grade(self, item) -> JudgeVerdict: ...
    async def grade_ref(self, golden) -> float:  # 人工参照一致率,供 E7 校准
```
- 调用前由 E5 保证:**确定性(E3)结果先到**;注入命中的 case 不进本接口。

## 判分入参(item)
```jsonc
{
  "case_id": 1,
  "rubric": "系统判分标准(忠实度/拒答/引用…按被测 module 选)…",
  "question": "…",
  "expected": {"answer_contains":[],"must_refuse":false, "…":"…"},
  "sut_answer": "…",
  "sut_sources": [],
  "deterministic": {"passed": true, "hits": []}   // E3 结果(供参照,非替换)
}
```
- 上下文纪律(成本/截断):入参有 `max_tokens`/长度上限,超长被测回答按 E5 截断策略进 judge(`需求基线.md` §8-W1 上下文溢出风险)。

## 判分出参(JudgeVerdict · 结构化,必须可解析)
```jsonc
{
  "verdict": "pass | fail | flag",     // flag = 存疑需人工(E7 触发 human review)
  "score": 0.0,                        // 0..1
  "labels": ["faithful", "no-hallucination"],
  "reasons": ["…(逐条判分依据)…"],      // 可解释性:每条理由给证据引用
  "evidence_refs": ["sources[0]"]
}
```
- 解析容错:模型输出非合法 JSON → 重问一次仍失败 → 抛 `E_JUDGE_PARSE` 并标该 case flag(不静默给分)。
- 超时:重试 1 次 → 仍超时抛 `E_JUDGE_TIMEOUT`(E5 处置)。

## 记录字段(报告侧必存)
- judge 模型 id/版本、temperature、max_tokens、并发上限、调用时间 —— 使跨模型分数**不可比**可被审计识别(DEC-002)。

## 人工参照校准(golden)
- 仓内 ≥2 条人工标注 golden(`总纲.md` §3.2 baseline);每次 run 先 `grade_ref`:judge 判定 ↔ golden 人工标签 → 一致率 = judge-人工一致率。低于阈值 → 报告 ⚠,建议人工复核阈值/边界(增强模式,人不全自动放行)。

## 错误码
| 码 | 含义 |
|---|---|
| `E_JUDGE_PARSE` | 输出非结构化/不可解析 |
| `E_JUDGE_TIMEOUT` | judge 超时 |
| `E_JUDGE_AUTH` | 凭证无效 |
| `E_JUDGE_MODEL_UNKNOWN` | 端点不认该模型名(如填错 model) |

## 变更记录
- 2026-09-09 v0.1。
