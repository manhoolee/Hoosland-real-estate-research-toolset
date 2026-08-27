# Hoosland 独立知识提纯库开发步骤与敏捷实施计划

文档状态：`Draft for Review`  
文档版本：`0.1.0`  
编写日期：`2026-08-26`  
配套规格：[独立知识提纯库开发文档](KNOWLEDGE-REFINERY-CORE-DEVELOPMENT.md)  
上位计划：[知识决策系统分部实施与敏捷迭代方案](KNOWLEDGE-DECISION-SYSTEM-AGILE-IMPLEMENTATION-PLAN.md)  
迭代节拍：Sprint 0 为 1 周，此后每个 Sprint 2 周  

## 0. 实施结论

开发顺序必须是：

```text
先定义什么是可信知识以及如何评测
→ 再建立稳定证据和案例结构
→ 再让 LLM 生成有证据的候选
→ 再提炼适用条件、反例和冲突
→ 再建立审核、版本和快照
→ 再服务新项目匹配
→ 再生产化
→ 最后接入 DeepSeek Harness 和 Skill
```

第一阶段的交付物是一个零 Harness 依赖的 Python package、CLI、Golden Set 和提纯报告。不得以“已经能向量检索文档”或“Agent 已经能调用工具”代替知识提纯 MVP。

## 1. 资源和周期假设

### 1.1 推荐团队

| 角色 | 投入 | 主要责任 |
|---|---:|---|
| 后端/数据工程师 | 1–2 人 | 领域模型、存储、任务、API、权限 |
| LLM/评测工程师 | 1 人，可由后端兼任 | 提取、Prompt、质量闸门、Golden Set |
| 地产领域专家 | 0.5–1 人持续参与 | 决策域、标注、知识审核和业务验收 |
| 前端/全栈 | Sprint 4 起 0.5–1 人 | 审核、证据和项目匹配界面 |
| QA/DevOps | 兼职，生产化阶段增加 | 自动化、恢复、安全和发布 |

领域专家从 Sprint 0 开始持续参与，不是项目末期的验收资源。

### 1.2 周期估算

| 里程碑 | 累计周期 | 可交付结果 |
|---|---:|---|
| 可运行原型 | 第 3 周 | 标准文档进入，生成稳定 EvidenceSpan |
| 提纯 MVP | 第 7 周 | 证据 → 案例 → 可审核经验候选 |
| 内部 Beta | 第 11 周 | 审核、版本、快照和新项目匹配 |
| 生产候选 | 第 15–17 周 | 权限、持久任务、监控、恢复和回归门 |
| Harness 灰度 | 第 16–19 周 | 只读 MCP、一个 Skill、shadow 运行 |

以上假设为 2 名主要工程师和持续领域支持。单人开发建议按 6–9 个月估算；如果历史案例和结果数据不完整，周期应按数据治理工作量上调。

### 1.3 首期输入假设

- 锁定一个决策域：住宅项目的产品组合与首开策略。
- 选取 5–10 个 PoC 案例，其中至少 3–5 个具备“输入—判断—动作—结果”。
- 首先接受 Markdown/JSON `ParsedDocument`。
- PDF/DOCX 等通过 Docling、MarkItDown 或 X2Knowledge adapter 接入，不让解析器决定领域模型。
- 首期只接一个真实 LLM Provider，同时保留 Fake Provider。
- SQLite 用于快速测试；PostgreSQL 从审核与发布阶段成为正式目标。

## 2. 版本路线图

```mermaid
flowchart LR
  S0[Sprint 0\n契约与评测] --> S1[Sprint 1\n证据管道]
  S1 --> S2[Sprint 2\n结构化提取]
  S2 --> S3[Sprint 3\n经验提纯 MVP]
  S3 --> MVP[Core MVP]
  MVP --> S4[Sprint 4\n审核与版本]
  S4 --> S5[Sprint 5\n新项目匹配]
  S5 --> BETA[Internal Beta]
  BETA --> S6[Sprint 6\n跨项目与图投影]
  S6 --> S7[Sprint 7\n生产化加固]
  S7 --> RC[Production Candidate]
  RC --> S8[Sprint 8\nHarness 灰度]
```

