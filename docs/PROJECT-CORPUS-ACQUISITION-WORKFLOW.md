# Hoosland 50–100 个现有项目资料采集与知识蒸馏前处理工作步骤

文档状态：`Draft for Review`  
文档版本：`0.1.0`  
编写日期：`2026-08-27`  
原始编写分支：`feat/project-corpus-distillation`（已随 V0.2.1 发布分支归档）
上位设计：[知识决策系统开发文档](KNOWLEDGE-DECISION-SYSTEM-DEVELOPMENT.md)  
上位计划：[知识决策系统敏捷实施计划](KNOWLEDGE-DECISION-SYSTEM-AGILE-IMPLEMENTATION-PLAN.md)  
配套计划：[独立知识提纯库实施计划](KNOWLEDGE-REFINERY-CORE-IMPLEMENTATION-PLAN.md)

## 0. 执行结论

本阶段先建立一批**合法可用、来源可追溯、范围可比较、能按项目隔离**的地产项目语料，不直接把网页摘要或 Skill 输出当成知识。

建议采用以下目标：

- 最低交付：`50` 个达到 C1 或更高等级的资料就绪项目（`C1+`）；
- 默认目标：`75` 个 C1+ 项目；
- 扩展上限：`100` 个 C1+ 项目；
- 从中形成 `30–50` 个达到 C2 或更高等级的案例就绪项目（`C2+`）；
- 从中形成 `20–30` 个包含“当时输入—判断—动作—结果”的 C3 蒸馏就绪案例；
- 从 C3 中分层留出 3 个盲测案例；C3 总数包含这 3 个项目，但知识编译 allowlist 必须将其排除。

采集顺序必须是：

```text
锁定决策域与授权边界
→ 建立 120–150 个候选项目池
→ 按覆盖矩阵筛选 50–100 个项目
→ 建立项目与 scope 身份
→ 登记来源、权限和不可变原文版本
→ 解析为可定位证据
→ 提取并核验 Claim / Metric
→ 构造时间截断 ProjectCase
→ 分级验收与冻结语料版本
→ 才允许进入后续知识蒸馏
```

首版默认只覆盖**住宅项目的产品组合与首开策略**。这是现有知识提纯设计已锁定的首个决策域。商业、产业园、文旅、酒店和城市更新可进入候选池，但不应混入首版可比较案例；如需覆盖，应另建决策域、字段扩展和评测集。

## 1. 目标、边界与非目标

### 1.1 本阶段目标

1. 获得 50–100 个唯一项目的可追溯资料包。
2. 让关键事实能够回到原网页、PDF 页码、Markdown 段落或表格单元格。
3. 保留来源主体、时间、范围、口径、权限、哈希和处理血缘。
4. 将事实、推导、推断、假设和建议分层保存。
5. 为后续 `ProjectCase → KnowledgeCandidate → KnowledgeUnit` 提供可审核输入。
6. 建立一组按项目隔离的盲测材料，避免训练/调试与评测泄漏。

### 1.2 本阶段不做

- 不把 50–100 个“项目名”当成 50–100 个有效案例；
- 不把新闻聚合页、搜索摘要或营销文案直接当作事实；
- 不由 LLM 自动批准 Claim、因果关系或成功经验；
- 不把缺少实际动作或结果的项目标记为蒸馏就绪；
- 不绕过登录、付费墙、验证码、访问控制、robots 限制或反爬机制；
- 不在 Git 中批量提交受版权保护的原文、图片、宣传册或客户受限资料；
- 不在本阶段生成问答训练集、微调数据或自动发布 KnowledgeUnit；
- 不把 `real-estate-delivery-qa` 当作数据质量引擎；它只负责最终可读交付物的放行检查。

## 2. 统一对象与分级口径

### 2.1 三类对象不得混用

| 对象 | 含义 | 计数规则 |
|---|---|---|
| `Project` | 项目的稳定身份 | 同名不同城市分开；同项目不同期次默认建立父子 Scope，不重复计算项目数 |
| `Document` | 一个逻辑来源 | 同一来源更新后生成新 `DocumentVersion`，不覆盖旧版 |
| `ProjectCase` | 某一决策时点的案例快照 | 同一项目可有定位、首开、在售复盘等多个时间截断案例 |

“完成 50–100 个项目”指 50–100 个通过资料就绪门槛的唯一 `Project`，不等于拥有同等数量的完整 `ProjectCase`。

