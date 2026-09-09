# 参考 · 技术选型建议与已验证来源链接

> 落地第一步:定技术栈。基于实时搜索整理(2026-08-09),含适用场景、成本、锁仓风险。详见 workflow 知识库 `07-外部参考与落地/`。

## 一、Agent 编排框架

| 框架 | 优势 | 局限 | 适合 |
|------|------|------|------|
| **LangGraph** | 状态机细粒度控制;检查点/断点续传;`interrupt()` 人在环中;OpenTelemetry 原生 | 学习曲线陡 | 复杂有状态工作流、生产 |
| **CrewAI** | 角色化原型快 | 细粒度控制弱 | 快速原型 |
| **AutoGen** | 会话式协作研究强 | 生产编排有限 | 研究/协作 |
| **Claude Agent SDK** | 「Claude Code as a library」;`Task` 工具委派子 Agent;内置 Guardrails;结构化输出;handoff 链;逐 agent 模型选择 | 绑定 Claude 生态 | Claude 生态多 Agent 自动化 |
| **Bedrock AgentCore** | 无服务器托管;内置共享记忆 | AWS 绑定 | AWS 云原生规模化 |

**结论**:生产可控 → LangGraph 或 Claude Agent SDK;**混合设计(规则协调 + LLM 推理)可靠性优于纯 LLM 框架**,不要迷信单一框架。

## 二、可观测性

| 工具 | 特性 | 注意 |
|------|------|------|
| **LangSmith** | LangChain/LangGraph 深度集成;评估/Prompt 管理/部署 | 仅 SaaS(2026.01 出 Self-Hosted v0.13);免费 5K traces/月 |
| **Arize Phoenix** | **OTel 原生、OpenInference-first**;开源可自托管 | 自托管高负载摄取需注意 |
| **Langfuse** | 开源优先;Prompt 管理;Experiments CI/CD | 开源友好 |
| **W&B Weave** | 自动埋点 OpenAI/Anthropic/LiteLLM 等 | 适合已在 W&B 生态 |

**结论**:优先 **OpenInference / OpenTelemetry GenAI 语义约定** + OTLP 后端,避免锁仓;评估分数是一等遥测(幻觉即生产事故)。

## 三、长期记忆

| 方案 | 机制 | 存储 | 适合 |
|------|------|------|------|
| **MemGPT/Letta** | LLM 自管理记忆;Core/Recall/Archival 三级 | LanceDB 默认,可换 Chroma/pgvector | 自托管状态型 Agent |
| **Mem0** | 面向查询记忆层;`memory_retrieval`/`memory_update` 节点 | 多向量库 | 与 LangGraph 组合 |
| **Zep** | 时序记忆 + 知识图谱 | 托管/自托管 | 长期会话 |
| **Graphiti** | 时序知识图谱记忆 | 图库 | 关系推理 |

**落地教程**:MemGPT/Letta/Zep/Graphiti 30 个可跑 Notebook — https://github.com/NirDiamant/Agent_Memory_Techniques

## 四、向量数据库

| 库 | 特点 | 适合 |
|----|------|------|
| **Chroma** | 轻量、嵌入式 | 原型/中小规模 |
| **pgvector** | Postgres 扩展,事务一致 | 已有 Postgres |
| **Milvus** | 分布式、高可用 | 大规模生产 |
| **Qdrant** | 独立向量库,过滤强 | 需复杂过滤 |

**结论**:Chroma/pgvector 起步,大规模再迁 Milvus/Qdrant;避免过度选型。

## 五、代码沙箱

- **E2B**:Firecracker 微 VM,硬件级隔离,~150ms 冷启动,Apache-2.0 — https://www.e2b.dev/blog/stackai
- **CubeSandbox**:自托管 KVM 微 VM,<5MB/沙箱,与 E2B 协议兼容 — https://github.com/weave-logic-ai/CubeSandbox
- **铁律**:绝不在宿主进程执行 LLM 代码;Docker 共享内核不足,需 VM 级;出口网络默认阻断白名单放行;沙箱默认临时超时自毁;最小权限。

## 六、评估工具

| 工具 | 类型 | 特点 |
|------|------|------|
| **DeepEval** | pytest 风格本地评估 | Prompt/RAG/Agent |
| **agent-eval** | 统计回归 | A/B 各跑 50 次,p-value/效应量 |
| **Promptfoo** | Prompt 回归测试 | 版本 diff、门禁 |
| **MLflow GenAI** | 平台 | trace + evaluate + Prompt Registry |
| **Ragas** | RAG 专用评估 | 忠实度/答案相关性 |

**结论**:评估工具是「引擎」,组织要自己定义「质量模型」(领域 rubric、加权计分卡、发布门禁)。

## 七、RAG 生产实践

- 管线:`embed+BM25(并行)→ RRF 融合(k=60)→ 重排(交叉编码器)→ top-5/20`。
- 铁律:BM25 与向量搜同一语料;重排候选 top-50 起;分块 512 token + 50 重叠。
- 指标:Recall@5、MRR、nDCG@20、忠实度(Ragas ≥0.85)。
- 落地实现:
  - 生产级 RAG(分块/混合/重排/评估/可观测): https://github.com/avuppal/enterprise-rag
  - RRF+HyDe 完整实现: https://github.com/MudassarHakim/Advance-RAG-ReRanking-FusionRetreival-RRF-HyDe
  - 离线生产 RAG(可验证引用): https://github.com/adityavijay21/rag-hybrid-search
  - 微软高级 RAG 官方课程: https://learn.microsoft.com/en-us/training/modules/aaai-implement-advanced-rag-azure-ai-search/

## 八、多 Agent 架构与落地参考

- 5 种生产模式: https://www.kdnuggets.com/5-essential-design-patterns-for-building-robust-agentic-ai-systems
- 2026 模式指南(Orchestrator-Worker/Evaluator-Optimizer): https://www.sitepoint.com/the-definitive-guide-to-agentic-design-patterns-in-2026/
- Claude Agent SDK 子 Agent 最佳实践: https://code.claude.com/docs/en/agent-sdk/subagents
- 无服务器 LangGraph 多 Agent(AWS): https://aws.amazon.com/cn/blogs/machine-learning/build-highly-scalable-serverless-langgraph-multi-agent-systems-in-aws-with-amazon-bedrock-agentcore/
- 企业真实架构(Yachai,读/写分离、无状态编排): https://github.com/simonamador/enterprise-llm-agent-architecture
- 可靠性/自愈: https://www.deepset.ai/blog/harness-engineering ; https://www.npmjs.com/package/@varpulis/agent-runtime

> 完整来源索引(10 维度、40+ 条)与落地案例集(Elastic/Cognizant/ServiceNow/Snowflake 等真实指标)见 `workflow/07-外部参考与落地/`。
