# trace_id 规范(全链路追踪 · 挂 B 05-模块-全链路追踪与观测)

> 原则:**每请求唯一 trace_id,入口生成,下发到所有模块与子 Agent;任何一条日志/告警都能凭它回溯整条决策链。**

## 1. 生成
- 入口(API 网关 / 消息队列消费者 / 定时任务)生成 `trace_id`(符合 W3C `traceparent`:32 位十六进制;或 16 字节随机)。
- 前端/Console 请求如已有上游 `trace_id` → 透传优先,无则网关生成。

## 2. 透传
- 同步调用:HTTP 头 `traceparent` / gRPC metadata / 函数入参携带。
- 异步/消息:消息头携带 `trace_id`;子 Agent 派生子任务保留父 trace_id,新增 span_id。
- **租户 ID 与 trace_id 全程同传**(B 多租户隔离:记忆/向量/日志全链路透传)。

## 3. span 命名(动作命名,便于聚合)
```
{module}.{action}  例:task.plan / router.route / memory.retrieve / tool.call(create_issue) / llm.chat / agent.subtask
```
span kind(OpenInference):CHAIN(编排)/ LLM / RETRIEVER(检索)/ TOOL(工具)/ AGENT(子 Agent)/ EMBEDDING。

## 4. 每条 span 必带
- `timestamp` / `trace_id` / `span_id` / `parent_span_id` / `module` / `action`
- `duration_ms` / `status`(ok/error/degraded)
- 入参摘要 / 出参摘要(**脱敏后**)/ `tags`(租户、模型版本、Prompt 版本、Agent 身份)

## 5. 决策可解释
- 路由决策、置信度、引用来源(检索到的文档 id/片段)写入 span attributes,支撑「某次决策依据」回溯。
- 人工接管点:会话卡片字段(意图/已确认信息/置信度/决策链)与 trace_id 关联。

## 6. 测试
- 端到端 `trace_id` 一致性测试:一次请求贯穿各模块 span 共享同一 trace_id。
- 采样/脱敏测试;观测压测(高并发下采集不丢、不阻塞业务)。

## 7. 失败处理
- 采集端故障 → 日志本地缓冲、异步上报,不阻塞主流程;Trace 丢失 → 基于结构化日志重建关键链路。
