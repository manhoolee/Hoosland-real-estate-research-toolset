# 更新记录

本项目分别记录应用、System Prompt、Skill 套件和数据 Schema 版本；它们不会为了展示一致而同步跳号。

## Unreleased

### 文档与架构

- 新增独立知识提纯库开发规格，明确知识核心零 Harness 依赖、Ports and Adapters、证据血缘、候选提纯、人工审核、不可变修订和知识快照。
- 新增 Sprint 0–8 实施计划，规定先独立验证提纯质量，再建立查询服务，最后以只读 MCP Adapter 灰度接入 DeepSeek Harness 和专业 Skill。
- 明确 X2Knowledge、Docling、MarkItDown 等只属于可替换的文档解析适配器，其 RAG 问答预处理不能作为正式 `KnowledgeUnit`。
- 本次仅更新规划和文档，没有实现知识提纯运行时、数据迁移或用户可见功能。

## App 0.2.2 Build `v0.2.2-conversation-token-usage-20260828T023809Z` / System Prompt v0.2.1 / Skill 2.3.1 / Usage sidecar 1 — 2026-08-28

### 对话 Token 消耗

- 按 `conversation_id` 累计 Harness 可观察到的 Provider usage，并在输入框上方显示当前对话累计 Token；
- 新增 `GET /api/conversations/{conversation_id}/usage`，消息 SSE 同步发送初始与增量 `usage` snapshot，刷新和切换对话后可恢复；
- 统计包含主 Agent、SDK 通知树中的子 Agent、实际开始的重试 attempt，以及成功落盘的 `compaction/summary`；
- 同一 attempt 的 usage chunk 与最终 assistant message 使用后值替换，不重复累计；`reasoning_tokens` 保留为 `output_tokens` 子项明细，不再次加入 `total_tokens`；
- 取消、失败和服务重启前已经持久化的 usage 保留；旧事件重放通过 session event seq 去重。

### 数据与兼容性

- Application 从 `0.2.1` 升至 `0.2.2`；System Prompt 保持 `real-estate-system-v0.2.1`，Skill bundle 保持 `2.3.1`；
- 每个 conversation 可新增独立、可选的 `usage.json` accounting sidecar；旧对话没有该文件时返回 0，旧 V0.2.1 会忽略该文件；
- Project state Schema 保持 `2.1.0`；`usage.json` 使用独立 Conversation usage sidecar Schema `1`，缺失等价于 0并可惰性创建，因此无迁移；升级前的历史 Token 不回填；
- 回滚到 V0.2.1 时保留 sidecar，无需删除或改写 conversation 数据；V0.2.1 不会更新统计，重新升级后会留下回滚期间不可恢复的用量缺口；
- Python requirements、Node dependencies、System Prompt 与 Skill 内容均未变化。

### 验证

- 后端单元与 HTTP 回归：94 项全部通过；
- Python 编译、前端 TypeScript 检查与生产构建：通过；
- 自动化覆盖 chunk/final 替换、重试、子 Agent、压缩、取消、持久化、旧对话缺省、404 与 conversation 隔离；
- 候选 Build 已冻结为 `v0.2.2-conversation-token-usage-20260828T023809Z`；正式切换前后均需补充真实 Provider 验收证据。

## App 0.2.1 Build `v0.2.1-production-sync-version-info-20260827T062425Z` / Skill 2.3.1 — 2026-08-27

### 生产基线与版本身份

- 以当前服务器已验证行为为基线，将 controller-first、总控缺失失败关闭、默认 Markdown + HTML 和输出格式审计正式提交到 Git，使 GitHub 可以重建线上核心行为；
- Application 从 `0.2.0` 升至 `0.2.1`，Skill bundle 从 `2.3.0` 升至 `2.3.1`，关闭上一热修使用旧 SemVer 承载新行为的版本债务；
- System Prompt 保持 `real-estate-system-v0.2.1`，Project state Schema 保持 `2.1.0`，无数据迁移；
- 修正发布闭环：新 Build 生成新的语义清单与 SHA-256，不复制或原地修补上一不可变 release 中已经过期的发布说明。

### 页面版本档案

- 品牌区增加可见版本号和 GitHub 源码按钮，桌面端直接展示，窄屏把版本号收进楼宇标识；
- 点击版本号或楼宇标识可查看迭代名称、发布日期、兼容性、本次修改内容和完整更新记录；
- 页面读取 `/api/health/live`，展示后端实时 Application 与精确 Build ID，避免只有前端硬编码版本；
- 版本档案支持 Escape、点击遮罩关闭、焦点返回、键盘焦点环与减少动画偏好；外部链接使用新标签安全属性。

### 验证

- 后端单元与 HTTP 回归：86 项全部通过；
- Python 编译、前端 TypeScript 检查与生产构建：通过；
- Skill v2.3.1 manifest、11 个 `_meta.json` 与 smoke tests：通过；
- 浏览器在 1440、1024、375 和 320px 验证无横向溢出，版本弹层完整，控制台无错误；
- Python requirements、Node dependencies、Nginx、既有公开业务 API 与持久数据布局未变化。

## App 0.2.0 Build `v0.2.0-controller-first-dual-output-20260825T081715Z` / System Prompt v0.2.1 — 2026-08-25

### 发布身份与兼容性

