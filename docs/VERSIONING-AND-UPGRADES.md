# 版本与升级指南

本项目采用多版本轴，而不是用一个展示版本代表全部组件。每次迭代必须说明改动发生在哪一层、对应版本是否变化、是否影响兼容性、如何验证以及怎样回滚。

## 1. 当前版本矩阵

| 版本轴 | 当前值 | 作用 |
|---|---:|---|
| 产品线 | V2 | 产品与界面代际，不作为可执行发布标识 |
| Application SemVer | `0.2.6` | 后端、前端和公开应用行为版本；已上线 V2 / slot-b |
| Build ID | `v0.2.6-scope-gate-20260829T101331Z` | 从前一线上 Build 精确派生并完成原子切换 |
| System Prompt | `real-estate-system-v0.2.4` | 全局身份、安全、证据、权限、任务复核和执行规则 |
| Skill bundle SemVer | `2.3.1` | 总控与 10 个专项 Skill 的协议集合 |
| Project state Schema | `2.1.0` | Skill 使用的持久化 project_state / case payload 契约 |
| Conversation usage sidecar Schema | `1` | 可选 `usage.json` accounting projection |
| Run checklist sidecar Schema | `1` | 按 run 保存任务与成果复核快照 |

这些数字不要求同步。只修改 System Prompt 时不应为了视觉整齐而改写 Project state Schema；新增不参与 project_state / case payload 的持久化 sidecar，应建立并维护自己的 Schema 轴，避免迫使无关的 Skill 契约跳号。V0.2.4 因此为运行清单建立独立 sidecar Schema `1`，不借用 usage 或 project state 的版本号；V0.2.5 改变拒绝后的运行协调，V0.2.6 增加对话 scope/egress 门禁，sidecar 字段和复核语义均不变，因此继续使用 Schema `1`。

V0.2.2 的 `usage.json` 使用独立 sidecar Schema `1`。文件缺失等价于 0，应用在首次收到新 usage 时惰性创建，旧 V0.2.1 会忽略它；不需要迁移，但升级前的历史 Token不会被推算或回填。Skill 所消费的 project_state / case payload 继续为 `2.1.0`，此次没有修改 case 文件或 Skill 契约。

## 2. 当前行为契约

### 2.1 Controller-first

Application 在每轮提交 Harness 前，以首行 slash command 确定性提交 `comprehensive-real-estate-expert` 入口命令；总控是否实际加载需由 Harness 会话或集成验收确认。Prompt/Skill 契约规定总控负责：

- 识别任务范围和证据许可；
- 调用一个或多个必要子 Skill；
- 维护本轮子 Skill 去重；
- 接收子 Skill 返回的下一节点需求；
- 组织正式交付链和最终 QA。

子 Skill 不得调用总控自身，也不得绕过总控直接编排下游。配置的 Skill 根目录缺少总控时，Ready 与运行必须 fail closed。

### 2.2 默认双格式

当主成果属于地产研究、项目分析、策划方案或管理报告，且用户没有指定最终格式时，同一轮默认生成：

- 内容对应的 Markdown；
- 同内容、独立且可离线打开的 HTML。

两份文件应使用一致的主名，实际存在、非空并可打开。PDF 不属于默认格式；用户明确指定单一格式、其他格式或不要文件时尊重用户要求。微信资料归档、社交平台素材和数据模型等专项任务按各自契约执行，除非同一任务还要求形成主报告。

## 3. 各版本轴的升级条件

| 版本轴 | 何时升级 | 必须同时完成 |
|---|---|---|
| Application | API、运行编排、UI、持久化实现或用户可见应用行为变化 | SemVer 判断、回归测试、兼容性和部署说明 |
| System Prompt | 全局身份、安全、证据、权限、路由或执行真实性规则变化 | 新 prompt version、对抗/回归用例、CHANGELOG |
| Skill bundle | Skill 内容、输入输出、交接协议、方法或质量闸门变化 | manifest 版本、Skill smoke、总控链路 E2E |
| Schema | 持久化字段、含义、约束或读取兼容性变化 | 迁移器或重建路径、备份、前向/回滚验证 |
| Conversation usage sidecar | `usage.json` 字段、计数语义、去重身份或读取默认值变化 | sidecar version、兼容读取、持久化与回滚测试 |
| Run checklist sidecar | 清单 item、状态、revision、run 绑定、终态复核或读取兼容性变化 | sidecar version、事件乱序/隔离、恢复、终态与回滚测试 |
| Build ID | 每次构建和部署候选 | 唯一 ID、Git commit、manifest、SHA-256、前一回滚点 |

