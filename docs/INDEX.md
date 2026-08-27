# 项目文档索引

本页是 Hoosland-real-estate-research-toolset 的公开文档入口，用于区分产品说明、架构约束、升级规则和发布证据。公开文档不保存生产凭证、客户数据、内部地址、主机信息、私有文件路径或可关联到具体任务的运行标识。

## 当前文档基线

| 版本轴 | 当前值 |
|---|---|
| 产品线 | V2 |
| Application | `0.2.1` |
| Build | `v0.2.1-production-sync-version-info-20260827T062425Z` |
| System Prompt | `real-estate-system-v0.2.1` |
| Skill bundle | `2.3.1` |
| Project state Schema | `2.1.0` |

当前核心行为契约：

- 应用每轮先确定性提交 `/comprehensive-real-estate-expert` 入口命令；Prompt/Skill 契约再要求总控调用并去重子 Skill。会话首行证明命令已提交，operation/E2E 证明后续子链；当前没有独立的总控正文加载回执。
- 总控文件缺失时，Ready 与运行均 fail closed，不静默退化为单 Skill 直达。
- 地产研究、项目分析、策划方案和管理报告在用户未指定最终格式时，默认同轮生成 Markdown 与独立 HTML。
- PDF 仍是按需格式；微信归档、社交素材和数据模型等专项任务保留各自输出契约。
- 是否完成以真实操作记录和实际文件为准，不以模型在文本中的自述为准。

## 文档地图

### 入门与使用

- [项目说明](../README.md)：产品定位、版本矩阵、能力、快速启动与当前限制。
- [安装指南](INSTALLATION.md)：支持平台、本地开发、单进程演示与安装验证。
- [使用说明](USAGE.md)：任务输入、附件、默认输出、刷新恢复和成果管理。
- [配置参考](CONFIGURATION.md)：环境变量、Provider、前端构建与配置不变量。

### 设计与演进

- [架构说明](ARCHITECTURE.md)：组件、单轮执行、数据布局、Skill 路由与安全边界。
- [Skill 编排契约](SKILL-ORCHESTRATION.md)：总控入口、子 Skill 交接、审计证据与当前强制边界。
- [独立知识提纯库开发文档（Draft）](KNOWLEDGE-REFINERY-CORE-DEVELOPMENT.md)：零 Harness 依赖核心、领域模型、证据、提纯、审核、版本、快照和查询契约。
- [独立知识提纯库开发步骤（Draft）](KNOWLEDGE-REFINERY-CORE-IMPLEMENTATION-PLAN.md)：Sprint 0–8、质量门、验收标准、前 30 天任务和 Harness 灰度条件。
- [知识决策系统开发文档（Draft）](KNOWLEDGE-DECISION-SYSTEM-DEVELOPMENT.md)：知识图谱、Skill 消费、核验、反馈闭环及整体产品架构。
- [知识决策系统敏捷方案（Draft）](KNOWLEDGE-DECISION-SYSTEM-AGILE-IMPLEMENTATION-PLAN.md)：完整系统从 PoC 到生产试点的上位实施节奏。
- [项目语料采集工作步骤（Draft）](PROJECT-CORPUS-ACQUISITION-WORKFLOW.md)：50–100 个公开项目语料的分级、许可、时点冻结、采集、质检和移交流程。
- [版本与升级指南](VERSIONING-AND-UPGRADES.md)：独立版本轴、升级要素、兼容性、迁移和回滚要求。
- [迭代原则](ITERATION-PRINCIPLES.md)：长期不变量、发布分级和 Definition of Done。
- [更新记录](../CHANGELOG.md)：按版本和 Build 记录已经发布与尚未发布的变化。
- [V0.2.1 发布说明](releases/v0.2.1/RELEASE-NOTES.md)：生产源码归档、版本身份修复和页面版本信息的公开摘要。
- [V0.2.0 发布说明](releases/v0.2.0/RELEASE-NOTES.md)：首次上线、刷新恢复与总控优先热修的公开摘要。
- 架构决策：
  - [ADR-0001：独立版本轴](adr/0001-version-axes.md)
  - [ADR-0002：双槽与数据隔离](adr/0002-dual-slot-data-isolation.md)
  - [ADR-0003：Controller-first](adr/0003-controller-first.md)
  - [ADR-0004：默认 Markdown + HTML](adr/0004-default-md-html.md)
  - [ADR-0005：Harness 插件、Skill 与知识层边界](adr/0005-harness-plugin-and-knowledge-boundaries.md)

### 验证与交付

- [测试与验收标准](TESTING-AND-ACCEPTANCE.md)：自动化、真实 E2E、文件验收、证据留存和放行门槛。
- [部署说明](DEPLOYMENT.md)：通用 Linux 单实例基线、不可变 release、升级与回滚。
- [安全政策](../SECURITY.md)：漏洞报告、数据与凭证边界。

### 迭代模板

- [迭代日志条目模板](templates/ITERATION-LOG-ENTRY.md)：记录问题、变更层、版本轴、验证、迁移和回滚。
- [发布检查清单](templates/RELEASE-CHECKLIST.md)：从仓库冻结到候选、切换、观察和证据归档的逐项检查。

## 单一可信源

不同信息按以下顺序确定权威来源：

1. 运行行为与 API：当前版本代码、配置 Schema 和自动化测试。
2. System Prompt：`backend/cordis.yml` 中的版本化 System Prompt。
3. Skill 行为：`skills/manifest.json` 和各 Skill 的 `SKILL.md`。
4. 版本变化：`CHANGELOG.md` 与不可变 release manifest。
5. 操作方法：本目录中的安装、配置、部署和验收文档。

历史发布记录只说明当时状态。后续行为变化应新增版本条目或明确标记“已被取代”，不要在历史记录中无痕改写结论。

## 文档更新规则

以下任一项变化时，必须在同一迭代更新对应文档：

- Application、System Prompt、Skill bundle、Schema 或 Build ID；
- 总控路由、默认输出、交付链或 fail-closed 条件；
- API、配置项、依赖、数据布局或部署拓扑；
- 测试基线、验收门槛、迁移方式或回滚方法；
- 能力支持范围、安全边界或已知限制。

公开文档只保留脱敏结论和通用示例。精确部署证据应由受控的发布档案保存，并通过校验值与公开发布说明关联。