| Sprint | 周期 | 版本建议 | 主要结果 |
|---|---:|---|---|
| 0 | 第 1 周 | `0.0.1` | 领域契约、Golden Set、包骨架 |
| 1 | 第 2–3 周 | `0.1.0` | EvidenceSpan 和文档版本 |
| 2 | 第 4–5 周 | `0.2.0` | Claim、Metric、结构化提取 |
| 3 | 第 6–7 周 | `0.3.0-mvp` | CaseEpisode 和 KnowledgeCandidate |
| 4 | 第 8–9 周 | `0.4.0` | 审核、不可变知识版本和快照 |
| 5 | 第 10–11 周 | `0.5.0-beta` | 新项目适用性匹配和证据包 |
| 6 | 第 12–13 周 | `0.6.0` | 跨项目归纳和图谱投影 |
| 7 | 第 14–17 周 | `0.9.0-rc` | 生产化、安全、恢复和性能 |
| 8 | 第 16–19 周，可与后期重叠 | `integration-0.1.0` | 只读 MCP 和 Skill 灰度 |

## 3. Sprint 0：领域契约与评测基线

周期：第 1 周，约 5–8 人日。

### 3.1 目标

定义“什么是知识、什么不是知识、怎样判断提纯正确”，并建立零 Harness 依赖的独立包骨架。

### 3.2 先实现

1. 首个决策域书面边界。
2. `ParsedDocument`、`EvidenceSpan`、`Claim`、`ProjectCase`、`CaseEpisode`、`KnowledgeCandidate`、`KnowledgeUnitVersion` Schema。
3. `FACT / DERIVED / INFERENCE / HYPOTHESIS / RECOMMENDATION` 分类规则。
4. Domain/Application/Ports/Adapters 分层。
5. Fake LLM、in-memory repository 和 frozen clock。
6. 第一版 CLI：`validate`。
7. 20–50 份代表性资料和至少 100 条人工标注。
8. 架构依赖测试，禁止核心引用 Harness、MCP、FastAPI 和具体 Provider。

### 3.3 本轮任务

- 创建 `packages/knowledge-refinery/pyproject.toml`。
- 定义 ID、内容哈希、版本号和时间字段规范。
- 定义 JSON Schema/Pydantic 模型和错误码。
- 建立 Golden Fixture 目录和标注模板。
- 定义质量指标、评分脚本和基线报告格式。
- 创建 ADR：独立核心包和单向依赖。
- 确认资料能否发送外部模型及数据分级规则。

### 3.4 验收标准

- [ ] 所有领域对象可序列化、反序列化并通过 Schema 校验。
- [ ] 相同输入生成稳定 ID 和内容哈希。
- [ ] Golden Set 的正确答案包含真实证据位置。
- [ ] 核心包依赖树不存在 Harness、MCP 或现有聊天后端。
- [ ] `knowledge-refinery validate fixture.json` 可独立运行。
- [ ] 至少 5 个可合法使用的项目进入案例清单。
- [ ] 技术负责人和领域专家共同批准数据字典。

### 3.5 本轮不做

- 文件 OCR 和复杂解析；
- embedding、向量库和图数据库；
- 自动知识总结；
- FastAPI、前端和 Harness 接入。

### 3.6 退出风险

如果无法找到至少 3–5 个具备实际动作与结果的案例，继续做解析可以，但不得承诺生成“已验证经验”；首期知识类型应降级为案例观察、风险线索和假设。

## 4. Sprint 1：证据化文档管道

周期：第 2–3 周，约 10–15 人日。

### 4.1 目标

把标准化资料转换为稳定、可定位、可重建的证据单元。

### 4.2 先实现

