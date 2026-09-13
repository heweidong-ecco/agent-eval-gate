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
// run 记录(E7 基准库)—— 字段在 2026-09-13(DEC-016)补齐;此前声明 11 个、落地只有 4 个
{
  "run_id": "20260909-<ts>-<sha>",         // 幂等/断点续跑锚
  "eval_version": 1, "evals_file_sha": "…",   // 评测集版本 + 内容 sha(同版本改内容也追得住)
  "threshold_rev": "…", "git_commit": "…",    // 生效阈值 rev · **门自身**的 commit(非被测)
  "started_at": "2026-09-13T17:14:56+0800",   // **运行开始**时刻(不是落盘时刻)
  "sut": {                                     // ← 被测侧自证(DEC-016)
    "endpoints": {"fastapi-rag": {"adapter": "FastApiRagAdapter",
                                  "base_url": "http://127.0.0.1:8000",
                                  "mode": "accurate_norerank", "top_k": 3}},
    "versions":  {"fastapi-rag": "f2dad78"},   // 契约原写顶层 `sut_versions` = **per-sut 映射**
    "probe": "ok"                              // 能力探针结果 ok/fail;缺省 null
  },
  "judge": "offline|deepseek-v4-flash@…",      // 见下方「与旧声明的三处差异」
  "judge_config": {"model": "…", "max_tokens": 4096, "retries": 1, "timeout_s": 60.0},
  "degraded": false, "degraded_reason": null,   // 熔断/整批 aborted;true ⇒ exit 3 且阈值判定作废
  "exit_code": 0
}
```

### 与旧声明(2026-09-09 版)的三处差异 —— **如实声明,不是静默对齐**

| 旧声明 | 现形态 | 为什么 |
|---|---|---|
| 顶层 `sut_versions: {sut: 版本}` | **`sut.versions`**(收进 `sut` 块) | 该字段**从未实现** ⇒ 无兼容负担;而"被测是谁、在哪、什么模式、什么版本"是**同一个问题**,收进一块更好读 |
| `judge: {model, version}` | `judge`(标签)+ **`judge_config`**(model/max_tokens/retries/timeout) | `judge_config` 是 `DEC-006 A4` 加的**更完整**的自证(含**预算**);两者合起来覆盖原意图 |
| `exit: 0` | **`exit_code`** | 实现/报告/复盘/CI 文档**一律用 `exit_code`** ⇒ 把契约对齐到既有事实,而不是反向改代码 |

> ⚠️ **本条的历史**:契约 2026-09-09 声明 11 个字段,**落地只有 4 个**;
> 该缺口 `docs/部署.md:96` 于 **2026-09-11 已登记**却一直未修 ——
> 而同期 P4-1 的《集成测试报告》写着「契约**零漂移**」(那条结论**只覆盖了被抽查的字段**)。
> ⇒ 2026-09-13(DEC-016)一次性补齐,并把「契约↔产物」做成**可机检**的测试
> (`tests/test_sut_identity.py::test_run_record_carries_all_contract_declared_fields`)。
```jsonc
// report(E7 报告 + 审计;逐条留证据)
{
  "summary": { "total": 100, "passed": 92, "failed": 5, "flag_human": 2, "skipped": 1,
               "redteam_hits": 0, "judge_human_agreement": 0.9,
               "soft_miss_judge_pass": 0, "rule_hit_judge_fail": 0 },
  "thresholds": {"applied": {…}, "met": false, "blockers": ["l2_task_completion"]},
  "cases": [ {"id":1,"verdict":"pass","score":0.9,"reasons":["…"],"evidence_refs":[],
              "deterministic":{"passed":true,"hard_passed":true,"soft_missed":false},
              "judge_verdict":"pass","meta":{}} ],
  "artifacts": {"report_path": "…", "log_path": "…"}
}
```

## 判定归属(逐条;DEC-004,签核 D-15)

每条 case 的 `deterministic` 子对象按**判据分层**记录:

| 字段 | 含义 |
|---|---|
| `hard_passed` | **硬层**(`must_refuse` / `answer_not_contains` / 空回答)是否全过 —— 判分器**不可翻案** |
| `soft_missed` | **软层**(`answer_contains`)是否有未命中 —— 由判分器定夺 |
| `passed` | 字面全过 = `hard_passed ∧ ¬soft_missed`(**既有语义,未改**) |
| `hits` | 报告文案(硬层失败原因 + 软层未命中提示) |

**合并规则**:`verdict = pass ⟺ hard_passed ∧ judge 判 pass`。
`judge` 不可用时(直接调用 `_grade_case` 且 `judge=None` 的离线精简路径),确定性层为
**唯一**判据(**含软层**)。

**两个观测计数**(进 `summary`,**只观测、不参与阈值**):

| 字段 | 含义 |
|---|---|
| `soft_miss_judge_pass` | 软层未命中、判分器救回 —— 量化"确定性层错了几次" |
| `rule_hit_judge_fail` | 软层命中、判分器判 fail —— 关键词堆砌或判分器误判(>0 时打 warn 日志) |

## exit code 语义(CI 门)
| code | 含义 | CI 处置 |
|---|---|---|
| `0` | 全绿(pass) | merge 放行 |
| `1` | block(任一阻断项:l2 低于阈值 / redteam 命中) | 阻断 |
| `2` | conditional / human(judge 一致率存疑或 flag 需人工) | 人工复核后决定 |
| `3` | 运行错误/熔断 degraded(如 `E_SUT_QUOTA`/aborted) | 不算全绿,告警 |

**exit 3 触发谓词(2026-09-10 补,R0)**:
1. 被测返回 `E_SUT_QUOTA`(契约 `评测-sut-adapter.md:34`)→ **整批 aborted**:触发条记 `fail`,其余未执行的 case 记 `verdict:"skipped"` 且**不再发请求**;`degraded=true`、`degraded_reason="E_SUT_QUOTA: …"`。
2. `degraded=true` 时**阈值判定作废**:`blockers` 置空(不得据此报 `l2_task_completion` 未达标——本轮根本没跑完),仅以 exit 3 告警。
3. 其余运行错误不动 exit:judge 单条调用失败 → 该 case 记 `fail` + `E_JUDGE_*` 理由,**run 继续**;被测其它错误(`E_SUT_TIMEOUT`/`5XX`/`4XX`/`AUTH`/`BAD_RESPONSE`)→ 该 case 记 `fail`,**run 继续**。

> 承载字段:`degraded`(bool)+ `degraded_reason`(str|null),写在 run 记录里(见下)。
> 教训预埋:CI 里 eval-gate 独立成 job,不与代码门合并成一个绿灯(`eval/README.md` 门禁②)。

## 变更记录
- 2026-09-09 v0.1。
- 2026-09-10 补 `exit 3 触发谓词` 与 `degraded`/`degraded_reason` 承载字段(R0 最小韧性加固;签核 D-10c)。
