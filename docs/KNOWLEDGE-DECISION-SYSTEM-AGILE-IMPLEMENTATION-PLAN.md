# Hoosland 知识决策系统分部实施与敏捷迭代方案

文档状态：`Draft`  
文档版本：`0.2.0`  
编写日期：`2026-08-26`  
配套文档：[项目经验知识图谱与专业决策引擎开发文档](KNOWLEDGE-DECISION-SYSTEM-DEVELOPMENT.md)  
架构决策：[ADR-0005：Harness 插件、Skill 与知识层边界](adr/0005-harness-plugin-and-knowledge-boundaries.md)  
核心库详细计划：[独立知识提纯库开发步骤与敏捷实施计划](KNOWLEDGE-REFINERY-CORE-IMPLEMENTATION-PLAN.md)  
建议节拍：每周演示、每两周形成可发布增量  
目标里程碑：第 7 周提纯核心 MVP、第 11 周独立 Beta、第 15–17 周生产候选、第 28 周完整系统试点  

## 0. 实施结论

本项目必须按纵向闭环逐步实现，不能先做一个“大而全的知识图谱”，再等待未来接入业务。

本文件描述完整知识决策系统的上位节奏；知识提纯核心的 Sprint、验收指标和 Harness 接入前置条件，以[独立核心实施计划](KNOWLEDGE-REFINERY-CORE-IMPLEMENTATION-PLAN.md)为准。核心先作为零 Harness 依赖的独立 package、CLI、API 和 Worker 交付，达到内部 Beta 后才进入本计划的 Skill/Harness 集成阶段。

正确顺序是：

```text
先把原文变成可定位证据
→ 再把证据变成结构化项目案例
→ 再把多个案例提纯为候选知识
→ 再建立专家审核与知识版本
→ 再按新项目条件选择知识
→ 再让一个 Skill 消费知识
→ 再增加图谱、向量和更多 Skill
→ 最后开启严格核验、结果回灌和生产能力
```

第一批功能应当是**资料版本、EvidenceSpan 和人工可校正的 ProjectCase**，不是图谱大屏，也不是自动总结全部历史资料。只有证据定位和案例数据可信，后续 KnowledgeUnit 和 Skill 判断才有意义。

## 1. 迭代策略

### 1.1 纵向切片

每个迭代必须交付一条可演示的小闭环：

```text
独立 use case 或用户操作
→ Python API / CLI / Service API
→ 持久化
→ 处理或判断
→ 结构化结果或页面
→ 审计记录
→ 自动化测试
```

只完成数据库表、只完成 Prompt 或只完成前端静态页面，都不算一个可验收增量。

### 1.2 手工先行，自动化后置

知识提纯早期允许人工校正和审核：

1. 先证明数据结构能表达真实项目；
2. 再证明知识对新项目判断有增益；
3. 最后提高自动抽取和批量编译比例。

如果一开始就追求全自动，错误会在实体、范围、证据和知识四个层面叠加，无法判断问题发生在哪里。

### 1.3 关系表先行，图谱投影后置

PoC 先用 PostgreSQL 关系表和 JSON 条件表达式实现完整语义。等 ProjectCase、KnowledgeUnit 和关系类型稳定后，再投影到 Apache AGE。

图谱用于关系查询和解释，不成为关键数值、权限或审核状态的唯一事实源。

### 1.4 一个决策域先跑通

首期建议锁定：

```text
住宅项目的产品组合与首开策略
```

核心内部 Beta 通过后，首个接入 Skill 使用 `real-estate-product-strategy`；再接入 `real-estate-research`。编辑、设计、PDF、营销和社交发布 Skill 暂时只消费最终审定结论，不进入首期知识本体。

### 1.5 功能开关

新能力必须位于 Feature Flag 后，但结构校验、知识发布和知识对决策的影响要分开控制：

```text
KNOWLEDGE_CAPABILITY_ENABLED=false | true
KNOWLEDGE_STRUCTURAL_VALIDATION=shadow | strict
KNOWLEDGE_PUBLICATION_POLICY=human_approval_only
KNOWLEDGE_DECISION_MODE=off | shadow | warn | strict
```