1. Markdown/JSON `DocumentParser` adapter。
2. `DocumentVersion → Block → EvidenceSpan`。
3. 标题、段落、表格和语义边界切分。
4. 页码、章节路径、表格位置、原始 locator 和文本哈希。
5. 增量导入、重复检测和幂等键。
6. 最小任务状态机和失败重试。
7. 一个 Docling 或 X2Knowledge 输出适配器 PoC。

### 4.3 实现顺序

```text
注册来源版本
→ 校验 ParsedDocument
→ 保存原始 block
→ 生成稳定 EvidenceSpan
→ 验证 locator
→ 提交事务
→ 输出导入清单
```

### 4.4 验收标准

- [ ] 同一来源版本重复导入不产生重复数据。
- [ ] 文件更新产生新版本，旧证据仍能打开。
- [ ] 每个 `EvidenceSpan` 能定位到页码、章节或单元格。
- [ ] 中断重试不会产生半成品或重复 span。
- [ ] 删除派生数据后可以从 `ParsedDocument` 重建。
- [ ] 100 页代表性文档完整进入证据库。
- [ ] X2Knowledge/Docling adapter 只输出 canonical Schema，不泄漏第三方领域字段。

### 4.5 测试

- 标题层级、列表、表格、跨页段落和空文档；
- 内容哈希和稳定 ID；
- 重复导入、版本变化和中断恢复；
- 非法编码、超长段落和恶意文件元数据；
- Golden Fixture locator 回跳。

### 4.6 本轮不做

- 将 X2Knowledge 问答对当作经验；
- 全格式解析和复杂图表视觉理解；
- LLM 提纯、向量检索和 Harness Tool。

## 5. Sprint 2：结构化主张与案例素材提取

周期：第 4–5 周，约 12–18 人日。

### 5.1 目标

从证据中提取事实、指标、约束、决策、行动和结果，但不自动形成正式经验。

### 5.2 先实现

1. `LLMProvider` Protocol、Fake Provider 和一个真实模型 adapter。
2. 结构化 JSON 输出和有限重试。
3. 原子化 `Claim`、`MetricObservation` 和候选事件提取器。
4. Evidence allowlist 和引用校验。
5. 单位、日期、scope 和口径标准化。
6. Prompt、模型参数和运行配置版本化。
7. Token、耗时和费用统计。
8. 文档提示注入隔离。

### 5.3 实现顺序

```text
选择 EvidenceSpan allowlist
→ 构建版本化提取任务
→ LLM 结构化输出
→ Schema 校验
→ evidence_id 校验
→ 单位/日期/scope 规则检查
→ 保存候选 Claim
```

### 5.4 验收标准

- [ ] 100% 输出通过 Schema 或进入隔离队列。
- [ ] 每条候选 Claim 至少引用一个有效 `EvidenceSpan`。
- [ ] 无证据输出不能进入候选库。
- [ ] 派生指标包含公式和输入 Claim。
- [ ] 无法确认的信息标记为 `unknown`。
- [ ] Golden Set 上 FACT 准确率不低于 85%。
- [ ] 决策和结果提取 F1 不低于 70%。
- [ ] 模型超时、限流、损坏 JSON 可恢复且不会重复写入。

### 5.5 测试

- Mock LLM 合同测试；
- 真实模型 Golden 回归；
- JSON 损坏、字段缺失、幻觉 evidence ID；
- 提示注入、越权来源和敏感文本；
- 模型切换与 Prompt 版本兼容性。

### 5.6 本轮不做

- 正式 KnowledgeUnit；
- 自动发布；
- 图谱和复杂向量检索；
- Agent 自动调用。

## 6. Sprint 3：经验提纯 MVP

周期：第 6–7 周，约 15–20 人日。

### 6.1 目标

将零散主张组织为有上下文、有条件、有反例的可审核经验候选。这是首个真正的业务 MVP。

### 6.2 先实现

