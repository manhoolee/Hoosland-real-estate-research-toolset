# ADR-0005：Harness 插件、Skill 与知识层边界

- 状态：Proposed
- 日期：2026-08-26

## 背景

Hoosland 以 DeepSeek Harness 作为 Agent 运行控制层。Harness 基于 Cordis 构建，模型适配器、工具注册、Skill provider、Session 和 Agent Loop 都通过插件组合。官方架构建议通过扩展点挂载新行为，而不是 fork 或修改 Harness 内核。

本项目还要增加两类能力：

1. 可替换、可组合的专业 Skill；
2. 持久化的项目经验提纯库，包括资料、证据、ProjectCase、KnowledgeUnit、专家审核、版本、权限、评测和结果回灌。

“Harness 一切皆插件”描述的是 Harness 运行时扩展方式，不代表所有业务数据、数据库迁移、审核状态和产品约束都应该成为随 Cordis 插件生命周期启停的内存能力。需要明确哪些部分可插拔，哪些部分必须由产品固定控制。

参考官方说明：

- [DeepSeek Harness Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)
- [DeepSeek Harness Skills](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)
- [DeepSeek Harness Tools](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/tools.md)
- [DeepSeek Harness MCP Client](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)

## 决策

采用：

```text
固定产品内核
+ Harness 可插拔运行能力
+ 可插拔 Skill 资源
+ 薄知识工具适配插件
+ 独立持久知识服务
```

不 fork DeepSeek Harness。Hoosland 通过 versioned `cordis.yml`、Skill provider 和 MCP/Tool 扩展点接入能力。

### 1. DeepSeek Harness 是 Agent 控制层

Harness 负责：

- Agent Loop；
- LLM、Tool、Skill、Session 和沙箱组合；
- 工具调用与取消；
- 本轮 Agent 运行事件和会话日志；
- Cordis 插件生命周期。

Hoosland 固定并测试一个受控 Harness 版本和产品 composition，但不修改 Harness 内核。

### 2. Skill 保持可插拔，但不是普通业务数据库插件

专业 Skill 继续作为 Harness Skill resource 存在，由 `ctx.skills` provider 发现和加载。单个 `SKILL.md` 是可选指令资源，不需要为每个 Skill 单独实现 Cordis Service 插件。

Skill 分为两类：

- `comprehensive-real-estate-expert`：产品 profile 要求的总控 Skill。其具体内容仍是版本化 Skill 资源，但“每轮从总控进入、缺失时 fail closed”属于应用固定约束。
- 研究、产品、营销、运营和交付专项：可安装、替换、升级和按 profile 组合的专业 Skill。

每个进入知识决策链的 Skill 需要机器可读 `SkillContract`，说明输入 Schema、允许消费的 KnowledgeUnit 类型和状态、冲突策略、未知条件策略和输出 Schema。

### 3. KnowledgeUnit 是数据，不是 Skill 或 Cordis 插件

`KnowledgeUnit` 及其版本、证据、适用条件、反例和有效期保存在知识数据库中。它们不能通过安装 Skill 文件或启动插件自动成为正式知识。

KnowledgeUnit 的状态变化由持久化审核流程控制：

```text
candidate → expert_review → published → challenged → superseded / retired
```

LLM 和 Agent 可以生成候选知识，但不能自动批准、发布、覆盖或废止正式知识。

### 4. 知识库提纯库是固定产品服务

以下能力由 Hoosland Application/Knowledge Service 持久负责：

- Document、DocumentVersion 和 EvidenceSpan；
- ProjectCase、ContextSnapshot、Decision、Action 和 Outcome；
- Knowledge Compiler、专家审核、KnowledgeUnitVersion；
- PostgreSQL Schema、迁移、事务、权限和审计；
- FTS、pgvector 和图谱投影；
- 历史时间截断、评测、结果回灌和知识复审；
- 知识资料库和审核 UI。

