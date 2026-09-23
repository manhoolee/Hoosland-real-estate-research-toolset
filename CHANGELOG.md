# 更新记录

## 0.3.3 — 2026-09-23

- 将清单收口调整为审计状态，不再以清单完成进度、暂存状态或提交失败拒绝已通过文件可访问性检查的成果；记录收口告警并继续持久化非空交付回复。
- 文件与回复清单项根据服务端实际成果和最终回复复核；未完成任务仍保留为未完成状态。
- 保留文件持久化、文件可访问性、必需报告格式配对和安全输出检查。
- 同步线上 v0.3.2 源码与测试；后端存储及交付优先回归测试通过。

## 0.3.2 — 2026-09-16

- 修正购房政策、销售模型、项目供应商、营销工具及明确业务规则的防刺探误伤；业务对象识别只作用于对象片段，不放行同轮夹带的刺探。
- 修正公开网址中的 `/app/`、`/home/` 等普通路径误伤，继续拦截秘密文件、带凭据网址和秘密查询参数。
- 对不超过 16 MiB 的文本成果分块全文检查，超限文件不以局部检查冒充通过；改扩展名的纯文本仍接受检查。
- 文件检查转入后台线程；真实 PDF/Office 等二进制正文检测仍未覆盖。


## 0.3.1 — 2026-09-16

- 修复公开 HTTP(S) 来源 URL 被识别为 Windows / UNC 内部路径，导致 MD / HTML 从文件列表和下载接口消失。
- 聊天区展示真实成果的打开、下载入口，解析已登记成果的路径引用，兼容历史对话和移动端。
- 成功提交前检查本轮成果可访问性；默认报告检查同名 MD / HTML 配对及 HTML 结构，缺失时明确失败，单格式和不要文件的要求保留。


本项目分别记录应用、System Prompt、Skill 套件和数据 Schema 版本；它们不会为了展示一致而同步跳号。

## App 0.3.0（V0.3）Build `v0.3.0-guided-intake-20260830T125845Z` / Guided intake sidecar 1 / slot-a — 2026-08-30

### 发布身份与槽位边界

- Application、后端健康接口、前端展示和构建元数据统一升至 `0.3.0`（对外简称 `V0.3`）；
- 本版本登记到奇数迭代对应的 `slot-a`，前端构建固定使用 `/tools/real-estate` 和 `slot-a` 存储命名空间；
- `slot-b` 的 `0.2.6` 与 Build `v0.2.6-scope-gate-20260829T101331Z` 作为在线基线保留，不执行重启、迁移或写入；
- System Prompt `real-estate-system-v0.2.4`、Skill bundle `2.3.1`、Project state Schema `2.1.0`、usage/checklist sidecar Schema `1` 均保持不变；新增 Guided intake sidecar Schema `1`，无数据迁移。

### 任务类型引导式提问 MVP

- 新增本地、无 Token 的任务预检：根据任务类型展示最多 3 道透明决策题，每题提供 2–4 个有影响说明的选项，支持自定义补充、跳过直接执行和刷新恢复；
- 新增 `pending_intake.json` sidecar 与 `GET/POST/DELETE /api/conversations/{conversation_id}/intake`，确认前不污染消息、run、checklist 或 usage；sidecar 采用原子写入、正文/附件绑定、24 小时 TTL 和幂等清理；
- 确认后由服务端校验问题、选项、附件和答案，把结构化偏好作为用户数据块追加到原始请求；原始用户消息保持不变，失败重试可重建同一语义；
- 前端新增可访问的内嵌决策卡，覆盖键盘/触控、移动布局、推荐项说明和 `prefers-reduced-motion`；
- 新增引导纯函数、sidecar 和 HTTP 回归用例；本地后端回归由 159 项增加到 175 项，前端类型检查与生产构建通过（仍有既有主包体积提示）；
- 详细分类、灰度、指标、验收和回滚方案见 [`docs/GUIDED-INTAKE-ITERATION-PLAN.md`](docs/GUIDED-INTAKE-ITERATION-PLAN.md)。A 槽切换前仍需完成目标主机只读拓扑确认、隔离候选和真实 Provider E2E；未满足前不宣称稳定。

### 验证与发布状态

- 本地后端回归 175 项、Python 编译、前端 TypeScript 检查与生产构建均通过；
- Build 制品需在目标主机以不可变 release 方式安装，并只切换 A 的服务、环境和 Skill 绑定；
- 任何 A 探针失败只回滚 A，不得影响 B；切换完成后进入 `online / observing`，观察期通过后再标记 stable demo。

### 文档与架构

- 新增独立知识提纯库开发规格，明确知识核心零 Harness 依赖、Ports and Adapters、证据血缘、候选提纯、人工审核、不可变修订和知识快照。
- 新增 Sprint 0–8 实施计划，规定先独立验证提纯质量，再建立查询服务，最后以只读 MCP Adapter 灰度接入 DeepSeek Harness 和专业 Skill。
- 明确 X2Knowledge、Docling、MarkItDown 等只属于可替换的文档解析适配器，其 RAG 问答预处理不能作为正式 `KnowledgeUnit`。
- 本次仅更新规划和文档，没有实现知识提纯运行时、数据迁移或用户可见功能。

