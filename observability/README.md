# observability/ · 观测模板(观测左移)

> 定位:B `05-模块-全链路追踪与观测` + `05-模块-监控告警与仪表盘` 的落地骨架。
> 核心:**唯一 trace_id 贯穿全链路**;结构化日志统一字段;评估分数是一等遥测(幻觉即生产事故);观测左移——**第一个 Agent 运行即植入**,不要等步骤 7。

## 目录约定

```
observability/
  README.md            本文件
  trace_id-规范.md       trace_id 生成/透传/span 命名规范
  日志-schema.md         结构化日志字段规范(JSON)
  otel-init.py          OpenTelemetry 最小初始化片段(样例,按后端改)
  监控面板-清单.md         Grafana/告警面板配置清单(L1/L2/L3)
```

## 关键设计点(引 B)
- **埋点节点**:任务、路由、模型调用、工具调用、记忆检索、人工接管;span kind 参考 OpenInference(CHAIN/LLM/RETRIEVER/TOOL/AGENT/EMBEDDING)。
- **脱敏**:日志与 Trace 中敏感字段必须脱敏(合规);入出参只留摘要/脱敏后值。
- **采样**:全量短期 + 按需长存;异常/慢链路必采;**激进保留长尾错误**(一次小众查询幻觉正是信号)。
- **避免锁仓**:优先 OTel/OpenInference 语义约定 + OTLP 后端(Phoenix/Langfuse/Jaeger 可换),勿用私有 span 格式。
- **决策可解释**:Trace 保留路由决策、置信度、引用来源(可解释性)。

## 落地步骤
1. 阶段3-步骤6:首个 Agent 即跑 `otel-init.py` + 埋点;本地 Jaeger/Phoenix 看 Trace。
   - ✅ **R3 已落地(2026-09-10)**:实现在 `app/eval_gate/obs.py`(E9),已接进 E5 调度层
     (`run.evaluate` 根 span → `sut.call`/`rule.check`/`judge.grade`)与 E1/E7
     (`evalset.load`/`report.write`)。**Trace 视图** = `eval-gate trace [--run <run_id>]`;
     span 落 `eval/runs/<run_id>.trace.jsonl`(OTLP-JSON 兼容,`EVAL_OTLP_ENDPOINT` 可外发)。
   - **CLI 适配(与规范的一处差异,显式记录)**:规范的「本地 stdout → 采集器」面向常驻服务;
     本产品是 CLI,stdout 是人读结果,故**结构化日志走 stderr**(`2>log.jsonl` 采集)。
   - **脱敏**:日志只记 `{len, sha8}` 摘要,**永不记原文**(`需求基线.md:149`);全文留 E7 报告。
     已由契约测试守:`tests/test_observability.py::test_logs_never_contain_answer_text`。
2. 阶段4-步骤9:端到端 trace_id 一致性测试、采样/脱敏测试。
   - ✅ **一致性测试已建**(`tests/test_observability.py::test_all_spans_share_one_trace_id`);
     采样策略留阶段4。
3. 阶段6-步骤11:按 `监控面板-清单.md` 上 L1/L2/L3 面板与告警;版本可比支撑灰度。

## 指标(对观测自身)
- 埋点开销占比 <5%;链路完整率(span 缺失率);Trace 可回溯率;告警准确率/误报率。