任何阶段都可以关闭知识链路，恢复现有工作台行为，而不删除原始资料和知识记录。

- scope、权限、单位、来源、公式和时间泄漏等确定性结构校验，在对应功能稳定后尽早进入 `strict`；
- 候选 KnowledgeUnit 从第一天起就必须人工批准；
- 知识是否影响正式判断，才按照 `shadow → warn → strict` 渐进放行。

### 1.6 Harness 插件化策略

本项目基于 DeepSeek Harness，但不把所有业务状态都塞进 Cordis 插件：

| 部分 | 实现形态 |
|---|---|
| Agent Loop、LLM、Tool、Session | DeepSeek Harness / Cordis 控制层 |
| 总控和专业方法 | 可插拔 Harness Skill resources |
| 知识查询和案例比对入口 | MCP Tool 或薄 Cordis plugin |
| 资料、案例、KnowledgeUnit、审核、版本、权限、评测 | 固定的 Hoosland Knowledge Service |
| 快照、结构校验、发布 Gate 和终态 | 固定的 Application 状态机 |

核心 PoC 不注册任何 Harness Tool。独立 Beta 通过后，优先通过当前 `@deepseek-ai/dsh-mcp-client` 和内部 MCP Gateway 暴露只读知识 Tool；只有后续确实需要监听 `agent/*`、`tools/*`、注入 scoped context 或提供 Harness 原生 UI 时，才开发薄 Cordis plugin。

KnowledgeUnit 是数据库数据，不是动态 Skill。专业 Skill 可替换，但 Skill 只能通过稳定 `SkillContract` 消费已发布知识。

## 2. 先后顺序总览

| 顺序 | 先实现的功能 | 为什么先做 | 暂时不做 |
|---:|---|---|---|
| 1 | 决策域、ID、Schema、案例清单 | 没有统一口径，后续数据无法比较 | 大而全本体 |
| 2 | 项目资料库、文件哈希和版本 | 先建立可信资料身份 | 全格式解析 |
| 3 | PDF/Markdown/CSV 的 EvidenceSpan | 先保证结论能回到原文 | 自动知识总结 |
| 4 | Claim、Metric、Scope 人工校正 | 先得到可信的结构化事实 | 完全自动抽取 |
| 5 | 时间截断 ProjectCase | 先形成可比较案例 | 跨项目规律自动发布 |
| 6 | 候选 KnowledgeUnit + 专家发布 | 建立 RAG 与 Skill 之间的知识层 | 复杂图谱算法 |
| 7 | 硬条件匹配 + 一个 Skill | 尽早验证业务价值 | 一次接入全部 Skill |
| 8 | 异步入库、更多格式和审核 UI | 扩大可用数据量 | 多租户和大规模扩容 |
| 9 | AGE/FTS/pgvector 混合检索 | 在已有语义上提高召回和解释 | 用向量替代条件判断 |
| 10 | Claim 核验与历史回放 | 证明系统比现有方案更可靠 | 立即开启 strict |
| 11 | 决策、动作、结果回灌 | 形成经验更新闭环 | 直接对接全部业务系统 |
| 12 | 权限、恢复、监控和试点 | 达到生产放行条件 | 未验证就全面上线 |

## 3. 里程碑与版本节奏

```mermaid
flowchart LR
  I0[I0 基线] --> I1[I1 资料身份]
  I1 --> I2[I2 证据定位]
  I2 --> I3[I3 事实标准化]
  I3 --> I4[I4 项目案例]
  I4 --> I5[I5 独立知识 PoC]
  I5 --> POC[核心技术 PoC]
  POC --> I6[I6 入库增强]
  I6 --> I7[I7 审核与版本]
  I7 --> I8[I8 混合匹配 + 两个 Skill]
  I8 --> I9[I9 核验与评测]
  I9 --> I10[I10 数据扩展与 MVP]
  I10 --> MVP[内部 MVP]
  MVP --> I11[I11 权限安全]
  I11 --> I12[I12 任务与恢复]
  I12 --> I13[I13 反馈闭环]
  I13 --> I14[I14 受控试点]
  I14 --> I15[I15 严格放行]
  I15 --> PILOT[生产试点]
```