### 2.2 语料成熟度

三类资料角色在全文使用固定标识：

- `R1_IDENTITY`：身份与法定条件，包括规划、出让、土地成交、许可或企业正式项目资料；
- `R2_DECISION`：决策与产品动作，包括定位、产品组合、推售、价格、营销或正式内部决策记录；
- `R3_OUTCOME`：结果与复盘，包括成交、去化、调价、交付、客户、经营复盘或可核验结果。

| 等级 | 名称 | 最低条件 | 可用于 |
|---|---|---|---|
| C0 | 候选项目 | 名称、城市、开发主体、项目类型可识别 | 候选池与替补池 |
| C1 | 资料就绪 | 项目身份稳定；至少 2 个独立来源，其中 `R1_IDENTITY` 至少 1 个且为 A/B 级，`R2_DECISION` 或 `R3_OUTCOME` 至少 1 个；原文、哈希、权限和来源台账完整 | 检索、事实抽取、覆盖分析 |
| C2 | 案例就绪 | C1 + 可形成 Context、关键 Claim/Metric、约束、决策问题和明确未知项 | 案例比较、人工研究 |
| C3 | 蒸馏就绪 | C2 + 实际 Decision、Action、Outcome、观察窗口、混杂因素和时间截断 | 候选知识编译与历史回放 |
| CQ | 隔离 | 权限不明、证据不足、实体冲突或解析失败 | 修复或审查，不进入正式语料 |

等级是递进关系。每个项目只保存一个 `highest_maturity`，统计时使用累计口径：`C1+ = C1 ∪ C2 ∪ C3`，`C2+ = C2 ∪ C3`，`C3` 为最高等级。因此 75 个验收项目可以同时统计为 75 个 C1+、40 个 C2+ 和 25 个 C3，不需要把三组数量相加。

项目状态建议统一为：

```text
candidate
→ screened
→ collecting
→ raw_complete
→ normalized
→ review_pending
→ accepted_c1 / accepted_c2 / accepted_c3
→ frozen

任一阶段可转为 quarantined / rejected / superseded
```

## 3. 现有 Skill Set 的使用方式

### 3.1 可直接复用的能力

| Skill / 脚本 | 本任务中的职责 | 使用限制 |
|---|---|---|
| `comprehensive-real-estate-expert` | 统一入口、项目身份、`scope_id`、来源/主张账本、G0–G3 闸门 | 负责路由和证据纪律，不替代采集器或数据库 |
| `real-estate-research` | 候选筛选、来源优先级、规划/土地/市场/竞品/客群核验 | 动态事实必须按 `as_of_date` 重新核验 |
| `wechat-article-exporter` | 对已知且允许访问的微信文章做 Markdown/JSON 研究归档 | 不负责发现项目；不绕过访问限制；微信材料通常仅为 C 级来源 |
| `real-estate-product-strategy` | 在 C2/C3 阶段整理产品组合、价格、货值和节奏字段 | 不能在缺少土地、成交和支付证据时补造精度 |
| `real-estate-report-editorial` | 编辑覆盖报告、数据卡和评审结论 | 不改变证据等级、数值或适用范围 |
| `real-estate-delivery-qa` | 对最终工作报告、数据卡和清单做发布前检查 | 不代替 Schema 校验、哈希、去重和证据回跳测试 |
| MCP `web_search` 能力 | 按查询发现候选来源和补充交叉验证链接 | 依赖单独配置的 Provider；单次 `limit` 最大 20；未配置时必须返回 `CAPABILITY_NOT_CONFIGURED`，不能用模型猜测替代 |
| MCP `document_extract` 能力 | 对会话工作区内的单个文档做文本或结构化抽取 | 依赖单独配置的 Provider；本地 Chat Completions 路径仅支持 TXT/MD/HTML/JSON/CSV/PDF，不含 OCR、DOCX、XLSX；不是批量入库管道 |
| `init_case.py` | 初始化单项目 `project_state.json / sources.csv / claims.csv` | 当前 Schema 为单项目工作底稿，不是跨项目总清单 |
| `validate_case.py` | 校验单项目状态、来源 ID、Claim 类型和引用关系 | 尚不校验版权、文件哈希、EvidenceSpan 和跨项目重复 |
| `scope_check.py` | 检查父子 Scope 与可加总指标 | 只能检查显式输入的范围关系 |

