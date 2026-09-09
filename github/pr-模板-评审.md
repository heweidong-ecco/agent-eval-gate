# GitHub 规范 · PR 模板与评审(Agent 化)

> 复用通用 checklist;Agent Kit 增补 4 个必附证据:**评估集回归结果 / 是否改 Prompt·工具·记忆 / 观测证据 / 契约漂移说明**(引 B `02-方法论-工程纪律与CI-CD-v1.0.md` §一契约测试 + §4.1 评估流水线;`05-模块-评估与测试`;`06-优化-版本迭代与发布策略`)。凡动 Prompt/工具/记忆策略的 PR,CI 会跑 eval-gate(见 `ci-cd-骨架/ci.yml`)。

## PR 描述模板(拷进每个 PR body)
```markdown
## 改动
- 一句话;列出关键文件。
- module label:…(14 模块之一;见 issue-模板-labels.md)

## 关联
- Closes #<issue>

## 评估证据(Agent 特有,必附)
- [ ] 评估集回归结果:命令 + 通过率/阈值对比(附链接或截图)
      —— 例:pytest evals/ -q → 92%(阈值 ≥90%,PASS)
- [ ] 是否改 Prompt / 工具 / 记忆策略?是 → 列改动与版本号;否 → 写明"未改"
- [ ] 观测证据:trace_id / 日志片段 / 监控截图(引 B 05-模块-全链路追踪与观测)
- [ ] 契约漂移说明:本次是否动接口/Schema(OpenAPI/MCP Schema/内部契约)?
      是 → 契约测试结果;否 → 写明"无契约变更"
- [ ] 本 PR 是否补/改评估集 case?(失败即补——B 05-模块-评估与测试 §10.3)

## 验收证据(代码/通用,必须)
- 测试命令与输出(通过几/失败几)
- lint/type/build 结果
- (若 UI)截图 / 行为

## 风险与回滚
- 影响面 / 需注意;是否可回滚(迁移? 破坏性? 模型/Prompt 能否秒级切回——B 05-模块-提示工程与模型路由)

## Review checklist(单人可自检或子代理代审)
- [ ] 需求点是否全实现(对照 issue/ROADMAP 验收)
- [ ] 测试覆盖关键路径;无"为绿而绿"的测试
- [ ] 无越权/明文密钥/注入等安全问题(引 B 03-原则-安全合规与伦理)
- [ ] 契约/命名与 contracts/ 一致;无漂移
- [ ] Prompt/评估集/模型版本已随代码入库且版本号可追溯
- [ ] commit 规范 + 只含本 issue 改动
```

## 评审方式(单人)
- 每 PR 至少一轮 **code review**(superpowers 的 task/whole-branch review 或子代理)。
- Critical/Important 必须处理后再 merge;Minor 记 deferred 到最终 review。
- 你不信任某改动 → 回退分支,别带病合并。
- **行为类改动**(改 Prompt/记忆策略/路由)以评估回归结果为准,不以"我觉得行"为准;回归不达标即 Block。

## Merge 条件(全部满足才可)
1. CI 绿:**代码门**(lint/test/build)**+ eval-gate**(若触发;低于阈值红)——两套门独立看,别合并成一个绿灯(见 `docs/留痕×指标挂钩.md` §三)。
2. Review 无未决 Critical/Important。
3. 描述含验收证据(含 Agent 四必附)。
4. (发布点)经 gate-review / 上线 check;发布授权 = 你真人(见 `ci-cd-骨架/deploy.yml`)。

---
*变更记录:M1 首版(2026-09-09)。旧 Kit PR 模板 + Agent 四必附证据(评估回归/Prompt·工具·记忆/观测/契约漂移)。*