| 里程碑 | 时间 | 定义 |
|---|---:|---|
| 核心技术 PoC | 第 6 周 | 5–10 个案例、3–5 个已发布 KnowledgeUnit，独立 CLI/API 完成可追溯匹配；不接 Harness |
| 内部 MVP | 第 17 周 | 20–30 个案例、两个核心 Skill、审核与版本、混合检索、历史回放和 warn 核验 |
| 生产试点 | 第 28 周 | 权限、持久任务、恢复、监控、真实项目试点和部分 deterministic strict 门 |

PoC 只证明技术和业务流程成立，不证明跨项目规律已达到统计可靠性。

## 4. PoC：第 1–6 周

### I0：基线与最小骨架——第 1 周

**迭代目标**

让团队对“解决哪个判断问题、使用哪些案例、数据如何命名”达成一致，并让新知识模块可以安全启动和关闭。

**先实现**

1. 收敛 canonical source、Build、Skill 和 Schema 基线；
2. 确定首个决策问题：产品组合与首开策略；
3. 选定 5–10 个 PoC 历史项目，标记资料与结果完整度；
4. 建立 Project、Scope、Document、Claim、Metric、ProjectCase、KnowledgeUnit 的 ID 规范；
5. 建立 PostgreSQL 开发环境和第一版迁移；
6. 新增 Knowledge Layer Feature Flag；
7. 固定本项目 `cordis.yml` composition、Harness 版本和知识 Tool 扩展契约；
8. 新增 `/api/health/ready` 中的知识层状态，但关闭时不影响现有工作台 Ready。

**本轮演示**

- 应用在 `off` 和 `shadow` 间切换；
- 数据库迁移可升级和回滚；
- 创建一个空 ProjectCase；
- 页面或管理接口能显示知识层未启用/可用状态。

**本轮不做**

- 文件解析；
- 图数据库；
- embedding；
- 自动提纯；
- 新项目结论。

**退出条件**

- 首个决策域有书面边界；
- 至少 5 个项目具备可合法使用的资料；
- 数据字典和 ID 规范通过技术与领域专家共同评审；
- 数据库迁移和 Feature Flag 测试通过。

### I1：项目资料库与文档版本——第 2 周

**迭代目标**

建立项目级资料身份，让历史资料不再只属于某个 conversation。

**先实现**

1. `KnowledgeBase / Document / DocumentVersion`；
2. 上传或从现有 conversation 复制资料到项目资料库；
3. SHA-256 去重、版本号、来源主体、来源等级和权限字段；
4. 资料列表、版本列表和处理状态；
5. “加入项目资料库”必须由用户显式触发；
6. 最小 Markdown Frontmatter 导入，允许 Obsidian/SiYuan 导出的标准笔记入库。

**本轮演示**

- 同一文件重复上传不会产生重复内容版本；
- 更新文件产生新版本，旧版本仍可打开；
- conversation 附件可选择性加入项目资料库；
- 一篇标准 Markdown 笔记保留来源和项目元数据。

**本轮不做**

- 自动双链转正式图谱关系；
- Office 和扫描件深度解析；
- 自动永久收录所有历史附件。

**退出条件**

- 原始版本不可原地覆盖；
- 文件越权、符号链接逃逸和重复上传测试通过；
- 所有文档具备稳定 `document_id / document_version_id / sha256`。

### I2：证据定位闭环——第 3 周

**迭代目标**

让系统能够从结构化结果回到真实原文，而不是只有无法核验的摘要。

**先实现**

1. PDF、Markdown、CSV 三类解析；
2. `EvidenceSpan` 和 locator；
3. PDF 页码、Markdown 标题/段落、CSV 行列定位；
4. 原文与抽取文本对照页面；
5. 简单异步 Job 状态和失败重试；
6. 解析器版本、文本哈希和重建入口。

