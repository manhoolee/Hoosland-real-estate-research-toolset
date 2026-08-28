# 更新记录

本项目分别记录应用、System Prompt、Skill 套件和数据 Schema 版本；它们不会为了展示一致而同步跳号。

## Unreleased

### 文档与架构

- 新增独立知识提纯库开发规格，明确知识核心零 Harness 依赖、Ports and Adapters、证据血缘、候选提纯、人工审核、不可变修订和知识快照。
- 新增 Sprint 0–8 实施计划，规定先独立验证提纯质量，再建立查询服务，最后以只读 MCP Adapter 灰度接入 DeepSeek Harness 和专业 Skill。
- 明确 X2Knowledge、Docling、MarkItDown 等只属于可替换的文档解析适配器，其 RAG 问答预处理不能作为正式 `KnowledgeUnit`。
- 本次仅更新规划和文档，没有实现知识提纯运行时、数据迁移或用户可见功能。

## App 0.2.4 Candidate Build `v0.2.4-task-checklist-20260828T043537Z` / System Prompt v0.2.3 / Skill 2.3.1 / Checklist sidecar 1 — 2026-08-28

### 任务清单与成果复核

- 直接从已上线 V0.2.3 commit `34d831a4779c204f08f25009a4d5dba4edfb3582` 创建候选分支，未从旧 `main` 或根目录镜像回拷源码；
- 挂载锁定 Harness `0.1.1rc1` 的原生 `todo_write`，要求根 Agent 在实质执行前把用户请求拆成任务与成果要求，并在每项复核后立即整表更新；
- 应用只接受成功后的 `todo/write` 事件，按 `run_id` 持久化 revision 快照，通过 SSE、刷新恢复、历史消息、取消、失败和重试显示同一份清单；
- 后端硬性拒绝首清单前实质操作、首张预完成和单 revision 批量完成；success 前至少观察一次首张后的逐项完成更新；
- 终态保留所有已完成与未完成项；文件成果要求还需同时满足模型已复核完成和本轮 canonical `outputs` 存在对应新增或更新格式；
- checklist 使用内部 committing 与幂等补偿协议，只有 checklist、assistant、run 三者都持久化后才发送成功事件；
- 原四阶段进度保留为概览，消息内新增“任务清单 / 成果要求”双分组状态账本。

### 版本、兼容性与发布状态

- Application 从 `0.2.3` 升至 `0.2.4`，System Prompt 从 `real-estate-system-v0.2.2` 升至 `real-estate-system-v0.2.3`；Skill bundle `2.3.1`、Project state Schema `2.1.0` 与 usage sidecar Schema `1` 不变；
- 首次引入 Run checklist sidecar Schema `1`，只为新 run 惰性创建，不写入 `run.json`，不回填旧任务；回滚到 V0.2.3 时旧应用会忽略该 sidecar；
- Python、Node、Harness 和系统依赖版本不变；
- 候选已通过后端 124 项回归、Python 编译、前端类型检查与生产构建、Skill smoke，以及 1440/1024/375/320px 本地固定快照浏览器复核；
- 当前仍未部署。线上 V2 / slot-b 在完成真实 Provider 流式 E2E、隔离候选部署和原子切换前继续运行 Build `v0.2.3-output-persistence-20260828T040220Z`。

## App 0.2.3 Build `v0.2.3-output-persistence-20260828T040220Z` / System Prompt v0.2.2 / Skill 2.3.1 / Usage sidecar 1 — 2026-08-28

### 成果文件持久化

- 修复 persistent Bash 切换目录后，文件工具可能把 `/tmp/**/outputs` 或嵌套 `outputs` 误当正式交付目录的问题；
- 每轮 Prompt 注入唯一会话 `workspace`、`work` 与 `outputs` 绝对路径，并明确 Bash `cd` 不改变文件工具的会话根；
- Cordis 恢复动态 runtime context，使模型能够持续看到 canonical session workspace；
- 新增成功前硬门禁：本轮尝试生成的每个输出目标没有完整写入顶层 `workspace/outputs` 时，任务变为可重试失败，不发送错误的成功结果；
- 私有审计只记录尝试数量、格式和路径分类，不记录客户文件名或原始路径。

### 兼容性与验证

- Application 从 `0.2.2` 升至 `0.2.3`，System Prompt 从 `real-estate-system-v0.2.1` 升至 `real-estate-system-v0.2.2`；Skill bundle、Project state Schema 和 usage sidecar Schema 均不变；
- 不迁移、不覆盖现有 conversation、成果文件或 Token 用量；V1 / slot-a 不在发布范围内；
- Build `v0.2.3-output-persistence-20260828T040220Z` 已上线 V2 / slot-b；后端 102 项单元与 HTTP 回归、Python 编译、前端类型检查、生产构建、隔离候选和生产真实 Provider E2E 均通过；同名 Markdown/HTML 更新后的哈希发生变化，API 与磁盘一致，V2 重启后文件和 Token 统计保持，V1 前后快照一致。

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
- Build `v0.2.2-conversation-token-usage-20260828T023809Z` 已上线 V2 / slot-b；隔离候选与生产均完成真实 Provider Token E2E，SSE/读取接口一致，服务重启后统计保持，V1 前后快照一致。

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