1. 时间截断 `ContextSnapshot`。
2. “背景—问题—决策—行动—结果—复盘” `CaseEpisode`。
3. `KnowledgeCandidate` 编译器。
4. 适用条件、排除条件、触发信号和失败模式。
5. 正向证据、反向证据和未知三态验证。
6. 同义候选聚类和初步冲突检测。
7. 分解式置信度依据。
8. 可供专家阅读的 JSON/Markdown/HTML 提纯报告。

### 6.3 关键业务规则

- 单一案例只能形成观察、先例或假设，不能自动表述为普遍规律。
- 缺少实际结果时，只能生成 `HYPOTHESIS` 或 `RECOMMENDATION`。
- 每条经验必须声明适用条件和排除条件；未知可明确写为“尚未确认”。
- 每条经验主动搜索反例；未找到时必须记录检索范围。
- 置信度保存来源质量、独立性、案例支持、结果观察、时效、冲突和审核依据。

### 6.4 验收标准

每条候选必须包含：

- [ ] 单一、明确的经验陈述；
- [ ] 适用条件；
- [ ] 排除条件或“尚未发现”；
- [ ] 至少一个来源项目；
- [ ] 支撑证据；
- [ ] 支持案例和反例状态；
- [ ] 置信度组成；
- [ ] 事实、推断、假设或建议分类；
- [ ] 模型、Prompt 和编译运行版本。

质量门：

- [ ] unsupported claim 比例低于 10%，目标低于 5%。
- [ ] Golden Set 关键经验召回率达到 70%，目标 75%。
- [ ] 未来数据泄漏为 0。
- [ ] 单案例错误泛化为 0。
- [ ] 至少 5–10 个案例产生 10–30 条可审核候选。

### 6.5 MVP 演示

```text
标准化项目资料
→ 可打开的 EvidenceSpan
→ Claim / Metric
→ CaseEpisode
→ KnowledgeCandidate
→ 带原文证据的提纯报告
```

演示不启动 Hoosland Agent，也不加载任何 Skill。

### 6.6 停止条件

如果领域专家认为候选经验相比直接阅读案例没有提高复用效率，停止增加模型和图算法，优先调整 `KnowledgeCandidate` 粒度、适用条件和案例结构。

## 7. Sprint 4：审核、发布与版本治理

周期：第 8–9 周，约 12–18 人日。

### 7.1 目标

把模型生成结果变成经过治理、可发布和可回滚的组织资产。

### 7.2 先实现

1. 审核队列和状态机。
2. 批准、修改、退回、拒绝和发布。
3. 不可变 `KnowledgeUnitVersion`。
4. `KnowledgeSnapshot` 和 manifest hash。
5. 审核、版本差异和追加式审计。
6. 知识挑战、替代和退役。
7. PostgreSQL 迁移和事务 outbox。
8. 最小审核 API 或管理界面。

### 7.3 验收标准

- [ ] 未经审核的候选无法进入正式快照。
- [ ] 已发布知识版本不可直接覆盖。
- [ ] 任意正式知识可恢复模型、Prompt、流水线、案例和原始证据。
- [ ] 审核人员的修改、意见和决定全部留痕。
- [ ] 快照重复导出得到相同 manifest hash。
- [ ] 发布失败不会出现“知识已发布但审计或索引任务缺失”的半状态。
- [ ] 可以切换旧快照完成回滚。

### 7.4 测试

- 状态机和非法跳转；
- 并发审核和乐观锁；
- 发布事务、outbox 和故障注入；
- 版本 diff、快照重放和回滚；
- 未授权审核、发布和读取。

## 8. Sprint 5：新项目匹配与比较服务

周期：第 10–11 周，约 15–22 人日。

### 8.1 目标

让已发布经验成为新项目的判断依据，同时明确展示为什么适用、为什么不适用和还缺什么资料。

### 8.2 先实现

1. `ProjectProfile` 和输入完整度。
2. 权限、快照、项目类型、阶段、地区和时间硬过滤。
3. 结构化、FTS 和知识单元级向量混合召回。
4. 三值适用性判断。
5. 相似点、差异点、风险、反例、冲突和未知信息。
6. Token 预算受控的 `KnowledgePacket`。
7. 匹配解释和证据回跳。
8. 新项目缺少信息时生成待补字段，而不是强行判断。