## Unreleased

暂无。

## App 0.2.6 Build `v0.2.6-scope-gate-20260829T101331Z` / Scope gate v1.1 / Egress gate v1 — 2026-08-29

### 对话边界与版本身份

- Application、后端健康接口、前端展示和构建元数据统一升至 `0.2.6`；
- 在地产项目任务之外，闲聊、运行信息/技能清单/模型与配置刺探，以及混入项目话术的后台、服务端、接口、版本和助手设定提取请求，均在进入 Harness 前本地拒绝，不消耗 Provider token；
- 增加最终文本与文件输出的 egress 过滤，命中内部运行标记时 fail closed，不把原始内容写入 SSE、历史或审计字段；
- System Prompt `real-estate-system-v0.2.4`、Skill bundle `2.3.1`、Project state Schema `2.1.0`、usage/checklist sidecar Schema `1` 均保持不变，无数据迁移；
- 本地 159 项后端回归、前端类型检查/生产构建、隔离候选和生产健康/路由/刺探 smoke 全部通过；旧 V0.2.5 release 保留为直接回滚点。

## App 0.2.5 Build `v0.2.5-todo-write-recovery-20260828T090530Z` / System Prompt v0.2.4 / Skill 2.3.1 / Checklist sidecar 1 — 2026-08-28

### todo/write 持久化拒绝恢复

- 保留 V0.2.4 的严格持久化门禁：首张预完成、单次批量完成、项目集合变化和无任务/成果的清单仍会被拒绝，不以模型或 Harness 的本地成功替代应用成功；
- 将拒绝原因改为有界类型；已有持久化基线的后续快照被拒时，应用读取最后一张已接受快照，把 revision、原因和权威 todos 作为同一根 Harness session 的服务端纠正指令回注；首张非法且没有 accepted items 时直接失败关闭；
- 纠正后的下一张快照必须与权威基线完全一致；在确认恢复前，其他实质工具和 final 都会 fail closed，重复不匹配不会继续发送纠正；
- 单轮最多处理 3 个彼此独立的拒绝事件，第 4 个事件以 `AGENT_CHECKLIST_RECOVERY_EXHAUSTED` 失败；存储、回注或协议异常也不会把运行误报为成功；
- 应用接管 pinned SDK 的单一 notification subscription，以 `agent/inbox/spliced` 回执界定每次注入；纠正回执尚未到达时忽略排队的旧 idle，只在后续根 idle 收口最终回复；
- 私有 operation log 只记录拒绝类型、attempt、revision 和结果，不保存任务正文、纠正 payload 或工具参数。

### 版本、兼容性与发布状态

- Application 从 `0.2.4` 升至 `0.2.5`，System Prompt 从 `real-estate-system-v0.2.3` 升至 `real-estate-system-v0.2.4`；Skill bundle `2.3.1`、Project state Schema `2.1.0`、usage sidecar Schema `1` 和 checklist sidecar Schema `1` 均不变；
- Python、Node、Harness、系统依赖、公开 API、环境变量和持久化 Schema 均未变化，无数据迁移；
- 精确源码 commit `914dc8f12a41a54ee2233f70834f24ed16330dcd` 的 GitHub Actions run `33157910758` 成功，本地与服务器端 132 项后端回归、Python 编译、前端类型检查/构建、`pip check` 和 Skill smoke 全部通过；
- Build 已于 `2026-08-28T09:36:50Z` 上线 V2 / slot-b。3092 隔离候选与生产公网真实 Provider E2E 均生成 2 个任务、3 项成果要求和 8 个 revision，并以 5 次逐项完成收口；两端重启持久化复验通过；
- 候选的真实 SDK wire gate 观察到 2 个 prompt 回执、2 张 todo 快照和 2 次 idle，最终只接受纠正后的回复。切换后本机、gateway 与公网 Ready 一致，`NRestarts=0`，高优先级与 recovery 失败日志为空；V1、Nginx、Skill 和公网 MCP 边界不变，V0.2.4 作为直接回滚点保留。

## App 0.2.4 Build `v0.2.4-task-checklist-20260828T043537Z` / System Prompt v0.2.3 / Skill 2.3.1 / Checklist sidecar 1 — 2026-08-28

### 任务清单与成果复核

- 直接从已上线 V0.2.3 记录 commit `34d831a4779c204f08f25009a4d5dba4edfb3582` 创建发布分支，部署源码为 `de24812edb0920d728b0e1ea7d9e0954218ef7ce`，未从旧 `main` 或根目录镜像回拷源码；
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
- 后端 124 项回归、Python 编译、前端类型检查与生产构建、Skill smoke，以及 1440/1024/375/320px 本地固定快照浏览器复核均通过；
- Build 已于 `2026-08-28T06:09:01Z` 上线 V2 / slot-b。隔离候选与生产公网真实 Provider E2E 均产生 2 个任务、3 项成果要求和 8 个 revision，并以 5 次逐项完成收口；两端重启后 checklist、assistant、sidecar、成果文件与 Token 用量精确保持。V1、Nginx 和 Skill 指纹前后相同，V0.2.3 作为直接回滚点保留。

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