**本轮演示**

- 从一个 EvidenceSpan 点击打开对应 PDF 页、Markdown 段落或 CSV 行；
- 删除派生结果后可以从原文件重建；
- 失败任务可安全重试，不产生重复 span。

**本轮不做**

- OCR；
- DOCX/XLSX；
- 图表视觉理解；
- embedding 和图谱。

**退出条件**

- EvidenceSpan 可打开率 100%；
- PoC 样本 locator 人工准确率达到 90% 目标；
- 解析失败不会把文档标记为 ready；
- 原始文件和派生数据边界清晰。

### I3：事实、指标与范围标准化——第 4 周

**迭代目标**

把可定位证据转化为可人工校正的 Claim、Metric 和 Scope。

**先实现**

1. `FACT / DERIVED / INFERENCE / HYPOTHESIS / RECOMMENDATION` Claim；
2. Claim 与一个或多个 EvidenceSpan 绑定；
3. Metric 的值、单位、币种、分母、观察期和统计口径；
4. Scope 父子层级和 `scope_id` 校验；
5. LLM 辅助抽取候选，默认状态为 `candidate`；
6. 人工编辑、批准、争议和驳回；
7. 确定性单位、日期和范围校验；
8. 对已经稳定的 scope、权限、单位和来源存在性校验启用结构性 `strict`。

**本轮演示**

- 从一份项目资料抽取 10–20 条候选 Claim；
- 专家修正数值或范围后保留修改记录；
- 点击 Claim 能打开所有支持或反驳证据；
- 范围、单位或来源缺失时不能批准关键事实。

**本轮不做**

- 自动把 Claim 变成跨项目经验；
- 由 LLM 直接批准事实；
- 复杂实体自动合并。

**退出条件**

- 关键数字范围、单位和来源错误为 0；
- `FACT` 没有证据时不能进入 verified；
- 冲突来源并列保存，不静默覆盖。

### I4：时间截断 ProjectCase——第 5 周

**迭代目标**

把单份资料的事实组织为可比较的项目决策案例。

**先实现**

1. `ProjectCase / ContextSnapshot`；
2. 决策时点 `decision_time` 和允许使用的资料快照；
3. 决策问题、事实、假设、约束和缺失项；
4. `DecisionRecord / Action / OutcomeObservation` 的人工录入；
5. 未来资料黑名单和时间泄漏检查；
6. 同一项目多个阶段生成不同案例快照。

**本轮演示**

- 将一个项目拆成定位时点和在售复盘时点两个 ProjectCase；
- 在定位案例中看不到后续成交结果；
- 显示“当时判断—实际动作—后续结果”的链路；
- 缺少动作或结果的案例被标记为“不足以支持经验”。

**本轮不做**

- 自动因果推断；
- 自动连接销售、财务或 CRM；
- 跨项目知识自动发布。

**退出条件**

- 至少 5 个 ProjectCase 结构完整；
- 时间泄漏测试为 0；
- 每个案例明确哪些字段未知；
- 领域专家确认结构能表达真实业务过程。

### I5：候选知识、审核与独立查询 PoC——第 6 周

**迭代目标**

打通“历史案例 → 候选知识 → 专家发布 → 新项目匹配 → 证据化输出”的首条独立闭环。

**先实现**

1. `KnowledgeUnit / KnowledgeUnitVersion`；
2. `heuristic / calculation_rule / anti_pattern` 三种知识类型；
3. 结构化适用条件和 `true / false / unknown` 三值判断；
4. 支持案例、反例、有效期和置信度；
5. `candidate → expert_review → published / rejected` 最小状态机；
6. SQL/JSON 硬条件匹配，不依赖图数据库；
7. Python use case `find_applicable` 和最小 `KnowledgePacket`；
8. 独立 CLI 或 Standalone API；
9. 架构测试确认核心零 Harness/MCP 依赖；
10. 输出匹配结果显示 KnowledgeUnit、支持案例、反例和原始证据。

**本轮演示**