### 8.3 验收标准

- [ ] 每项风险、判断依据和建议检查都能回到 KnowledgeUnit 和证据。
- [ ] 输出明确区分“经验支持”“模型推断”“信息不足”。
- [ ] 必须召回经验的 `Recall@K` 达到 80%。
- [ ] 必须召回反例的命中率达到 85%。
- [ ] 硬条件失败的知识不会因向量相似度进入适用列表。
- [ ] 固定项目输入、快照和配置时，核心匹配结果可复现。
- [ ] 原始 RAG Chunk 不能绕过正式知识单元生成经验性结论。

### 8.4 本轮产物

```text
matched_experiences
applicable_experiences
partially_applicable_experiences
non_applicable_experiences
conflicting_experiences
similarities / differences
risk_signals
missing_information
recommended_checks
knowledge_snapshot_id
evidence_refs
```

本阶段结束形成独立知识提纯库内部 Beta。

## 9. Sprint 6：跨项目归纳与图谱投影

周期：第 12–13 周，约 15–22 人日。

### 9.1 目标

在已有稳定语义上支持多案例关系、冲突簇和可解释路径，而不是重新发明事实源。

### 9.2 先实现

- 项目、案例事件、Claim、知识、条件和证据关系边表；
- 实体消歧和人工确认；
- 跨项目 `SUPPORTS / CONTRADICTS / APPLIES_TO / EXCLUDED_BY`；
- 多案例支持度和反例覆盖；
- 冲突簇和可能的范围/时间差异；
- 知识失效信号；
- 可选 AGE 或其他图引擎投影。

### 9.3 验收标准

- [ ] 图谱可从正式快照完整重建。
- [ ] 每条边具有来源、推断类型和版本。
- [ ] 单项目观察与跨项目规律严格区分。
- [ ] 支持案例、反例和未解决冲突可同时展示。
- [ ] 删除图投影后可以从 PostgreSQL 恢复。
- [ ] 实体歧义不会被静默合并。

### 9.4 停止条件

如果 edge table 已满足查询，不引入新的图数据库。只有多跳查询、关系解释或性能出现明确瓶颈时才增加 AGE/Neo4j 等实现。

## 10. Sprint 7：生产化加固

周期：第 14–17 周，约 20–30 人日。

### 10.1 目标

达到可长期运行、可治理、可审计、可恢复的生产候选标准。

### 10.2 先实现

1. 持久 Job Queue、心跳、重试、取消、dead-letter 和恢复。
2. 多租户、项目权限、RBAC 和查询前权限过滤。
3. 密钥管理、数据分级、加密和备份。
4. PII 检测或脱敏策略。
5. 模型限流、超时、重试、熔断和费用预算。
6. 指标、追踪、告警和审计查询。
7. 容器化、迁移、备份恢复和索引重建。
8. Golden 回归门和模型/Prompt 升级阻断。
9. 性能、容量和稳定性基线。

### 10.3 验收标准

- [ ] 服务重启后任务可恢复，不重复发布。
- [ ] 真实备份恢复演练成功。
- [ ] 跨租户和跨项目越权测试为 0 泄漏。
- [ ] Provider 不可用时任务进入可恢复状态。
- [ ] Prompt、模型或 Schema 升级未通过 Golden Gate 时不能发布。
- [ ] 所有生产查询都返回知识快照。
- [ ] 结构化知识查询 p95 目标小于 500ms。
- [ ] 不含 LLM 的项目匹配 p95 目标小于 2s。
- [ ] 生产日志不包含资料正文、完整 Prompt、完整模型输出或密钥。
- [ ] 路径穿越、SSRF、提示注入和恶意文件测试通过。

### 10.4 生产候选放行门