### 3.2 必须承认的现有缺口

当前 Skill Set 尚不具备以下规模化能力，实施阶段必须补齐，不能在工作记录中写成“已完成”：

当前仓库没有真实项目语料库；`skills/tests/fixtures/` 下只有 3 个明确用于测试的合成 JSON fixture，不能计入 50–100 个项目目标。

1. 通用网页、PDF、DOCX、XLSX、图片和 OCR 的批量采集适配器；现有 `web_search` 和 `document_extract` 只能辅助单次发现/抽取，不能代替下载、版本、队列和证据入库；
2. 项目候选自动发现与跨站点调度；
3. 跨项目 corpus manifest、统一 Schema 和数据迁移；
4. 抓取缓存、断点续跑、限速、指数退避和 dead-letter；
5. 文件级与内容级去重、别名消歧和实体合并审核；
6. `DocumentVersion / EvidenceSpan / ProjectCase` 的正式持久化；
7. 权限继承、审计日志和盲测集隔离；
8. 真正的知识蒸馏、反例搜索和 KnowledgeUnit 审核流水线。

`wechat-article-exporter/scripts/batch_fetch.py` 当前会按每种输出格式重复请求同一篇文章。Pilot 可只取一种主格式；进入规模采集前，应改为“一次抓取、多格式本地转换”，避免重复请求和不必要的访问压力。

## 4. 样本框架

### 4.1 候选池、主采集队列与验收集

先登记 `120–150` 个候选项目，再建立默认 75 个项目的主采集队列和至少 25 个同层替补。只有通过 C1 的项目才进入 `accepted corpus`；主队列中尚未处理或未通过的项目不计入验收数量。这样既允许在 50 个项目达到覆盖目标时停止，也不会把剩余队列误记为失败样本。

设置候选池和替补队列的原因是：

- 部分项目无法找到 A/B 级来源；
- 部分项目存在名称、期次或开发主体歧义；
- 部分资料受限、失效或不允许进入语料；
- 只选择“资料最多的名盘”会产生知名度和成功者偏差。

### 4.2 首版覆盖矩阵

首版样本只要求住宅决策域内的覆盖，不追求所有地产类型的数量均衡。每个项目至少记录以下标签：

- 地域与城市；
- 城市层级及层级依据；
- 核心区、成熟板块、成长板块、远郊新城或存量压力板块；
- 央国企、民营、地方平台或合资开发主体；
- 刚需、刚改、改善、高端等主定位；
- 定位、首开、在售、交付、复盘阶段；
- 强销、正常、滞销、调价、停工/复工等结果标签；
- 公开资料完整度与来源结构；
- 是否具备反例或失败模式价值。

建议的偏差控制线：

- 单一城市不超过 `accepted corpus` 的 `15%`；
- 单一开发商不超过 `accepted corpus` 的 `10%`；
- 单一来源域名不得成为某项目全部关键事实的唯一依据；
- 弱销售、调价、去化困难或策略失效项目不少于 C3 案例的 `20%`；
- 资料较弱但有反例价值的 C1 项目不超过 `accepted corpus` 的 `10%`；
- C3 案例必须同时覆盖支持案例与反例，不得只保留成功项目。

### 4.3 候选准入

C0 进入正式采集前至少满足：

1. 能确认规范名称、所在城市、主要开发主体和住宅属性；
2. 能区分项目、期次、宗地和产品组团；
3. 找到至少两个相互独立的潜在来源；
4. 至少一个潜在来源为政府、交易机构、企业正式披露、正式内部系统或经核验台账；
5. 资料不是只有搜索摘要、单条营销信息或无法定位的截图；
6. 权限初审没有明确禁止采集或处理。

## 5. 来源、权限与证据规则

### 5.1 沿用现有来源分级

| 等级 | 来源 | 在本任务中的用途 |
|---|---|---|
| A | 法定规划、政府公告、土地出让/成交文件、登记或正式内部系统 | 范围、规划、指标、成交和监管事实 |
| B | 企业正式披露、权威研究机构、经核验项目台账 | 经营、产品、市场和项目动作 |
| C | 主流媒体、平台数据库、微信公众号、销售口径 | 发现线索、补充背景和待核验观点 |
| D | 传闻、匿名截图、无日期转述、生成式内容 | 只进入调查线索，不进入事实层 |