- 产品线与应用版本继续为 V2 / `0.2.0`，以唯一 Build ID 识别本次热修；由于运行编排、Ready 状态和默认交付行为已变化而未提升 patch，这也是需在下一 canonical release 升至至少 `0.2.1` 的版本债务；
- System Prompt 从 `real-estate-system-v0.2.0` 升级为 `real-estate-system-v0.2.1`；
- Skill manifest 仍为 `2.3.0`，但生产通过版本化 Skill 目录与 Build ID 绑定本次内容修订；下一次内容变更应正式升级到 `2.3.1` 或更高版本；
- 项目状态 Schema 继续为 `2.1.0`，没有数据迁移；前端、Python requirements、Nginx 与既有公开 API 路径未变更，Ready/runtime 状态仅新增向后兼容的总控配置字段。

### 总控路由与默认报告格式

- System Prompt 升级为 `real-estate-system-v0.2.1`；
- 应用每轮首行确定性提交 `comprehensive-real-estate-expert` 总控命令，再由总控按 Prompt/Skill 契约调用并去重子 Skill；缺少总控文件时 Ready 与运行均 fail closed；
- 地产研究、项目分析、策划方案和管理报告在用户未指定格式时默认生成 Markdown 与独立 HTML，专项转换、归档、社交素材和数据模型保留各自输出契约；
- operation log 新增总控注入准备事件，并按本轮文件变更记录实际输出格式，便于回归检测；
- 编辑、设计、PDF、社交和微信子 Skill 改为向总控返回下一节点请求，不再自行调用下游 Skill。

### 验证与上线

- 后端单元/HTTP 回归扩展为 86 项并全部通过，Python 编译与 Skill smoke 通过；
- 候选与生产公网均以同一“广州越秀地产阅璟台”任务完成真实 E2E；有效链为总控 → 研究 → 编辑 → 设计 → QA，子 Skill 无重复或失败；
- 两次 E2E 均实际生成并打开同轮 Markdown 与独立 HTML，默认未误调用 PDF；
- 槽 B 原子切换成功，槽 A、Nginx、共享依赖、持久数据与既有运行配置未变更；旧应用 release、旧 Skill 与环境配置均保留用于回滚。

### 安装与部署文档

- 新增独立安装指南，明确本地开发、单进程演示、WSL2 和支持平台；
- 把 Linux 基线补齐为从主机初始化到 release、配置、systemd、Nginx、验收、备份、升级和回滚的闭环；
- 每个不可变 release 使用独立 `.venv`，源码、前端与 Python 依赖可以一起回滚；
- 明确反向代理访问控制、`APP_API_TOKEN` 的 SPA 限制、`/mcp` 阻断和 PDF 系统依赖；
- Docker、多副本和原生 Windows 后端继续标记为未完成真实运行时验收，不做超前承诺。

> 上述安装/部署文档描述的是长期推荐基线；本次既有槽 B 生产热修沿用已验收的共享 venv，requirements 未变化，没有在本次发布中执行 venv 迁移。

### 文档与追溯

- 新增文档索引、Skill 编排契约、版本与升级指南、测试与验收标准；
- 新增版本轴、双槽隔离、controller-first 和默认 Markdown + HTML 四份 ADR；
- 新增 V0.2 脱敏 Release Notes，以及后续迭代日志和发布检查清单模板；
- 精确 Build ID 可以进入公开 Release Notes；运行 ID、服务器路径、内部文件哈希与回滚锚点由受控发布档案保存。

## App 0.2.0 / Skill 2.3.0 — 2026-08-25

### Agent 合成

- 确立 `LLM + Harness = Agent；Agent + Skill = Domain Tools` 的四层架构；
- 使用 DeepSeek Harness Python SDK 与 Cordis 组合模型、沙箱、文件、会话、搜索和 Skill 路由；
- 固化 `real-estate-system-v0.2.0`，统一身份、安全、证据、权限和执行真实性；
- 集成 11 个房地产 Skill，Skill bundle 升级到 `2.3.0`；
- 项目状态 Schema 继续保持 `2.1.0`，兼容既有 case state。

### 应用

- 新增 FastAPI + React 工作台、项目、多对话、附件和成果管理；
- 使用 REST + SSE 提供长任务进度与最终结果；
- 增加 content-free `run.json`、请求 ID 和一致性对账，支持刷新恢复并防止重复模型任务；
- 增加取消、失败重试、多标签竞态处理和后台结果回填；
- 增加管理员配置、Provider 密钥加密和最小化 operation log；
- 增加 conversation 绑定的内部 MCP token 与五类可选能力适配器。

### 正式交付

- 固化“业务专项 → 编辑 → 设计 → 按需 PDF → 最终 QA”链路；
- 新增 `hoosland-pdf-output`，负责 HTML → PDF 与逐页技术质检；
- 补强产品测算的输入依据、单位、公式、舍入和审计字段；
- 微信归档、社交传播和客户正文纯净边界进一步收紧。

### 验证

- 初始实现阶段为 73 个后端测试；刷新恢复与幂等加固后扩展为 83 个；
- 该阶段源码快照通过 83 个后端单元测试、Python 编译、前端类型检查与生产构建；
- Skill v2.3 smoke tests 通过。

## 历史 Skill 版本

Skill v2.1 与 v2.2 的历史方法和说明仍可在原 Skill 仓库历史中查阅；本统一仓库从 App 0.2.0 / Skill 2.3.0 开始维护。