- P0 安全和数据一致性问题全部关闭；
- P1 问题有明确责任人与计划；
- 数据迁移可回滚；
- 活跃快照可原子切换；
- 评测报告和已知限制被批准；
- 领域专家确认知识使用边界。

## 11. Sprint 8：DeepSeek Harness 适配与灰度

周期：第 16–19 周，可在生产加固后半段开始，约 8–15 人日。

### 11.1 启动前置条件

只有同时满足以下条件才启动：

- 核心 MVP 和内部 Beta 已通过；
- 管理写接口与生产只读接口已经分离；
- `KnowledgeSnapshot` 可复现；
- 查询和适用性指标达到 Sprint 5 基线；
- 可以独立关闭所有 Agent 接入而不影响知识服务。

### 11.2 先实现

1. 只读 Knowledge MCP Adapter。
2. 四个最小 Tool：`search`、`match_project`、`get_unit`、`get_evidence`。
3. 一个知识消费 SkillContract。
4. 手动 `/kb_compare` 或等价触发入口。
5. Feature Flag、超时、熔断和调用审计。
6. KnowledgePacket 的 Token 预算和字段裁剪。
7. Harness—MCP—知识服务合同测试。

### 11.3 明确禁止

- 不把 `refine`、`review`、`publish` 注册为自动 Agent Tool。
- 不让 Agent 直接连接 PostgreSQL 或对象存储。
- 不把 `KnowledgeUnit` 转成大量动态 Skill。
- 不把领域事务或审核逻辑写进 MCP/Cordis adapter。
- 不因接入方便修改核心领域 Schema。

### 11.4 灰度顺序

1. 开发环境直接调用只读 API。
2. MCP 合同测试和手动 Tool 调用。
3. 内部用户使用 `/kb_compare`，不自动路由。
4. Agent 建议使用知识，但不改变正式输出，运行 `shadow`。
5. 允许影响内部分析，人工确认报告，运行 `warn`。
6. 只有历史回放和真实试点达标后，才评估有限 `strict`。

### 11.5 验收标准

- [ ] 删除 MCP adapter 后核心服务仍可完整运行。
- [ ] 核心包不存在 Harness import。
- [ ] Agent 无法调用管理写接口。
- [ ] 每个知识性结论携带知识版本 ID、快照 ID 和证据。
- [ ] Adapter 失败时主 Agent 可降级到 Skill-only，并明确告知知识层不可用。
- [ ] 关闭自动路由后可以仅保留手动触发。
- [ ] 灰度期准确率、反例召回和延迟不低于独立服务基线。

## 12. 贯穿全程的并行工作流

### 12.1 历史数据工作流

每周持续推进：

```text
资料盘点
→ 权限确认
→ 项目/范围/日期标注
→ 决策/动作/结果补齐
→ 案例完整度评分
→ Golden Set
```

工程迭代不得等待“将来会有数据”。每个 Sprint 计划必须明确本轮使用的真实案例和缺失项。

### 12.2 Golden Set 工作流

Golden Set 至少包括：

- 原文 locator；
- 应抽取和不应抽取的 Claim；
- 正确主张类型；
- 决策截止时间；
- CaseEpisode；
- 应生成和不应生成的经验；
- 必须召回的支持案例、反例和冲突知识；
- 新项目适用、部分适用、不适用和未知用例。

每次 Schema、Prompt、模型、解析器和规则变化都运行回归。

### 12.3 专家审核工作流

- 每周固定审核时段，不以临时请求代替。
- 记录审核耗时、退回原因和字段修改距离。
- 重复错误转化为 Schema、规则或 Prompt 改进。
- 高风险知识可要求双人审核；普通候选保持单人审核和抽检。
- 审核通过率不是越高越好，关键是拒绝理由可转化为改进。

## 13. 敏捷运行机制

### 13.1 每周节奏

| 时间 | 活动 |
|---|---|
| 周一 | Sprint 目标、真实案例和风险确认 |
| 周二至周四 | 开发、标注、审核和自动化 |
| 周四 | Golden 回归和失败分类 |
| 周五 | 用真实资料演示、专家验收、复盘和下周取舍 |