V0.2.2 将 Application 从 `0.2.1` 升至 `0.2.2`，新增对话 Token 用量统计、持久化和显示。System Prompt 继续为 `real-estate-system-v0.2.1`，Skill bundle 继续为 `2.3.1`，Project state Schema 继续为 `2.1.0`。新增独立的 Conversation usage sidecar Schema `1`；旧对话惰性创建，无迁移，历史 Token 不回填。

## 4. 升级要素矩阵

每次迭代至少评估下列要素。明确写“无变化”也属于必要记录。

| 要素 | 需要回答的问题 | 主要证据 | 回滚单位 |
|---|---|---|---|
| 业务目标 | 修复了哪个真实任务问题，成功标准是什么 | 需求与标准用例 | 整个候选 Build |
| Application | API、任务恢复、文件或 UI 是否变化 | 代码 diff、单元/HTTP/前端测试 | Application release |
| System Prompt | 全局规则是否变化，是否产生职责重复 | prompt diff、对抗测试 | Cordis 随 release 回滚 |
| Skill | 总控、子 Skill、链路或输出契约是否变化 | manifest、Skill diff、smoke、操作链 | 版本化 Skill bundle |
| Schema 与数据 | 是否需要迁移，旧数据能否读取，能否降级 | schema diff、迁移/恢复测试 | 数据快照与旧代码 |
| 配置 | 是否新增、删除或改变环境变量含义 | 脱敏配置差异、启动探针 | 前一版本配置 |
| 依赖 | Python、Node、Harness 或系统依赖是否变化 | lock/freeze、依赖检查、构建日志 | release 自带依赖 |
| 输出 | 默认格式、文件结构、预览或下载是否变化 | 文件 hash、打开/渲染记录 | 旧行为 Build |
| 安全 | 权限、秘密、日志、外部动作或公网边界是否变化 | 安全测试、脱敏审计 | 受影响配置与 release |
| 部署 | 服务、端口、代理、槽位或健康检查是否变化 | 候选探针、切换记录 | 前一不可变 release |

## 5. 兼容性分类

每个版本条目必须选择一种分类：

- **兼容**：旧配置和旧数据可直接继续使用，公开行为没有破坏性变化。
- **条件兼容**：需要新增配置、重建前端或执行可逆迁移；必须列明前置条件。
- **不兼容**：API、配置或数据契约无法直接沿用；必须给出迁移器、人工迁移或重新初始化路径。

没有批量数据迁移也必须明确写出 Schema 是“未变化”还是“兼容升级并惰性创建”，以及历史数据是否回填，防止后续维护者把迁移策略误判为遗漏。

## 6. 标准升级流程

1. **登记**：复制迭代日志模板，写清目标、影响层、版本轴和成功标准。
2. **冻结基线**：记录 Git commit、当前版本矩阵、测试基线和前一回滚点。
3. **实现**：只修改登记范围；同时更新代码、测试和相关文档。
4. **构建候选**：创建新的不可变 Build ID，生成 manifest 与 SHA-256。
5. **自动化验证**：运行后端、编译、前端和 Skill 测试；任何失败都阻止候选放行。
6. **真实 E2E**：在隔离候选环境验证真实模型、总控链、输出文件和受影响 Provider。
7. **切换**：确认没有不应中断的活动任务后，原子切换受影响槽位；失败自动回滚。
8. **上线复验**：核对 Build、能力、公开入口和真实最小任务，不以健康检查代替业务 E2E。
9. **观察与归档**：记录告警、错误、资源和回滚状态；关闭观察期后再提升发布等级。

## 7. Release manifest 最低字段

每个不可变 release 至少记录：

- Application、Build、System Prompt、Skill bundle、Project state Schema 和 Conversation usage sidecar Schema 版本；
- Git commit、工作树状态和构建时间；
- 基线 Build 与完整变更文件清单；
- 源码、前端资产、Skill、依赖锁和发布脚本的 SHA-256；
- 数据迁移、配置变化和秘密处理结论；
- 自动化测试、候选 E2E、上线复验和观察状态；
- 前一稳定 release 与可执行回滚说明。

公开 release note 只保存脱敏摘要；包含内部拓扑或任务关联信息的原始证据必须进入访问受控的发布档案。

## 8. 当前 Build 的升级摘要

V0.2.5 todo/write recovery（Build ID：`v0.2.5-todo-write-recovery-20260828T090530Z`）：