- 专家从 5–10 个案例中批准 3–5 个 KnowledgeUnit；
- 为一个新项目建立 ContextSnapshot；
- 系统解释哪些知识适用、哪些不适用、哪些条件未知；
- 独立 CLI/API 完成一份带证据和条件边界的匹配报告；
- 不启动 Hoosland Agent 也能重复运行和复现结果。

**本轮不做**

- 全自动知识编译；
- AGE 和向量检索；
- MCP、Harness 和 Skill 接入；
- 自定义重量级 Cordis plugin；
- strict 核验；
- 以 PoC 结果对外声称知识已经统计有效。

**PoC 放行条件**

- 首条纵向闭环可重复演示；
- 关键结论 100% 可追溯；
- 候选知识未经专家批准不能进入生产查询快照；
- 不适用和未知条件不会被相似度绕过；
- 不出现未来资料泄漏、伪造来源或关键数字错误；
- 领域专家确认 KnowledgeUnit 比直接阅读原始 Chunk 更适合复用经验。

## 5. 内部 MVP：第 7–17 周

### I6：入库工程化与更多格式——第 7–8 周

**先实现**

1. PostgreSQL Job Table、心跳、超时、dead-letter 和 orphan 恢复；
2. transactional outbox；
3. DOCX、XLSX、HTML、TXT；
4. XLSX 工作表和单元格 locator；
5. 扫描 PDF 的 OCR 降级路径；
6. 解析质量分和低质量人工复核队列；
7. 索引清除与重建命令。

**演示与验收**

- 服务重启后未完成任务可以恢复；
- 同一幂等键不会重复生成资料版本；
- XLSX 结论能回到工作表和单元格；
- 低质量 OCR 不自动进入 verified Claim。

**后置**

- PPT 深度解析；
- 图表自动语义理解；
- 专用分布式消息队列。

### I7：知识编译器与完整审核——第 9–10 周

**先实现**

1. `CompilationRun`，冻结输入案例、模型、Prompt、规则和版本；
2. 跨案例候选模式生成；
3. 主动搜索支持案例和反例；
4. `triaged / evidence_ready / approved_with_limits / challenged / superseded / retired`；
5. 审核理由、专家分歧、条件修改和版本 diff；
6. 高风险知识双人审核；
7. 到期和失效信号进入复审队列；
8. 第一版 AGE 图谱投影，只投影已稳定的实体和关系。

**演示与验收**

- 同一 CompilationRun 可重放；
- 已发布 KnowledgeUnit 不能原地修改；
- 反例是一级对象并影响审核；
- retired/superseded 知识不进入默认激活；
- 删除 AGE 投影后能从关系表重建。

### I8：混合匹配、案例差异与首批两个 Skill——第 11–12 周

**先实现**

1. 硬条件过滤；
2. SQL 数值和时间窗口比较；
3. AGE 关系路径查询；
4. PostgreSQL FTS + pgvector 候选召回；
5. 支持案例、严重反例和差异矩阵；
6. KnowledgePacket 稳定 Schema；
7. 接入 `real-estate-research`；
8. `real-estate-research → real-estate-product-strategy` 结构化交接；
9. 最小项目经验图谱和案例对比页面。

**演示与验收**

- 相似度只能影响候选排序，不能覆盖硬条件失败；
- 新项目能看到最重要的 5 个相同点和 5 个差异点；
- 同时返回支持案例和反例；
- 两个 Skill 使用同一知识快照，不各自重新检索；
- 每条结论保存所用 KnowledgeUnitVersion。

### I9：逐结论核验与历史回放——第 13–14 周

**先实现**

1. Skill 输出结构化 Claims；
2. `supported / partially_supported / unsupported / contradicted / stale / out_of_scope`；
3. 引用是否实际支持 Claim 的核验；
4. 数字、单位、范围、日期和公式确定性复算；
5. 最多一次受控修订；
6. `shadow → warn` 放行；
7. 时间截断历史回放；
8. LLM-only、RAG-only、Skill-only、完整方案四组对照框架。

**演示与验收**

