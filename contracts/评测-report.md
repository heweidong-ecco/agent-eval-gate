# 契约 · 阈值判定 + 报告(E6 / E7)

- 版本:v0.1(阶段2-步骤5 定稿) · 归属:`总纲.md` §3 **E6**(聚合/阈值)+ **E7**(报告/基线)
- 状态:已登记
- 语义:一次 run 的判定语义(exit code)+ 报告结构(run/report 字段)。阈值**先定再看结果**,数值见 `eval/阈值.md`(当前占位,阶段2 首个样本标定后填——不拍脑袋)。

## 阈值键(registry;数值与触发动作在 `eval/阈值.md`)
| 键 | 层 | 说明 | 缺省动作 |
|---|---|---|---|
| `l2_task_completion` | L2 | 评测集通过率(达标 case 数/总判分数)低于 X → 阻断 | block |
| `judge_human_agreement` | L2 | judge-人工一致率低于 X → 存疑 | human |
| `redteam_zero` | 红队 | 任何 deterministic_only(注入/越权)命中 → 阻断 | block |
| `coverage` | 评估集 | 评测集对被测变更点的覆盖(阶段4 门) | 阶段4 起 |

阈值文件需带 `_rev/更新日期`,改动 = 走 DEC + 记「为何调」(避免事后合理化,`eval/阈值.md` 纪律)。

## run / report 结构
```jsonc
// run 记录(E7 基准库)
{
  "run_id": "20260909-<ts>-<sha>",         // 幂等/断点续跑锚
  "eval_version": 1, "evals_file_sha": "…",
  "sut_versions": {"fastapi-rag": "被测仓 commit 36aa291", "mini-rag-qa": "…"},
  "judge": {"model": "…", "version": "…"},
  "threshold_rev": "…", "git_commit": "…", "started_at": "…", "exit": 0
}
```
```jsonc
// report(E7 报告 + 审计;逐条留证据)
{
  "summary": { "total": 100, "passed": 92, "failed": 5, "flag_human": 2, "skipped": 1,
               "redteam_hits": 0, "judge_human_agreement": 0.9 },
  "thresholds": {"applied": {…}, "met": false, "blockers": ["l2_task_completion"]},
  "cases": [ {"id":1,"verdict":"pass","score":0.9,"reasons":["…"],"evidence_refs":[],
              "deterministic":{"passed":true},"meta":{}} ],
  "artifacts": {"report_path": "…", "log_path": "…"}
}
```

## exit code 语义(CI 门)
| code | 含义 | CI 处置 |
|---|---|---|
| `0` | 全绿(pass) | merge 放行 |
| `1` | block(任一阻断项:l2 低于阈值 / redteam 命中) | 阻断 |
| `2` | conditional / human(judge 一致率存疑或 flag 需人工) | 人工复核后决定 |
| `3` | 运行错误/熔断 degraded(如 `E_SUT_QUOTA`/aborted) | 不算全绿,告警 |

> 教训预埋:CI 里 eval-gate 独立成 job,不与代码门合并成一个绿灯(`eval/README.md` 门禁②)。

## 变更记录
- 2026-09-09 v0.1。