C1 的唯一准入规则是：至少两个独立来源，其中一个必须是 A/B 级 `R1_IDENTITY`，另一个必须是 `R2_DECISION` 或 `R3_OUTCOME`。关键市场判断原则上仍需两个独立来源；单一弱来源只能形成 `HYPOTHESIS`。该规则必须同步到成熟度表、采集清单、验收表和后续 validator。

### 5.2 来源登记最小字段

每个 `DocumentVersion` 至少保存：

```text
source_id
document_id
document_version_id
project_id
scope_id
title
publisher
author
source_grade
source_type
original_url_or_relative_path
published_at
data_as_of
retrieved_at
access_method
http_status_or_fetch_status
mime_type
language
byte_length
sha256
rights_status
distribution_policy
parser_name_and_version
raw_relative_path
extracted_relative_path
notes
```

`rights_status` 建议限定为：

- `public_reference_only`：可做内部研究、事实抽取和必要短引用，不随语料包再发布全文；
- `customer_authorized`：客户明确授权在指定知识库内处理；
- `owned_internal`：组织自有材料，按内部权限处理；
- `open_license`：记录具体许可名称和版本；
- `unknown_quarantine`：权利不明，只能隔离；
- `prohibited`：不得采集或处理正文，只保留满足审计所需的最小拒绝元数据。

### 5.3 原文与引用

- 原始文件只追加新版本，不原地修改；
- SHA-256 相同的文件复用内容对象，但保留各自来源关系；
- 网页正文、PDF、表格和图片必须保留稳定 locator；
- 客观数字和关键事实必须能由 `claim_id` 回跳到 EvidenceSpan；
- 直接引用只保留完成核验所需的最短片段和上下文；
- 第三方资料不会因为本仓库采用开源许可而自动获得相同再分发许可；
- Git 只保存工作文档、Schema、模板、许可允许的结构化结果和合成测试样本；受限原文放受控数据存储。

## 6. 数据目录与 Manifest

语料数据与代码仓库分离。逻辑目录建议如下：

```text
project-corpus/
  README.md
  corpus-card.md
  schema/
    project.schema.json
    scope.schema.json
    document.schema.json
    claim.schema.json
    project-case.schema.json
    data-dictionary.yaml
  manifests/
    projects.csv
    documents.jsonl
    files.csv
    runs.jsonl
    rights-review.csv
    rejected-projects.csv
  raw/
    {project_id}/
      {source_id}/
        {document_version_id}/...
  extracted/
    {project_id}/
      {document_version_id}.md
      {document_version_id}.json
  normalized/
    projects.jsonl
    scopes.jsonl
    claims.jsonl
    metrics.jsonl
    cases.jsonl
  profiles/
    {project_id}.md
  qa/
    completeness.csv
    duplicate-review.csv
    conflicts.csv
    locator-checks.csv
    rights-checks.csv
    review-log.jsonl
  splits/
    development-projects.txt
    blind-evaluation-projects.txt
  logs/
    acquisition-runs.jsonl
    parse-runs.jsonl
```

本地 Pilot 可以将数据根目录配置到 Git 已忽略的 `outputs/project-corpus/`，但该目录不能成为唯一副本；每批冻结前必须复制到具备备份、权限和不可变版本能力的受控存储。不得将绝对宿主路径写入可分发清单，清单只使用数据根目录下的相对路径。

## 7. 逐步执行流程

### Step 0：任务登记与决策域冻结

**输入**：本文件、上位知识提纯设计、数据处理授权。  
**动作**：

1. 确认首版决策域为住宅项目产品组合与首开策略；
2. 确认允许使用的公开资料、内部资料和外部模型范围；
3. 指定数据负责人、研究负责人、领域审核人和权限审核人；
4. 冻结项目 ID、Scope ID、时间、单位、来源和权限字段；
5. 建立 `corpus_version = corpus-v0.1-pilot`。

**退出条件**：数据字典和 ID 规则完成共同评审；候选发现和资料处理授权已明确。若已有 5 个合法 seed 项目则直接进入 Smoke；否则由 Step 1 先建立候选池并选出 5 个 seed，不得用合成 fixture 代替。

### Step 1：建立 120–150 个候选项目池