- 核验失败不会继续显示为完全成功；
- `warn` 模式明确降低结论等级；
- 未来资料被回放器阻断；
- 关键数字错误、伪造来源和未授权资料访问均为 P0；
- 当前阶段仍不整体开启 semantic strict。

### I10：数据扩展、评测与 MVP 放行——第 15–17 周

**先实现**

1. 扩展到 20–30 个完整历史案例；
2. 30–50 个时间截断快照；
3. 100–200 个黄金问题；
4. 数据质量、知识适用、反例召回、专家同意和拒答指标；
5. 人工记录新分析的 Decision、Action 和 Outcome；
6. KnowledgeUnit 挑战和复审触发；
7. 检索、知识包构建和页面性能优化；
8. Schema 迁移、索引重建、回滚和 MVP 发布证据；
9. 内部用户操作说明和专家审核手册。

**MVP 放行条件**

- 两个核心 Skill 完成统一知识消费；
- 关键结论证据覆盖率达到批准门槛；
- scope、单位、日期和关键数字 P0 错误为 0；
- 适用知识和反例召回达到开发文档初始目标；
- 证据不足场景能正确降级或拒绝；
- 完整方案在盲评中优于现有最佳基线；
- 人工可以完成入库、审核、新项目分析、决策记录和结果复盘；
- 所有索引可重建，MVP 可回滚。

## 6. 生产试点：第 18–28 周

### I11：身份、权限和资料安全——第 18–19 周

**先实现**

1. 组织、用户、项目、知识库角色；
2. 服务端 tenant/project scope；
3. PostgreSQL RLS 或等效强制授权；
4. 原文、EvidenceSpan、KnowledgePacket 和输出的权限继承；
5. 外部模型可发送/仅本地/禁止模型处理三级策略；
6. 保留、删除、导出和审计规则；
7. 跨项目越权自动化测试。

**放行条件**

- 未授权跨项目读取为 0；
- 前端隐藏不能代替服务端授权；
- 权限变更有审计和回滚路径。

### I12：持久任务、扩容与恢复——第 20–21 周

**先实现**

1. API 与 ingestion/compiler worker 分进程；
2. 多 worker 任务竞争和幂等；
3. 数据库、原始文件和配置备份；
4. PITR 或批准的等效恢复方案；
5. 队列延迟、失败、重试、解析、检索和费用监控；
6. 容量、超时、取消和故障注入测试；
7. 明确试点 RPO/RTO。

**放行条件**

- 完成真实备份恢复演练；
- worker 中断后任务可恢复且不重复提交知识；
- 数据库权威状态与派生索引一致。

### I13：结果回灌与知识监测——第 22–23 周

**先实现**

1. Decision、Action、Outcome 的批量导入；
2. 结果观察窗口和干预因素；
3. `consistent_with / inconsistent_with / inconclusive`；
4. 命中失效信号后自动 challenge；
5. KnowledgeUnit 与 SkillRun 的校准指标；
6. 人工覆盖理由和后续结果关联；
7. 评测看板和版本回退告警。

**放行条件**

- 结果回灌不会自动声称因果；
- challenge 不会直接删除旧知识；
- 新版本知识可与旧版本做历史回放对比。

### I14：真实项目受控试点——第 24–25 周

**先实现**

1. 选择 2–3 个真实但受控项目；
2. `shadow` 和 `warn` 双轨运行；
3. 专家审核 SLA 和积压看板；
4. 错误分类、成本、延迟和用户操作反馈；
5. 修复 P0/P1、补充 Golden Case；
6. 灾备、权限和回滚演练。

**放行条件**

- 试点期间 P0 为 0；
- 所有 P1 有责任人和关闭证据；
- 未通过的语义核验仍保持 warn，不得为了上线强开 strict。

### I15：选择性 strict 与生产试点放行——第 26–28 周

**先实现**

1. 复核并扩大已在早期启用的结构性 strict：权限、来源存在、时间泄漏、scope、单位和公式；
2. 对达到精确率门槛的引用核验逐项开启 strict；
3. 只对批准决策域和已发布知识开启选择性 decision strict；
4. 新 Skill、新知识类型和新领域仍从 shadow 重新开始；
5. 负载、长任务、容量、费用和模型漂移测试；
6. 不可变 release、迁移、回滚和观察期；
7. 生产运行手册、知识治理手册和事件响应手册。