- 以线上 V0.2.4 记录 commit `6351cd2622a6903796a24e655ab2a98c02005fb1` 为父基线，发布分支为 `release/v0.2.5-todo-write-recovery`，部署源码 commit 为 `914dc8f12a41a54ee2233f70834f24ed16330dcd`；
- Application 升至 `0.2.5`，System Prompt 升至 `real-estate-system-v0.2.4`；Skill bundle、Project state Schema、usage sidecar 与 checklist sidecar Schema 均不变；
- 持久化层仍拒绝非法快照；已有 accepted baseline 时，应用把最后一张已接受快照作为同一根 Harness session 的权威纠正，要求精确重置，并以 prompt receipt 和后续 root idle 封闭完整纠正 turn；首张非法且没有基线时直接失败关闭；
- recovery pending 时禁止其他实质操作和 final；注入、存储、协议或重复恢复失败均 fail closed，无配置、依赖或数据迁移；
- 已于 `2026-08-28T09:36:50Z` 上线 V2 / slot-b；直接回滚点为完整 V0.2.4 release。

### 前一线上与直接回滚 Build

V0.2.4 task checklist（Build ID：`v0.2.4-task-checklist-20260828T043537Z`）：

- 以线上 V0.2.3 部署记录 commit `34d831a4779c204f08f25009a4d5dba4edfb3582` 为唯一父基线，发布分支为 `release/v0.2.4-task-checklist`，部署源码 commit 为 `de24812edb0920d728b0e1ea7d9e0954218ef7ce`；
- Application 升至 `0.2.4`，System Prompt 升至 `real-estate-system-v0.2.3`，首次建立 Run checklist sidecar Schema `1`；
- 使用 Harness 原生 `todo_write` / `todo/write` 建立任务与成果要求的整表快照，并在 SSE、消息与恢复链路中发送完整 revision；
- 已于 `2026-08-28T06:09:01Z` 上线 V2 / slot-b；V0.2.5 上线后作为直接回滚点保留。

### 更早线上 Build

V0.2.3 output persistence Build（Build ID：`v0.2.3-output-persistence-20260828T040220Z`）：

- Application 从 `0.2.2` 升至 `0.2.3`，System Prompt 从 `real-estate-system-v0.2.1` 升至 `real-estate-system-v0.2.2`；Skill bundle `2.3.1`、Project state Schema `2.1.0` 与 usage sidecar Schema `1` 不变；
- 动态 runtime context 与每轮绝对工作区注入共同固定唯一 `workspace/outputs`，明确禁止使用 `/tmp`、嵌套 outputs 或 shell `${PWD}/outputs` 作为正式交付目录；
- 后端在写入成功状态和发送最终消息前，对本轮 output write 意图与真实顶层 outputs 指纹进行核对；缺失或格式不完整时返回可重试失败；
- 不复制共享临时目录，不自动提升来源不确定的文件，不修改历史 conversation；回滚单位是整个 V0.2.3 应用与匹配的 System Prompt；
- V1 / slot-a 不变，V0.2.2 Token 统计与 usage sidecar 继续兼容。

### 更早 Build

V0.2.2 Token usage visibility Build（Build ID：`v0.2.2-conversation-token-usage-20260828T023809Z`）：

- Application 从 `0.2.1` 升至 `0.2.2`；System Prompt `real-estate-system-v0.2.1` 与 Skill bundle `2.3.1` 不变；
- 后端从 Harness 持久事件提取 Provider usage，按 conversation 汇总主 Agent、子 Agent、实际重试 attempt 与成功压缩调用；同一 attempt 的 chunk/final 使用后值替换，reasoning 只作 output 明细；
- 新增 `GET /api/conversations/{conversation_id}/usage` 与 SSE `usage` snapshot，前端在输入框上方显示当前对话累计 Token；
- `usage.json` 是可选 accounting sidecar，Schema 为 `1`；旧对话缺失时返回 0并在新 usage 到达时惰性创建，无迁移且不回填历史 Token；Project state Schema 保持 `2.1.0`；
- Python requirements、Node dependencies、System Prompt、Skill 内容和现有项目/案例状态字段不变；
- 自动化覆盖用量替换、重试、子 Agent、压缩、取消、持久化、旧数据和对话隔离；发布前仍需使用真实 Provider 完成最小验收；
- 回滚到 V0.2.1 时无需删除 `usage.json`；旧应用不会读取或更新它。后续再切回 V0.2.2 可继续使用回滚前的统计，但 V0.2.1 运行期间的 Token 会形成不可恢复的缺口。
