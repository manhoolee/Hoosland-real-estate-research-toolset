# 版本与升级指南

本项目采用多版本轴，而不是用一个展示版本代表全部组件。每次迭代必须说明改动发生在哪一层、对应版本是否变化、是否影响兼容性、如何验证以及怎样回滚。

## 1. 当前版本矩阵

| 版本轴 | 当前值 | 作用 |
|---|---:|---|
| 产品线 | V2 | 产品与界面代际，不作为可执行发布标识 |
| Application SemVer | `0.2.0` | 后端、前端和公开应用行为版本 |
| Build ID | `v0.2.0-controller-first-dual-output-20260825T081715Z` | 每次不可变构建的唯一标识 |
| System Prompt | `real-estate-system-v0.2.1` | 全局身份、安全、证据、权限和执行规则 |
| Skill bundle SemVer | `2.3.0` | 总控与 10 个专项 Skill 的协议集合 |
| Project state Schema | `2.1.0` | 持久化项目状态的数据契约 |

这些数字不要求同步。只修改 System Prompt 时不应为了视觉整齐而改写 Schema；只有持久化数据契约变化时才升级 Schema。

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
| Build ID | 每次构建和部署候选 | 唯一 ID、Git commit、manifest、SHA-256、前一回滚点 |

当前 Build 对运行编排、Ready 状态和用户可见默认交付行为做了修订，但 Application 仍保持 `0.2.0`；同时 Skill 内容发生变化而 manifest 仍为 `2.3.0`。这两项均登记为版本债务。下一次 canonical release 应至少升级 Application 到 `0.2.1`，Skill bundle 至少升级到 `2.3.1`，避免不同应用/Skill 行为继续共享同一 SemVer。

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

没有数据迁移也必须明确写出“Schema 未变化、无数据迁移”，防止后续维护者误判遗漏。

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

- Application、Build、System Prompt、Skill bundle 和 Schema 版本；
- Git commit、工作树状态和构建时间；
- 基线 Build 与完整变更文件清单；
- 源码、前端资产、Skill、依赖锁和发布脚本的 SHA-256；
- 数据迁移、配置变化和秘密处理结论；
- 自动化测试、候选 E2E、上线复验和观察状态；
- 前一稳定 release 与可执行回滚说明。

公开 release note 只保存脱敏摘要；包含内部拓扑或任务关联信息的原始证据必须进入访问受控的发布档案。

## 8. 当前 Build 的升级摘要

本次 controller-first / dual-output Build：

- System Prompt 从 `real-estate-system-v0.2.0` 升级为 `real-estate-system-v0.2.1`；
- 应用每轮确定性提交总控入口命令，缺少总控文件时 fail closed；会话首行证明命令已提交，operation/E2E 证明后续子链，当前没有独立的总控正文加载回执；
- Prompt/Skill 契约规定子 Skill 由总控统一调用和去重，下游交接改为返回下一节点需求；
- 默认主报告输出改为同轮 Markdown + HTML，并增加基于实际文件的格式审计；
- 后端回归扩展为 86 项并全部通过；
- Application SemVer、Skill manifest、Schema、既有公开 API 路径、前端和依赖均未变化；Ready/runtime 状态增加向后兼容的总控配置字段；
- 没有数据迁移，旧 Build、Skill 和配置应作为回滚点保留。

