# 日志-schema.md · 结构化日志字段规范(JSON)

> 依据:B `05-模块-全链路追踪与观测` 三、结构化日志字段规范。所有日志输出 JSON,机器可读、可聚合、可重建链路。

## 字段表

| 字段 | 类型 | 说明 | 示例 |
|---|---|---|---|
| `timestamp` | string(ISO8601) | 时间戳 | `2026-09-09T10:00:00.123Z` |
| `module` | string | 模块(任务/路由/记忆/工具/模型/…)| `memory` |
| `action` | string | 动作类型 | `retrieve` |
| `trace_id` | string | 链路标识(见 trace_id-规范) | `4bf92f3577b34da6a3ce929d0e0e4736` |
| `span_id` | string | 当前 span | `00f067aa0ba902b7` |
| `input` | object | 入参(**脱敏后**/摘要) | `{"query":"<摘要>","tenant_id":"t1"}` |
| `output` | object | 出参(**脱敏后**/摘要/结果状态) | `{"hits":3,"top_score":0.82}` |
| `duration_ms` | number | 耗时 | `245` |
| `status` | string | 成功/失败/降级 | `ok` \| `error` \| `degraded` |
| `tags` | object | 租户、模型版本、Prompt 版本、Agent 身份等 | `{"tenant":"t1","model":"claude-…","prompt_ver":"v3"}` |
| `error` | object(可选) | 失败时的错误码/信息(不含堆栈敏感信息) | `{"code":"TOOL_TIMEOUT","msg":"create_issue 5s 超时"}` |

## 规则
1. **脱敏优先**:PII/密钥/长文本正文一律不入日志;入参只留摘要(长度/类型/关键词),必要详情存安全审计库。
2. **一行一事**:每条日志独立 JSON,不跨行拼接;禁止在 JSON 里拼非转义大文本。
3. **可重建**:`trace_id` + `span_id` + `parent_span_id` 齐全,丢失 Trace 时可凭日志重建链路。
4. **分级**:`info`(正常动作)/ `warn`(降级、重试)/ `error`(失败);`error` 必带 `trace_id` 与 `module`。
5. **评估分数是一等遥测**:评估/幻觉检测结果也要记一条日志(与 trace_id 关联),幻觉即生产事故。

## 采集与存储
- 本地 stdout → 采集器(OTel Collector / Fluent Bit)→ 存储(日志库 + OTLP 后端)。
- 采集端故障不阻塞主流程(本地缓冲 + 异步上报)。
