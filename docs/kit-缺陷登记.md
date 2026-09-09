# kit-缺陷登记 · agent-eval-gate(母体 Kit 试金石)

- 目的:本仓是母体 Kit(`product-agent-dev-os`)试金石;推进中暴露的 Kit 缺陷在此登记,业务方审批后修母体回流,使"项目做得越多、Kit 越完善"。
- 判定与触发:skill `kit-feedback`;5 触发点(init / 定调压测门 / gate-review / 留痕-checks / 节点完成)末尾必问。
- 状态:待审批 → 已批准 → 已修母体 → 已回流。

## 登记表
| KD | 线索 | 证据 | 影响 | 最小修复建议 | 状态 |
|---|---|---|---|---|---|
| KD-1 | K1 门禁/流程 | gate-review/阶段卡门禁允许 AI 自评 PASS(本仓曾 1406d74 自宣阶段1 PASS) | 派生项目可绕过"人验收" | gate-review skill 内联"PASS=建议、终裁=业务方签核" | 已批准 · 已修母体(部分,a92be73);补:gate-review 内联 |
| KD-2 | K2 定义缺失 | init-runbook 无"定调压测/逐条签核"步骤(本仓曾先标"已拍板"后认"代定") | 定调易被 AI 越权 | runbook 加 定调压测(grilling)+ 签核记录 | 已修母体(a92be73:初始化-runbook §6.0) |
| KD-3 | K2/K3 留痕缺口 | issue/分支/PR 在无 gh 时不可验证、无最小留痕替代 | 留痕闭环断 | runbook 明确最小留痕(`验收:`/`Closes #`) | 已批准 · 待补(母体) |
| KD-4 | K5 适配断层 | scaffold 假设 chat-Agent/14 模块;评测门被迫改写 E1–E9 | 非 chat-Agent 套用成本高 | agent-system-creator 加"非对话 Agent 适配 B"指南 | 已批准 · 待补(母体) |
| <!-- 后续新 KD 追加至此(触发点问答结果) --> | | | | | |

## 回流记录
- 母体 `a92be73`(2026-09-10):缺陷反馈子系统 + KD-1..4 登记(业务方批准)。KD-1/3/4 补全项挂母体待办。

## 触发点纪律(本仓已启用)
进新阶段/大节点/关键选型前 = 定调压测门(grilling)→ 通过签核后才推进;其余触发点(init/gate-review/留痕-checks/节点完成)末尾自查是否暴露新 KD。