PoC/MVP 初期可以与现有应用位于同一 Git 仓库或部署进程，但知识核心必须是独立 Python package，并通过 Application adapter 单向调用；核心包禁止导入 FastAPI route、Harness、MCP 和现有 Agent 状态。首个提纯 PoC 通过 CLI/pytest/独立存储验证，不要求立即拆成独立微服务；未来可按容量和权限需要拆分进程。

### 5. Harness 通过薄适配层调用知识服务

知识服务向 Harness 暴露稳定、JSON 可序列化的只读或受控 Tool：

```text
knowledge.prepare_case
knowledge.find_applicable
knowledge.compare_cases
knowledge.get_evidence
knowledge.verify_claims
knowledge.record_decision
knowledge.record_outcome
```

首期优先通过 MCP 暴露。当前产品 composition 已使用 `@deepseek-ai/dsh-mcp-client`，因此可以增加知识工具 endpoint 或独立 `serverName: knowledge` 的 MCP plugin row，让工具注册进 `ctx.tools`。

实现时必须以项目锁定的 Harness runtime 版本为准。当前项目固定 `deepseek-harness-sdk==0.1.1rc1`，而官方 `master` 文档仍在演进；外部示例不能直接复制。尤其当前官方 `ToolDefinition` 要求声明 canonical `output`，缺少输出 Schema 的示例只能作为概念草图。PoC 选择 MCP 也可以降低 TypeScript Cordis API 与 Python 应用之间的版本耦合。

适配层只负责：

- 身份和本轮 project/conversation scope；
- Tool JSON Schema；
- 调用知识服务；
- 错误、超时、取消和结果映射；
- 最小审计元数据。

适配层不得包含领域本体、数据库事务、知识审核或知识发布逻辑。

如果未来必须监听 `agent/*`、`tools/*` 事件、注入 scoped context 或提供 Harness 原生 UI，再增加薄 Cordis 插件；仍不把知识数据库和编译器搬进插件。

### 6. 产品硬约束不交给 Skill 自觉执行

以下能力固定在 Application/Knowledge Gate：

- 总控入口注入和缺失 fail closed；
- 用户、项目和资料权限；
- EvidenceSnapshot 与 KnowledgeSnapshot 冻结；
- scope、日期、单位、公式、来源存在性和未来泄漏检查；
- 候选知识必须人工批准；
- 输出 Claim 核验和发布状态；
- 审计、版本、迁移和回滚。

Skill 可以决定专业分析方法和调用顺序，但不能绕过这些硬约束。

## 运行链

```text
Hoosland Application
→ 冻结 Project / Evidence / Knowledge Snapshot
→ 启动 DeepSeek Harness
→ 确定性加载总控 Skill
→ 总控按任务加载专业 Skill
→ Skill 通过 MCP Tool 获取 KnowledgePacket
→ Agent 形成结构化 Claims 和建议
→ Application Verification Gate 核验
→ 保存结果、审计和终态
```

## 边界矩阵

| 能力 | 形态 | 是否可替换 | 是否产品硬约束 |
|---|---|---:|---:|
| DeepSeek Harness / Cordis | 外部运行控制层 | 固定版本后可升级 | 是 |
| `cordis.yml` 产品 composition | 版本化产品配置 | 可按 release 替换 | 是 |
| LLM Provider | Cordis plugin | 是 | 否 |
| 总控 Skill 内容 | Harness Skill resource | 是，需联合发布 | 入口与缺失检查是 |
| 专业 Skill | Harness Skill resource / bundle | 是 | 否 |
| Skill provider | Cordis plugin | 是 | profile 必须提供 |
| 知识 Tool 适配器 | MCP client row 或薄 Cordis plugin | 是 | Tool 契约固定 |
| KnowledgeUnit | 数据库中的版本化数据 | 可发布新版本 | 是 |
| Knowledge Compiler | Application/Knowledge Service | 可替换实现 | 审核链固定 |
| PostgreSQL/权限/审计 | 持久产品基础设施 | 可迁移实现 | 是 |
| FTS/pgvector/AGE | 知识服务内部适配器和派生索引 | 是 | 否 |
| 核验与发布 Gate | Application 固定状态机 | 规则可版本化 | 是 |
| 知识审核和评测 UI | Application 功能模块 | 可演进 | 是 |