每两周形成一个可标记版本；不能只演示 Mock 数据或静态页面。

### 13.2 WIP 限制

- 同时在开发的主能力不超过 2 个。
- 未通过证据定位，不并行扩展更多解析格式。
- 未通过候选质量门，不并行开发复杂图谱。
- 未通过独立 Beta，不并行接入多个 Skill。

### 13.3 Story Definition of Ready

- 业务问题和用户明确；
- 输入、输出、状态和错误可描述；
- 对应真实案例和 Golden Fixture 已准备；
- 权限、时间、范围和证据要求已确认；
- 验收指标和回滚方式可测试；
- 不依赖未批准的 Harness 接入假设。

### 13.4 Story Definition of Done

- 功能代码、迁移和回滚完成；
- 单元、架构、合同、Golden 和集成测试通过；
- 模型输出通过 Schema 和证据校验；
- Prompt、模型、规则和配置有版本；
- 日志不泄露正文；
- 真实资料演示通过；
- API、Schema、CHANGELOG 和已知限制更新；
- 核心零 Harness 依赖仍由自动测试保证。

## 14. 前 30 天具体安排

### 第 1 周

- 确定首个决策域和 5–10 个案例；
- 完成资料权限和结果完整度盘点；
- 建立独立 package、领域 Schema 和依赖边界测试；
- 建立 Golden Set 模板和前 20 条标注。

### 第 2 周

- 完成 `ParsedDocument`、DocumentVersion 和 EvidenceSpan；
- 支持 Markdown/JSON fixture；
- 实现内容哈希、稳定 ID 和 locator；
- 选择 Docling 或 X2Knowledge 作为一个解析 adapter PoC。

### 第 3 周

- 完成幂等导入、失败重试和证据回跳；
- 用 3–5 份真实资料建立 locator Golden Set；
- 修复解析质量，不增加更多格式。

### 第 4 周

- 实现 LLMProvider、Fake Provider 和结构化提取；
- 完成 Claim、Metric、scope、日期和单位校验；
- 开始 FACT、Decision、Outcome Golden 回归。

30 天结束时应得到可信的证据底座和首批结构化案例素材，而不是知识图谱大屏或 Agent Demo。

## 15. 阶段停止与转向条件

| 检查点 | 停止或转向条件 |
|---|---|
| Sprint 0 后 | 没有合法资料或没有领域专家时，暂停自动提纯，先解决数据治理 |
| Sprint 1 后 | locator 准确率不达标时，停止扩格式，优先修复证据定位 |
| Sprint 2 后 | 悬空引用或主张误分类不可控时，不进入经验编译 |
| Sprint 3 后 | 候选经验不比案例摘要更有复用价值时，重做知识契约 |
| Sprint 5 后 | 完整方案相对 Skill-only/RAG 没有可测增益时，不接 Harness |
| Sprint 7 后 | 存在越权、不可恢复不一致或无法回滚时，不进入试点 |
| Sprint 8 灰度 | 错误适用、反例遗漏或延迟显著回退时，恢复手动触发或 Skill-only |

## 16. 延期时的裁剪顺序

按以下顺序后移：

1. 图谱可视化美化；
2. 专用图数据库和复杂图算法；
3. Obsidian 实时双向同步；
4. PPT 和复杂图表视觉理解；
5. 第二个及后续 Skill；
6. 自动业务系统同步；
7. 高级运营看板；
8. 独立消息队列集群。

不得裁掉：

- 来源版本和 SHA-256；
- `EvidenceSpan` 和 locator；
- scope、日期、单位、来源和截止时间；
- 时间截断 `ProjectCase`；
- 适用条件、排除条件和反例；
- 人工审核与不可变知识版本；
- `KnowledgeSnapshot`；
- 权限、审计、回滚和 Golden 回归。

## 17. 主要风险与控制