由总控加载 `real-estate-research`，按来源优先顺序发现和登记项目。已配置 MCP `web_search` 时可用于生成候选链接；每次查询结果上限 20，因此必须按城市、板块、时间和来源类型拆分查询，并在项目级去重。未配置时记录能力缺口，不得生成虚构搜索结果。

来源顺序：

```text
政府规划/交易文件
→ 登记或正式内部数据
→ 企业正式披露
→ 权威研究机构
→ 主流媒体/平台
→ 微信与销售口径
→ 匿名线索
```

候选登记只保存项目身份、候选来源链接、覆盖标签、预期案例等级、权利初判和纳入理由，不在此步大规模下载全文。

**输出**：`candidate-projects.csv`、重复候选清单、候选覆盖矩阵。  
**退出条件**：候选数达到 120–150，且不存在明显单城市、单开发商或单来源垄断。

### Step 2：筛选并冻结主采集队列

1. 运行项目身份去重；
2. 将同项目不同期次建立父子 Scope；
3. 根据覆盖矩阵和资料可得性评分；
4. 选出默认 75 个项目的主采集队列和至少 25 个同层替补；
5. 为每个项目设定目标等级 C1、C2 或 C3；
6. 预先登记盲测的分层抽样规则和保留层位，但不依据模型表现挑选项目。

**禁止**：按“最容易找到资料”单一排序；把未采集项目计入 `accepted corpus`；根据模型表现更换盲测项目。  
**退出条件**：主采集队列和替补队列均能满足覆盖与权利初审要求。

### Step 3：初始化项目工作区和范围树

对主采集队列中的每个启动项目调用现有初始化脚本：

```powershell
python skills/comprehensive-real-estate-expert/scripts/init_case.py `
  <case-directory> `
  --project <project-name> `
  --scope-id <scope-id> `
  --stage <stage> `
  --mode audit
```

随后建立：

- `project_id` 与规范名、别名；
- 城市 → 板块 → 期次 → 宗地 → 子地块 → 产品组团范围树；
- `as_of_date`、项目阶段和目标决策域；
- 原始 `sources.csv`、`claims.csv` 和项目阻塞项。

**退出条件**：G0 范围身份通过；同名项目和不同期次没有被静默合并。

### Step 4：制定单项目采集清单

每个项目至少规划三类资料：

1. **`R1_IDENTITY` 身份与法定条件**：规划、出让、土地成交、许可或企业正式项目资料；
2. **`R2_DECISION` 决策与产品动作**：定位、产品组合、推售、价格、营销或正式内部决策记录；
3. **`R3_OUTCOME` 结果与复盘**：成交、去化、调价、交付、客户、经营复盘或可核验结果。

C1 必须具备 `R1_IDENTITY`，并由 `R2_DECISION` 或 `R3_OUTCOME` 中的至少一个独立来源交叉确认项目事实；C2 必须具备 `R1_IDENTITY + R2_DECISION`；C3 必须同时具备三类资料，并将决策前证据和决策后结果按时间截断。

**输出**：每项目 `collection-plan.csv`，字段包括目标来源、负责人、优先级、预期等级、权限状态、计划获取方式和替代来源。

### Step 5：获取原始资料

采集器只负责合法获取和原样登记，不负责判断事实真伪。

- 已知微信链接：使用 `wechat-article-exporter` 归档；
- 公开网页：保存 URL、响应元数据、正文快照和必要 locator；
- PDF/DOCX/XLSX/CSV：保存原文件、MIME、字节数和 SHA-256；
- 内部资料：复制到项目权限域，保留原权限和审计记录；
- 动态页面或无法直接下载的页面：只在允许的交互式访问下保存可见证据，不绕过控制；
- 失败来源：登记错误类型、尝试次数和替代来源，不补写正文。
- 已知 `prohibited`：不下载正文、不写入 raw corpus，只保存最小来源标识、拒绝原因和处理时间。

微信 Pilot 示例：

```powershell
python skills/wechat-article-exporter/scripts/batch_fetch.py `
  <wechat-urls-file> `
  markdown `
  <project-wechat-output-directory>
```

在批量脚本完成“一次抓取、多格式转换”改造前，每轮只选一种主格式，并另外把抓取元数据写入 `documents.jsonl`。

**退出条件**：所有成功文件均有来源记录、相对路径、SHA-256 和权利状态；失败项有可审计记录。

### Step 6：原文冻结与版本登记