## Tool 权限分级

模型可直接调用：

- 查询适用知识；
- 对比案例；
- 打开授权证据；
- 提交候选 Claim；
- 请求确定性复算。

需要明确权限或人工批准：

- 保存正式决策；
- 回写实际结果；
- 创建候选 KnowledgeUnit。

不得由模型直接完成：

- 批准或发布 KnowledgeUnit；
- 修改已发布版本；
- 废止生产知识；
- 修改 SkillContract、权限或审核策略；
- 绕过核验 Gate 发布正式结论。

## 后果

正面影响：

- 符合 Harness 插件式扩展，不需要 fork 内核；
- Skill、知识数据和运行控制可以独立版本化；
- 更换 Harness、图引擎或检索算法时，组织知识不被绑定；
- Agent 运行失败或插件卸载不会破坏知识库事务和审核状态；
- 权限、审计和发布门不依赖 Prompt 自觉执行。

成本与风险：

- 需要维护 Tool、SkillContract 和知识服务三类版本兼容关系；
- MCP/HTTP 增加一次调用和错误处理边界；
- Application 与 Harness 之间必须冻结并传递明确的 project scope；
- 如果 Tool 粒度过细，Agent 调用成本和编排复杂度会上升。

## 被否决的方案

### 所有能力硬编码进 Application

被否决，因为会失去 Harness 的 Skill、Tool 和 Provider 可组合性，专业能力升级需要修改主应用。

### 把知识库和编译器全部写成 Cordis 插件

被否决，因为持久数据库、迁移、专家审核、权限和结果回灌不应依赖 Agent 插件生命周期，也会过度绑定 Harness 预览版 API。

### 把 KnowledgeUnit 做成动态 Skill

被否决，因为知识和方法职责不同。大量经验 Skill 会污染 Skill 路由、缺少结构化适用条件和反例，也无法可靠进行数据库查询、时间过滤和版本审核。

### 只把知识库做成 RAG Tool

被否决，因为只能返回相似文本，无法保证适用条件、反例、项目时间截断和专家审核。

### Fork DeepSeek Harness

被否决，因为官方已经提供 Tool、Skill、Event、MCP 和 composition 扩展点；fork 会扩大升级和安全维护成本。

## 渐进实施

1. 核心 PoC：建立零 Harness 依赖的独立 package，以 CLI/pytest 跑通证据、案例、候选、审核、版本和快照，不注册 Tool。
2. 独立 Beta：提供管理写 API 与生产只读 Query API，验证 KnowledgePacket、适用性、反例和快照复现。
3. Harness 灰度：通过现有 MCP Gateway 或独立 `serverName: knowledge` 暴露最小只读 Tool；先手动触发，再 shadow/warn。
4. 生产试点：对 Tool 增加 project scope、RBAC、超时、审计和可观测性；知识发布仍只走 Application 审核流。
5. 后续：仅在需要 Harness 原生事件、scoped context 或 UI 插槽时开发薄 Cordis plugin。

## 回滚

通过 Feature Flag 停止知识 Tool 注册或禁用 Knowledge Layer，Harness 恢复现有 Skill-only 运行。回滚不得删除 Document、ProjectCase、KnowledgeUnit、审核和审计数据；FTS、向量和图谱投影可以重建。

## 待确认

- PoC 是复用现有 `capability` MCP serverName，还是直接建立独立 `knowledge` serverName；
- `record_decision` 和 `record_outcome` 是否允许 Agent 提交待审核记录，还是只由 Application UI 写入；
- 总控 Skill 与专业 Skill 的 `SkillContract` 放在 Skill bundle 还是独立 registry；
- 哪些核验错误允许 Agent 自动修订一次，哪些错误必须直接中止。

