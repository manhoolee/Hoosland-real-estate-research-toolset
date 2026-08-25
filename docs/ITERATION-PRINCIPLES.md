# 迭代原则

本文件定义 Hoosland Agent Tools 的长期演进不变量。目标不是锁死实现，而是保证每次升级都能解释“改了哪一层、为什么更好、如何验证、怎样回滚”。

## 1. 分层演进

系统分为四层：

1. **LLM / Provider**：推理能力和模型接口；
2. **Harness / Cordis**：执行循环、沙箱、会话和工具；
3. **Skill**：领域触发、方法、证据、计算和交付规范；
4. **Application**：交互、持久化、文件隔离、安全编排和运行恢复。

修改一层不得把其他层的职责偷偷复制进来。替换模型不应改写 Skill 方法；增加 Skill 不应绕过 Harness 权限；UI 变化不应改变证据标准。

## 2. 单一可信源

- 全局身份、权限、安全、保密、证据与执行真实性只由 versioned System Prompt 定义；
- Skill 只补充领域角色、触发范围、工作方法和局部边界；
- 普通 user prompt 只承载当前请求、附件清单和已确认历史；
- 同一规则不得在多处维护互相漂移的副本。

System Prompt 变更必须升级 prompt version，并增加对抗或回归用例。

## 3. 多版本解耦

分别管理：

- Application SemVer；
- System Prompt version；
- Skill bundle SemVer；
- Project state Schema version；
- Build ID。

只有持久化数据契约变化时才升级 Schema；升级必须同时提供迁移器、兼容范围和回滚方法。不得只为让展示数字一致而改写已有项目状态。

## 4. 功能价值优先

槽位、端口、目录、备份和发布脚本只是交付保障，不能替代真实业务价值。每次迭代必须至少回答：

- 它解决了哪个真实地产任务？
- 输出质量或运行可靠性如何量化改善？
- 哪个回归用例能阻止该问题再次出现？

## 5. 不可变发布

- 每次构建进入新的 release 目录；
- 验证通过后原子切换 `current`；
- 禁止直接修改在线 release；
- 保留前一稳定 release 和完整回滚点；
- 奇数迭代优先槽 A，偶数迭代优先槽 B，避免覆盖正在服务的基线。

## 6. 状态与秘密隔离

两个槽位的下列资源必须独立：

- `DATA_DIR` 与 conversation workspace；
- Harness sessions；
- operation logs；
- encrypted runtime config；
- 管理员 session secret；
- MCP token；
- Skill 目录和 build ID。

客户数据不自动迁移，不共享可写目录。确需迁移时必须单独定义范围、备份、校验、回滚和用户授权。

## 7. 幂等恢复

- 先持久化用户消息和 running 状态，再启动模型；
- 每个请求有 `client_request_id`，每次运行有 `run_id`；
- 刷新、断网、SSE 中断和多标签竞态不得重复启动同一任务；
- 重试引用原消息和原附件，不复制业务输入；
- 终态持久化与 assistant 结果保持一一对应。

## 8. 能力真实与 fail closed

缺凭证、缺依赖、未调用、调用失败、排队中和候选稿必须准确呈现。未配置能力返回明确的 `CAPABILITY_NOT_CONFIGURED`，不得用模型补造结果。

“代码完成”“构建成功”“文件生成”“逐页验证”“正式放行”“已发布”是不同状态，不得互相代替。

## 9. 证据与计算纪律

- 区分 `FACT`、`DERIVED`、`INFERENCE`、`HYPOTHESIS`、`RECOMMENDATION`；
- 关键数据包含来源、日期、范围、口径、单位和置信度；
- 公式、输入、舍入和敏感性可复算；
- 来源冲突并列记录，不静默选边；
- 证据不足时降低结论等级，不伪造精度。

## 10. 正式交付闸门

正式成果固定经过：

```text
业务责任专项 → 报告编辑 → 报告设计 → 按需 PDF → 最终交付 QA
```

PDF 技术通过不能替代业务、证据、版权、隐私或发布放行。P0/P1 未关闭时，不得声称“可提交”“可发布”或“可决策”。

## 11. 安全最小化

- 发布包不包含客户会话、附件、成果、密钥、Cookie、日志或浏览器 profile；
- Harness 子进程只获得当前任务必要的凭证；
- 日志只保留必要元数据；
- 外部发布、发送、公开链接和权限变更必须再次取得明确授权；
- 公共文档只保留脱敏拓扑和通用示例。

## 12. 发布分级

```text
development → candidate → online/observing → stable demo
```

只有完成自动化测试、真实模型与 Provider、Prompt 对抗、文件成品、PDF、浏览器、隔离和回滚验证，关闭所有 P0/P1，并完成既定观察期后，才能晋级为稳定演示版本。

## 13. 可审计与可回滚

每个 release 应包含：

- manifest 与版本矩阵；
- 文件 SHA-256；
- build ID 和 Git commit；
- 自动化及真实能力测试记录；
- 数据和配置迁移说明；
- 回滚入口与前一稳定 release。

故障时只回滚受影响槽，先保留脱敏诊断证据，不破坏另一槽的服务和数据。

## 14. Definition of Done

一次可发布迭代至少满足：

- [ ] 需求、影响层和版本变化已说明；
- [ ] System Prompt、Skill、Schema 没有职责漂移；
- [ ] 后端单元测试和 Python 编译通过；
- [ ] 前端类型检查和生产构建通过；
- [ ] Skill manifest、脚本与 smoke tests 通过；
- [ ] 真实模型及本次涉及的 Provider 通过最小验收；
- [ ] 生成文件已实际打开，视觉文件已渲染检查；
- [ ] 刷新、取消、重试与幂等边界无回归；
- [ ] 暂存区无密钥、客户数据、缓存、发布包和现网配置；
- [ ] release 可回滚，文档与 CHANGELOG 已更新。