**生产试点放行条件**

- P0/P1 均按发布规则关闭；
- strict 不显著增加错误拒绝；
- 关键审计链完整率 100%；
- 可从上一稳定知识、Skill 和 Application 版本回滚；
- 观察期、负责人和停止条件已明确。

## 7. 贯穿全程的并行工作流

### 7.1 历史数据工作流

数据清洗不能等到 I10 才开始，应从第 1 周持续推进：

| 时间 | 累计目标 |
|---|---:|
| 第 1 周 | 完成 5–10 个项目资料盘点 |
| 第 6 周 | 5–10 个可演示 ProjectCase |
| 第 10 周 | 12–15 个较完整案例 |
| 第 17 周 | 20–30 个包含结果的案例 |
| 第 28 周 | 40–60 个案例或达到批准的领域覆盖目标 |

混合 PDF、Excel、会议纪要和报告项目，通常需要额外 2–5 个数据人日和 0.75–1.5 个专家人日。数据负责人应单独维护完整度和阻塞清单。

### 7.2 Golden Set 工作流

每个功能迭代同时增加对应反例：

| 迭代 | 必须新增的测试材料 |
|---|---|
| I1 | 重复文件、版本冲突、越权文件 |
| I2 | PDF 页码错误、CSV 行列错误、损坏文件 |
| I3 | 单位、日期、范围、来源冲突 |
| I4 | 未来资料泄漏、同项目不同阶段混用 |
| I5 | 知识不适用、条件未知、缺少反例 |
| I7 | 过期、争议、superseded、双人审核分歧 |
| I8 | 文本相似但业务条件不适用 |
| I9 | 无依据结论、引用不支持、应当拒答 |
| I10 | 四组盲评和项目级隔离 |
| I11–I15 | 越权、故障、回滚、漂移和生产回归 |

### 7.3 专家审核工作流

- 每周固定领域评审，不把专家验收推迟到迭代结束；
- 高风险 KnowledgeUnit 双人审核；
- 专家修改适用条件时必须保存修改前后 diff；
- 专家分歧作为数据保留，不用会议结论无痕覆盖；
- 审核积压超过 SLA 时暂停增加自动候选量。

## 8. 敏捷运行机制

### 8.1 每周节奏

| 时间 | 活动 | 产物 |
|---|---|---|
| 周一 | 迭代计划与风险确认 | 本周目标、故事、验收人和 WIP |
| 每日 | 15 分钟同步 | 阻塞、数据缺口、专家待决事项 |
| 周三 | 技术与数据中检 | API/Schema diff、案例质量 |
| 周四 | 领域专家评审 | Claim、案例、KnowledgeUnit 或分析结果 |
| 周五 | 可运行演示与复盘 | Demo、指标、缺陷、下一轮调整 |
| 每两周 | Candidate Build | 不可变构建、迁移、测试和回滚证据 |

### 8.2 WIP 限制

- 每个迭代只有一个主要纵向目标；
- 未通过证据链验收，不并行扩展更多格式；
- 未通过 ProjectCase 验收，不扩大知识编译；
- 未证明一个 Skill 有增益，不接入更多 Skill；
- P0 未关闭时不开始下一里程碑功能。

### 8.3 Story Definition of Ready

开发前每个 Story 至少具备：

- 关联的业务决策问题；
- 输入、输出和权限边界；
- Schema/API 影响；
- 正常样例和至少一个失败样例；
- 可演示的验收步骤；
- 数据迁移和回滚影响；
- 明确的领域验收人。

### 8.4 Story Definition of Done

- 纵向功能真实可运行；
- 权威状态已持久化；
- 审计链存在；
- 单元、迁移、API 和必要 UI 测试通过；
- 真实样本演示通过；
- P0/P1 已关闭或明确阻断发布；
- 文档、Schema、OpenAPI 和 CHANGELOG 同步；
- Feature Flag 和回滚已验证。