1. 计算文件 SHA-256；
2. URL 规范化，但保留原始 URL；
3. 对相同内容复用内容对象，不删除来源关系；
4. 同一来源发生变化时创建新 `document_version_id`；
5. 保存抓取时间、发布/数据日期、访问方式和处理版本；
6. 将 `unknown_quarantine` 与可用语料物理或逻辑隔离；
7. 若正文下载后才被判定为 `prohibited`，立即停止派生处理，并按权限政策删除或转交受控处置；禁止进入 raw corpus、备份和任何冻结版本，只保留最小拒绝审计记录。

**退出条件**：重复导入不产生重复内容版本；旧版本仍可打开；原始内容不可变。

### Step 7：解析与 EvidenceSpan 构建

将原文解析为规范化 Markdown/JSON，并保留：

- PDF 页码与区域；
- Markdown 标题路径与段落序号；
- 表格工作表、单元格和行列；
- 网页 DOM/正文段落定位；
- OCR 页码、区域和置信度；
- 原始文本哈希、解析器版本和重建入口。

已配置 MCP `document_extract` 时，可以辅助单文件抽取，但必须遵守工作区文件边界和能力限额。当前默认单文件/能力输入上限为 25 MiB；Chat Completions 本地抽取最多传递约 120,000 字符，且只直接支持 TXT、Markdown、HTML、JSON、CSV 和可读文本 PDF。被截断的文档、扫描 PDF、DOCX 和 XLSX 必须走专用解析器，不能把部分抽取标成完整。

低置信 OCR 数字、无法回跳的摘要和缺失正文不得进入已验证事实。

**退出条件**：抽检 EvidenceSpan 可打开率 100%；Pilot locator 人工准确率达到 90% 目标。

### Step 8：事实、指标与冲突标准化

由 `real-estate-research` 负责研究口径，逐条形成原子 Claim：

```text
FACT / DERIVED / INFERENCE / HYPOTHESIS / RECOMMENDATION
```

每个数字至少记录：

```text
value_original
unit_original
value_normalized
unit_normalized
currency
denominator
period
methodology
scope_id
as_of_date
source_ids
evidence_span_ids
confidence
status
```

冲突处理顺序：范围 → 日期 → 单位 → 统计定义 → 原始性与权威性。无法消解时并列保存为 `disputed`，不得静默覆盖。`DERIVED` 必须保存公式和输入 Claim。

**退出条件**：关键数字的 scope、单位和来源错误为 0；无来源 `FACT` 无法进入 verified。

### Step 9：ProjectCase 与时间截断

对目标为 C2/C3 的项目建立：

```text
ContextSnapshot
+ Claim / MetricObservation
+ Assumption / Constraint
+ 决策问题与备选方案
+ DecisionRecord
+ Action
+ OutcomeObservation
+ 观察窗口与混杂因素
```

定位时点案例只能读取 `decision_time` 之前允许的资料；后续成交与复盘资料进入结果层和未来资料黑名单。缺少 Decision、Action 或 Outcome 的案例可以停在 C2，但不得作为“成功经验”支持正式 KnowledgeUnit。

**退出条件**：时间泄漏为 0；每个 C3 案例能够展示“当时判断—实际动作—后续结果”。

### Step 10：自动校验与人工复核

每个项目先运行现有基础校验：

```powershell
python skills/comprehensive-real-estate-expert/scripts/validate_case.py <case-directory>
python skills/real-estate-research/scripts/scope_check.py <scope-check-input.json>
```

再运行待实现的 corpus 级校验：

- Schema、必填字段、枚举和日期；
- 文件哈希、孤儿文件和重复来源；
- 项目别名、地址、主体和 Scope 冲突；
- Claim → EvidenceSpan → DocumentVersion 回跳；
- 单位、币种、分母、观察期和公式；
- 权利状态、敏感字段和跨项目权限；
- 未来资料泄漏；
- development / blind evaluation 项目交叉污染。

人工复核要求：

- 权限与隐私：100% 项目复核；
- C3 案例：100% 领域复核；
- 除 C3 外的 C1+/C2+ 项目：抽检数取 `accepted corpus` 的 20% 与 15 个项目中的较大值；
- 高风险知识候选：两名专家独立审核，分歧由第三人裁决；
- P0 错误为 0：伪造来源、关键数字无证据、范围混用、未来泄漏、越权访问。

### Step 11：分级验收、冻结与发布数据卡

