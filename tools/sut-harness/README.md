# tools/sut-harness/ · 真实被测的运行适配层

> **一句话**:把外部被测(`01.FastAPI RAG Agent`)**零改动**地跑起来,供评测门做真实链路评测。

## 为什么它在本仓(而不是被测仓)

| 理由 | 说明 |
|---|---|
| **职责归属** | 它是**评测门**为"在受控环境里跑外部被测"造的适配层,属门的基础设施 |
| **避免第三套运行方式** | 被测仓**已有**自己的官方方式(`docker-compose.yml` / `Dockerfile` / `deploy.sh` / `dev.sh`) |
| **不污染对方仓库** | 不往被测的 GitHub 历史里混入评测门的关注点 |
| **随门演进** | 它会随评测门变化(加隔离库、放宽会话预算),放本仓才不用每次去改被测仓 |

被测路径通过 `EVAL_SUT_REPO` 注入 ⇒ **本仓不硬编码任何外部绝对路径**。

## 🔴 2026-10-18:退出条件已满足 —— 改走官方镜像

**原退出条件**:
- 被测侧用**官方方式**重建镜像可用(`docker compose build api && docker compose up -d api`),且
- 重建后的镜像**能力探针通过**。

**实测**:官方镜像 `fastapi-rag-agent:latest`(由被测仓 `app/Dockerfile` 构建)可用,
能力探针通过 ⇒ **达到退出条件**。

**因此本层已收窄成"薄包装"**:
- 只用官方镜像,**不再**在启动时 `pip install` 补依赖,也不再用 `/deps` 卷与 `sut_run.py` 启动器;
- **源码只读挂到 `/src`,容器启动时复制到可写 `/app` 再跑 `uvicorn`** ——
  ⚠️ **不能**直接把源码只读挂到 `/app`:应用会写 `/app/.mem0/qdrant/.lock`,
  只读挂载会导致启动失败(2026-10-18 实测 `OSError [Errno 30] Read-only file system`);
- 仍保留两件**只有这层能做**的事:
  1. **能力探针**(`/health` 200 ≠ 答得了,见下「陷阱」);
  2. **被测自证**(DEC-016:把被测 commit 与探针结果写进 `eval/runs/.sut-harness.env`)。

> ⚠️ `sut_run.py` / `sitecustomize.py` 是旧路径的遗留文件,**当前脚本不再使用**;
> 保留它们只为在旧被测 commit 上做历史复查。新路径不要调用它们。

## 用法

> ⚠️ **起依赖只用 `docker start`,<u>不要</u>用 `docker compose up`**(业务方 2026-09-15 指示:
> **本机内存有限,只开需要的**)。需要的只有两个:`postgres-rag` / `redis-rag`
> —— 它们由**被测仓自己的** `docker-compose.yml` 定义(项目名 `my-fixed-name`),
> 数据卷仍在,`docker start` 会**复用原卷**。
> 脚本自身就是这么做的(见 `run_sut.sh` 的 `docker start postgres-rag redis-rag`)
> ⇒ **不要额外跑 compose**:那会把 compose 里其余服务一并拉起,白吃内存。

```bash
export EVAL_SUT_FASTAPI_API_KEY=<admin key>     # 能力探针要用;跳过它会失去最重要的那道保险
tools/sut-harness/run_sut.sh                    # 默认路径;可用 EVAL_SUT_REPO 覆盖

# 评测隔离库 + 放宽会话预算(新版被测默认 5 万 token/会话,单轮会触顶)
EVAL_SUT_DB=rag_eval_20261018 \
EVAL_SUT_SESSION_TOKEN_LIMIT=200000 \
tools/sut-harness/run_sut.sh
```

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `EVAL_SUT_REPO` | (内置一个默认路径) | 被测仓根目录 |
| `EVAL_SUT_IMAGE` | **`fastapi-rag-agent:latest`** | 官方镜像(由被测仓 `app/Dockerfile` 构建) |
| `EVAL_SUT_CONTAINER` / `EVAL_SUT_NETWORK` | `rag-api-eval` / **`fastapi-rag-agent_app-net`** | 容器三要素 |
| `EVAL_SUT_PORT` | `8000` | 宿主机端口(应用固定容器内 8000) |
| `EVAL_SUT_DB` | (不设) | 覆盖 `POSTGRES_DB`(评测用隔离库) |
| `EVAL_SUT_SESSION_TOKEN_LIMIT` | (不设) | 覆盖被测的 `SESSION_TOKEN_LIMIT` |
| `EVAL_SUT_LOGS_DIR` | `<本仓>/eval/runs/sut-logs` | 可写的 `/app/logs`(源码是只读挂载) |
| `EVAL_SUT_IDENTITY` | `<本仓>/eval/runs/.sut-harness.env` | DEC-016 被测自证落盘位置 |

退出码:`0` 就绪且探针通过 · `1` 起不来 · **`2` 起来了但答不了**。

## 文件

| 文件 | 作用 |
|---|---|
| `run_sut.sh` | 起依赖容器 → 起被测容器(官方镜像 + 只读挂载源码)→ 等就绪 → **能力探针** → 写被测自证 |
| `sut_run.py` | **遗留**(旧最小启动器),当前脚本不使用 |
| `sitecustomize.py` | **遗留**(旧 langchain 兼容层),当前脚本不使用 |

## 陷阱清单(踩过的,别再踩)

1. **`docker run --env-file` 不剥离行内 `#` 注释** —— 被测 `.env` 里
   `LLM_MODEL_FAST=deepseek-v4-flash   # …` 会把注释整段当成**值**,
   模型名被污染后网关返回 400。⇒ 必须用 `-e` 显式覆盖(脚本已做)。
2. **`/health` 200 ≠ 被测答得了** —— `/health` 只查 DB/Redis。**能力探针是必需的**:
   2026-09-11 实测,被测能通过健康检查却对真实问题一律回「无法回答」(根因是被测的查询改写
   因 `max_tokens` 被推理吃满而返回空)。**跳过探针,跑完的结果会被误读成"被测质量崩了"。**
3. **别直接用原 `rag-api` 容器** —— 旧镜像,跑的不是当前代码。
4. **不要把源码只读直接挂到 `/app`** —— 应用会写 `/app/.mem0/qdrant/.lock` 等运行时状态
   (实测 `OSError [Errno 30] Read-only file system`)。本脚本的做法是 `/src`(只读)→ 复制到可写 `/app`;
   日志目录另挂 `EVAL_SUT_LOGS_DIR`,避免写进被测仓、保持"被测仓零改动"。
5. **新版被测有会话预算**(默认 5 万 token/会话/日)——
   跑 48 条评测前先看 `token_usage_logs` 今日余量,不够就设 `EVAL_SUT_SESSION_TOKEN_LIMIT`;
   否则尾几条会被 `429 QUOTA_EXCEEDED` 污染,看起来像被测失败。
6. **`docker logs` 为空不等于进程崩了**(旧路径遗留观察) —— 旧容器启动时先 `pip install`,
   头几十秒日志空白。官方镜像没有这一步;若仍见空白,先等 30–60s 再判,别急着重启。

## 观察记录(本层已验证有效)

- 2026-09-11:用本层跑通真实链路一轮(run `20260911-224254-be1c4574`,30/40);
  并借此**定位到被测侧一个真实的生产缺陷**(查询改写空返回导致静默降级),
  被测已修(`85e456b`)。
- 2026-10-18:**切到官方镜像**,并用隔离语料库跑完 `DEC-019` 完整 live 回归
  (run `20261018-182724-e6212c1d`,**47/48 · exit 0**)。
