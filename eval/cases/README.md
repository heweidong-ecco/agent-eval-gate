# eval/cases/ · 失败回灌用例库(「失败即补 case」落地点)

> 依据:B `05-独立模块工作流/05-模块-评估与测试-v1.0.md:84`「**失败即补 case**:线上新失败 → 立即补进评估集复现」
> + 数据飞轮 `06-优化-数据飞轮与主动学习-v1.0.md:29-32`「案例库沉淀成功/失败案例(带标签)。失败案例 → **防错规则**」。
> Kit 约定(`eval/README.md:13,25,28,63`)只给了**一句话**,本目录是它的**结构落地**。

## 这里放什么(与 `eval/*.evals.json` 的分工)

| | `eval/*.evals.json` | **`eval/cases/`** |
|---|---|---|
| 用途 | **跑一轮评测**的输入 | **沉淀失败**、防重犯的案例库 |
| 内容 | 全量评测集 | **只放「失败过」的用例**(含根因) |
| 判据 | 通过/失败 | **为什么失败 + 复现条件 + 防错措施** |

**一条失败,两个动作**:① 若它属评测集该覆盖的 → 补进 `*.evals.json`;② **同一条**必须在 `cases/` 留档(带根因)。
没有 ② 的话,下次没人知道「这条为什么一直是 fail」,会被当成噪声忽略或误删。

## 单条格式

文件与评测集同构(**可直接被 `load_evals` 加载校验**),每条**额外**带 `regression` 块:

```jsonc
{
  "version": 1,
  "threshold_ref": "eval/阈值.md",
  "sut_default": "fastapi-rag",
  "evals": [
    {
      "id": 26, "module": "rag", "tags": ["regression"],
      "input": { "question": "文档中提到了几种数据库？" },
      "expected": { "answer_contains": ["三种", "三类", "3 种", "3种"] },
      "source": "01.FastAPI RAG Agent archive eval_dataset.json id:25",

      "regression": {                                  // ← 本目录独有
        "from_run": "20260910-221513-dde2e4d6",        // 哪次 run 暴露的
        "observed": "被测答『两种数据库:向量数据库 和 Redis』",  // 实际观测
        "root_cause": "检索未召回 PostgreSQL 那篇 → 被测按召回到的 2 篇作答",  // 根因(必填)
        "status": "open",                              // open | fixed | accepted(接受为已知基线)
        "prevention": "待办:核查 top_k 与召回策略(R1b 口径关闭重排)"   // 防错措施
      }
    }
  ]
}
```

**必填**:`regression.from_run` / `regression.observed` / `regression.root_cause` / `regression.status`。
缺 `root_cause` 的条目由 CI 拦下(`.github/workflows/eval-gate.yml` 的「失败集完整性检查」)。

## 纪律

1. **失败即补**:任何一轮评测出现 `failed > 0`,当轮节点**不算完成**,直到失败条目在 `cases/` 留档。
2. **带根因,不带情绪**:写「为什么」,不写「谁的问题」;根因写不出来就先记 `root_cause: "待查"`,`status: open`(**不许空着**)。
3. **`status` 演进**:`open`(已知未修)→ `fixed`(已修且有回归验证)→ `accepted`(业务方接受为已知基线,须记理由)。
4. **不得删除**:条目只能改 `status`。要删必须走 DEC 并说明理由(删一条失败案例 = 丢掉一条教训)。

## 变更记录
- 2026-09-10 建立:补上 Kit 只给了「一句话」却未落地(scaffold 不创建目录、无模板、无 hook)的结构缺口;首份 = 阶段3 R1b 失败回灌。