每个项目只保存实际达到的最高等级 `highest_maturity = C1 / C2 / C3`，汇总时按 C1+、C2+、C3 累计统计。C3 达到 20 个且尚未开始任何知识编译或 Prompt 调试时，由评测负责人按预登记规则从所有 C3 中分层冻结 3 个盲测项目；这 3 个计入 C3 总数，但不进入 `distillation_allowlist`，且知识编译/Prompt 调试团队不可访问其身份和材料。冻结时生成：

如果最终 C3 少于 20 个，可以冻结 C1+/C2+ 资料版本，但必须把知识蒸馏状态标为 `blocked_insufficient_c3`，不得启动知识编译。

- 不可变 corpus 版本号；
- 项目、文档、文件、Claim、Case 和运行 manifest；
- 覆盖、完整度、冲突、去重、locator、权限和抽检报告；
- `corpus-card.md`，说明用途、范围、采样、偏差、限制和禁止用途；
- development / blind evaluation 项目清单及哈希；
- 失败与拒绝项目清单，不删除失败记录。

冻结版本建议：

```text
corpus-v0.1-pilot     5–10 个项目
corpus-v0.5-minimum   50 个 C1+ 项目
corpus-v0.8-default   75 个 C1+ 项目
corpus-v1.0           50–100 个 C1+、30–50 个 C2+、20–30 个 C3（含 3 个盲测），全部门槛通过
```

## 8. 分批节奏与停止条件

| 批次 | 新增项目 | 累计目标 | 主要验证 |
|---|---:|---:|---|
| Smoke | 5 | 5 | ID、范围、权限、目录、哈希和最小证据链 |
| Pilot | 5 | 10 | Schema、解析、locator、单项目成本和失败类型 |
| Batch A | 20 | 30 | 并发、断点续跑、去重、覆盖矩阵 |
| Batch B | 20 | 50 | 最低交付、C2/C3 转化率、首次饱和度评估 |
| Batch C | 25 | 75 | 默认目标、反例与弱结果覆盖 |
| Batch D | 25 | 100 | 只在覆盖或知识增量仍明显不足时执行 |

每批都执行完整闭环：

```text
候选确认 → 采集 → 原文冻结 → 解析 → 标准化 → 去重
→ 自动校验 → 人工抽检 → 分级 → 冻结 → 复盘
```

达到 50 个后召开 Go/Stop 评审：

- 覆盖矩阵已满足，且最近 10 个项目新增的决策模式、反例或字段需求很少，可在 50–75 之间停止；
- C3 仍不足 20 个、反例不足、城市/开发商偏差超线或新批次仍持续发现重要模式，则继续到 75；
- 只有在 75 后仍存在明确覆盖缺口时才扩展到 100；
- 不允许为了凑数降低 C1 门槛。

Pilot 后用真实数据估算人力，不在 Pilot 前承诺固定采集工期。至少记录：每项目文档数、成功率、平均人工分钟、解析失败率、C1→C2→C3 转化率和返工率。

## 9. 失败、重试与替换

建议统一错误码：

```text
TIMEOUT
HTTP_404
BLOCKED
PAYWALL
CAPTCHA
ROBOTS_DENIED
DOWNLOAD_FAIL
OCR_FAIL
PARSE_FAIL
RIGHTS_UNKNOWN
ENTITY_AMBIGUOUS
CONFLICT
INSUFFICIENT_EVIDENCE
FUTURE_LEAKAGE
```

处理原则：

1. 网络瞬时错误最多重试 3 次，使用递增退避和域名级限速；
2. 登录、付费墙、验证码、robots 禁止或明确访问限制不做绕过重试；
3. 优先寻找同一事实的官方替代来源；
4. 单个项目尝试 3 个独立来源后仍达不到 C1，转入 `rejected` 并启用同层替补；
5. 权利不明进入 `unknown_quarantine`，不得以空字段伪装通过；
6. 解析失败保留原文与失败版本，修复后重新运行并记录解析器版本；
7. 失败任务、人工覆盖和替换理由必须进入 `runs.jsonl` 或审计日志。

## 10. 验收门槛

### 10.1 C1+ 资料就绪