| 风险 | 后果 | 控制 |
|---|---|---|
| 历史项目没有实际结果 | 无法形成可靠经验 | 完整度盘点；缺失结果只生成假设 |
| 模型输出看似合理但无依据 | 将幻觉固化为知识 | Evidence allowlist、引用校验和人工发布 |
| 单案例被泛化 | 新项目错误迁移 | 知识类型约束、跨案例支持和反例 |
| 不同项目口径不可比 | 错误阈值和结论 | scope、日期、单位、分母和方法标准化 |
| 审核成为瓶颈 | 候选积压 | 风险排序、聚类去重、固定审核时段 |
| 图谱过早复杂化 | 延期且语义不稳 | PostgreSQL 权威源，edge table 先行 |
| 项目退化为普通 RAG | 无法形成护城河 | 只将已发布 KnowledgeUnit 用于经验判断 |
| Harness 绑定过深 | 核心不可复用 | 独立 package、架构测试、只读 MCP 薄适配 |
| 文档提示注入 | 模型被资料中的指令操控 | 文档作为不可信数据，提纯调用禁用工具 |
| 数据泄漏 | 严重安全事故 | 查询前权限过滤、正文不入日志、数据分级 |
| 模型升级漂移 | 知识质量回退 | Prompt/模型版本和 Golden Gate |
| X2Knowledge 直接上线 | 路径写入、SSRF 或同步阻塞风险 | 仅隔离 adapter；补安全、超时和资源限制 |

## 18. 交付物清单

### Core MVP

- [ ] 独立 Python package 和 CLI；
- [ ] canonical Schema 和 JSON Schema；
- [ ] DocumentVersion / EvidenceSpan；
- [ ] Claim / Metric / ProjectCase / CaseEpisode；
- [ ] KnowledgeCandidate 编译器；
- [ ] 机器质量闸门；
- [ ] JSON/Markdown/HTML 提纯报告；
- [ ] Golden Set 和基线报告；
- [ ] 架构、合同和安全测试。

### Internal Beta

- [ ] PostgreSQL 和迁移；
- [ ] 审核队列和不可变 KnowledgeUnitVersion；
- [ ] KnowledgeSnapshot 和回滚；
- [ ] 混合检索和三值适用性；
- [ ] 新项目差异、反例、冲突和未知输出；
- [ ] 最小审核和证据查看界面。

### Production Candidate

- [ ] 多租户/RBAC；
- [ ] 持久任务、恢复和 dead-letter；
- [ ] 备份恢复和索引重建；
- [ ] 监控、告警、预算和熔断；
- [ ] 安全和负载测试；
- [ ] Golden 回归发布门；
- [ ] 生产运行手册和回滚手册。

### Harness Integration

- [ ] 独立只读 MCP Adapter；
- [ ] 四个最小 Tool；
- [ ] 一个 SkillContract；
- [ ] `/kb_compare` 手动入口；
- [ ] shadow/warn 指标；
- [ ] 一键关闭和 Skill-only 降级。

## 19. 下一批开工产物

开始 Sprint 0 前，应建立以下执行文件：

1. `KNOWLEDGE-DOMAIN-DATA-DICTIONARY.md`：首个决策域字段、单位和枚举。
2. `KNOWLEDGE-SCHEMA-V0.1.md`：实体、关系、Schema 和状态机。
3. `PARSED-DOCUMENT-CONTRACT-V0.1.md`：解析器 canonical 输出。
4. `EVAL-GOLDEN-SET-SPEC.md`：标注格式、评分和回归门。
5. `SPRINT-0-BACKLOG.md`：Story、责任人、工时和验收。
6. `CORE-DEPENDENCY-BOUNDARY-ADR.md`：核心包单向依赖。

真正的首要验收指标不是导入了多少文件或生成了多少向量，而是：

> 对一项新项目判断，系统能否明确说明使用了哪条正式经验、经验来自哪些历史案例、原始证据在哪里、适用条件和反例是什么，以及还有哪些条件未知。