## 9. 团队分工

建议核心团队：

| 角色 | 主要责任 |
|---|---|
| 技术负责人 / 后端 | 架构、数据库、API、运行链和迁移 |
| 数据与知识工程师 | 解析、标准化、编译、检索和图投影 |
| 前端 / 全栈 | 资料、审核、案例对比、证据和评测界面 |
| LLM / 评测工程 | Claim 抽取、核验、历史回放和基线实验；可由前两者兼任 |
| 地产领域专家 | Schema、案例、KnowledgeUnit、Golden Set 和业务验收 |
| QA / DevOps | 自动化、发布、监控、备份和安全；前期可兼职 |

领域专家不是项目末期的验收资源，而是从 I0 开始持续参与的知识共同开发者。

## 10. 阶段停止与转向条件

### I2 后

如果核心文档 locator 准确率明显低于目标，停止增加格式，优先修复证据定位。

### I4 后

如果不足 5 个案例能形成可信的“输入—判断—动作—结果”，不得进入自动知识编译，应先补数据或缩小决策域。

### I5 后

如果专家认为 KnowledgeUnit 相比直接阅读案例没有提高复用效率，应重做知识契约和适用条件，而不是增加图算法。

### I8 后

如果完整方案相对 Skill-only 没有可测增益，不继续接入更多 Skill，应检查案例质量、知识粒度和匹配逻辑。

### I10 后

如果误放行、未来泄漏、关键数字错误或反例遗漏仍超过门槛，只能保留 shadow/warn，不得进入 strict。

### I14 后

如果出现越权、不可恢复的数据不一致或无法回滚，生产试点停止，先完成安全和恢复整改。

## 11. 延期时的裁剪顺序

时间不足时按以下顺序后移，不能裁掉证据和审核：

1. 图谱可视化美化；
2. 复杂图算法；
3. Obsidian 实时双向同步；
4. PPT 和复杂图表自动理解；
5. 第三个及后续 Skill；
6. 自动对接 CRM/财务系统；
7. 高级运营看板；
8. 独立微服务和专用消息队列。

以下能力不得为了赶工裁掉：

- 原始资料版本和 SHA-256；
- EvidenceSpan 与可打开引用；
- scope、日期、单位和来源；
- ProjectCase 时间截断；
- KnowledgeUnit 专家审核；
- 反例与适用条件；
- 运行版本快照；
- 权限和回滚。

## 12. 第一个 30 天的具体任务

### 第 1 周

- 确定“产品组合与首开策略”决策边界；
- 选出 5–10 个案例；
- 完成 ID、Schema 和 PostgreSQL 迁移骨架；
- 增加 Feature Flag 和知识层健康状态。

### 第 2 周

- 完成项目资料库、文件哈希、版本和来源信息；
- 增加“加入项目资料库”；
- 支持标准 Markdown Frontmatter 导入。

### 第 3 周

- 完成 PDF/Markdown/CSV 解析；
- 建立 EvidenceSpan；
- 打通原文页码、段落和表格行列回跳。

### 第 4 周

- 完成 Claim、Metric、Scope；
- 建立候选抽取和人工校正；
- 实现来源、单位、范围和日期校验。

30 天结束时，应得到一套可信的**格式化项目证据底座**，而不是一个看起来复杂但无法核验的知识图谱。

## 13. 下一份执行产物

本方案确认后，应立即生成以下执行文件：

1. `PoC-BACKLOG.md`：I0–I5 的 Story 和验收；
2. `DOMAIN-DATA-DICTIONARY.md`：首个决策域字段、单位和枚举；
3. `KNOWLEDGE-SCHEMA-V0.1.md`：实体、关系和状态机；
4. `EVAL-GOLDEN-SET-SPEC.md`：时间截断案例模板和评分；
5. `MIGRATION-AND-ROLLBACK.md`：数据库、原文件和 Feature Flag；
6. `SPRINT-0-ACCEPTANCE.md`：第一周验收清单。