- [ ] 50–100 个唯一项目，默认目标 75；
- [ ] 项目 ID、规范名、城市、开发主体、住宅属性、阶段和 Scope 身份完整率 100%；
- [ ] 每项目至少 2 个独立来源：至少 1 个 A/B 级 `R1_IDENTITY`，另有至少 1 个独立的 `R2_DECISION` 或 `R3_OUTCOME`；
- [ ] 所有原始版本都有 SHA-256、抓取时间、来源和权利状态；
- [ ] 所有关键事实和数字有可定位证据；
- [ ] 已知重复项目为 0，歧义合并为 0；
- [ ] 已知冲突全部显式登记；
- [ ] `unknown_quarantine` 和 `prohibited` 内容未进入正式语料；
- [ ] EvidenceSpan 可打开率 100%，locator 抽检准确率达到 90% 目标；
- [ ] 跨项目未授权访问为 0。

### 10.2 C2+ 案例就绪

- [ ] 30–50 个项目达到 C2；
- [ ] Context、关键 Claim/Metric、Assumption、Constraint 和决策问题可比较；
- [ ] 缺失值使用 `unknown` 与原因，不以推断补齐；
- [ ] 关键数字 scope、单位、日期、口径和来源错误为 0；
- [ ] 事实、推导、推断、假设和建议没有混层。

### 10.3 C3 蒸馏就绪

- [ ] 20–30 个案例具备输入、判断、动作、结果、观察窗和混杂因素；
- [ ] 每个案例通过时间截断，未来资料泄漏为 0；
- [ ] 支持案例与反例同时存在，弱结果/失败案例达到覆盖线；
- [ ] C3 总数包含 3 个盲测项目，`distillation_allowlist = C3 - blind_evaluation`；
- [ ] 盲测按项目拆分，同项目任何文档没有泄漏到知识编译、Prompt 调试或开发集；
- [ ] 采集与 QA 团队可按职责访问盲测原文，但知识编译/Prompt 调试团队不可访问盲测身份和材料；
- [ ] C3 案例完成 100% 领域复核；
- [ ] 缺少实际动作或结果的项目未被用作成功经验。

## 11. 蒸馏前交付物

1. 原始证据包与文件哈希清单；
2. 项目、Scope、文档、Claim、Metric 和 ProjectCase 标准化数据；
3. 每项目一份可读项目卡；
4. Claim → EvidenceSpan → DocumentVersion 证据映射；
5. 数据字典、Schema、ID 和版本规范；
6. 样本分层、覆盖与偏差报告；
7. 完整度、冲突、去重、locator、权限和抽检报告；
8. 失败/拒绝/隔离项目清单与替换理由；
9. corpus data card、禁止用途和已知局限；
10. 运行日志、Skill/脚本/解析器版本和可复现配置；
11. development 与 blind evaluation 的项目级拆分；
12. 后续知识编译的 `distillation_allowlist`，其值严格等于已批准 C3 减去 blind evaluation；C1+/C2+ 不自动升级。

只有上述交付物通过评审后，才进入：

```text
证据与事实抽取
→ 案例内决策链整理
→ 跨案例模式与反模式发现
→ 主动搜索支持案例和反例
→ 适用条件与失效信号结构化
→ 专家审核
→ 发布不可变 KnowledgeUnitVersion
```

## 12. 分支与实施边界

本分支只承载本任务新增的工作文档、后续 Schema/脚本和合成测试夹具。创建分支时工作树已经存在其他未提交修改；后续实现必须：

- 只定向暂存本任务文件；
- 不使用 `git add -A`；
- 不擅自 stash、reset、覆盖或提交既有未提交改动；
- 不把 `outputs/` 下的真实语料原文加入 Git；
- 每次实现前先记录基线 diff，避免把并行工作混入本任务提交。

## 13. 文档批准后的首轮任务

1. 评审并冻结首版决策域、覆盖矩阵和权限政策；
2. 新增跨项目 `projects/documents/files/runs/rights` Manifest 模板；
3. 新增 Project、DocumentVersion、EvidenceSpan 和 ProjectCase Schema；
4. 为 `init_case.py / validate_case.py` 增加 corpus 侧适配，不破坏现有 v2.1 项目格式；
5. 将微信批处理改为一次抓取、多格式本地转换；
6. 实现通用公开网页/PDF 的最小采集 adapter、缓存、限速和失败清单；
7. 先完成 5 个 Smoke 项目并提交成本、失败和 Schema 修订报告；
8. 评审通过后扩展至 10 个 Pilot，再决定 50/75/100 的执行节奏。
