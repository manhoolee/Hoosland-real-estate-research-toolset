# ADR-0001：版本轴独立演进

- 状态：Accepted
- 日期：2026-08-25

## 背景

工作台同时包含应用代码、System Prompt、Skill 套件、持久化项目状态和具体构建产物。它们变化的原因、兼容性含义和回滚边界不同。如果用一个版本号覆盖全部层次，会出现以下问题：

- Prompt 行为变化被误解为数据 Schema 变化。
- Skill 内容升级无法与应用二进制或构建产物准确对应。
- 为了展示数字一致而无意义地改写持久化状态版本。
- 回滚时无法判断需要恢复应用、Skill、数据还是全部内容。

## 决策

项目独立维护七个版本轴：

| 版本轴 | 表达内容 | 何时升级 |
|---|---|---|
| Application SemVer | API、应用行为、前后端功能 | 应用发布按 SemVer 规则升级 |
| System Prompt version | 全局身份、安全、证据、编排与交付规则 | 全局 Prompt 语义变化时升级 |
| Skill bundle SemVer | Skill manifest、领域方法和交接契约 | Skill 内容或套件接口变化时升级 |
| Project state Schema version | 持久化项目/案例数据契约 | 只有持久化 Schema 变化时升级 |
| Conversation usage sidecar Schema | 对话 Token accounting projection | `usage.json` 字段或计数语义变化时升级 |
| Run checklist sidecar Schema | 每次运行的任务与成果复核快照 | `checklists/<run_id>.json` 字段或复核语义变化时升级 |
| Build ID | 一次不可变构建及其部署身份 | 每次可部署构建均生成唯一值 |

Build ID 必须能够关联构建清单、文件校验值和源代码修订。它不是 API 版本，也不能替代 SemVer。

## V0.2 版本矩阵

| 轴 | V0.2 当前值 | 说明 |
|---|---:|---|
| Application | `0.2.5` | 从前一线上 V0.2.4 精确派生，现已上线 V2 / slot-b |
| System Prompt | `real-estate-system-v0.2.4` | 明确本地 todo 成功不等于应用持久化成功，并要求执行权威纠正 |
| Skill bundle | `2.3.1` | 本次未修改 Skill 内容或套件接口 |
| Project state Schema | `2.1.0` | 无数据结构变化，无迁移 |
| Conversation usage sidecar Schema | `1` | 字段与计数语义未变化 |
| Run checklist sidecar Schema | `1` | 按 run 惰性创建；旧应用忽略，不回填历史运行 |
| Build ID | 每个构建唯一 | 由发布清单记录，不在本文固定具体值 |

V0.2 热修改变了应用运行编排、Ready 状态和用户可见默认交付行为，却仍沿用 Application `0.2.0`；Skill 内容也发生修订但 manifest 仍为 `2.3.0`。这两项都是已记录的发布事实与版本债务，不应成为后续惯例。下一次 canonical release 应至少升级 Application 到 `0.2.1`、Skill bundle 到 `2.3.1`。

V0.2.1 canonical release 已按该决策把 Application 提升为 `0.2.1`、Skill bundle 提升为 `2.3.1`。System Prompt 与 Project state Schema 没有变化，继续分别使用 `real-estate-system-v0.2.1` 与 `2.1.0`；历史 V0.2.0 版本债务记录保留，不倒改旧发布事实。

V0.2.2 新增每个 conversation 可选的 `usage.json` Token accounting sidecar，并建立独立 Schema `1`。Project state Schema 继续为 `2.1.0`，因为 Skill 的 project_state / case payload 字段、含义和校验均未变化；Skill bundle 因此也继续为 `2.3.1`。Sidecar 缺失可按 0 读取、在首次新 usage 时惰性创建，旧 V0.2.1 会忽略它；不运行迁移，也不推算或回填升级前的历史 Token。回滚到 V0.2.1 时 sidecar 保留但停止更新，重新升级会保留一段不可恢复的统计缺口。

V0.2.3 修改了运行编排、成功终态条件与全局工作区规则，因此 Application 升至 `0.2.3`，System Prompt 升至 `real-estate-system-v0.2.2`。Skill 内容、Project state Schema 和 usage sidecar 计数语义均未变化，继续使用 `2.3.1`、`2.1.0` 和 sidecar Schema `1`。

V0.2.4 从线上 V0.2.3 对应记录 commit `34d831a4779c204f08f25009a4d5dba4edfb3582` 直接派生，部署源码 commit 为 `de24812edb0920d728b0e1ea7d9e0954218ef7ce`。Application 升至 `0.2.4`，System Prompt 升至 `real-estate-system-v0.2.3`，新增按 run 隔离的 checklist sidecar Schema `1`；Skill bundle、Project state Schema 与 usage sidecar Schema 均不变化。该 sidecar 只为新运行惰性创建，不回填旧对话；回滚到 V0.2.3 时文件可保留并由旧代码忽略。

V0.2.5 从线上 V0.2.4 记录 commit `6351cd2622a6903796a24e655ab2a98c02005fb1` 直接派生，部署源码 commit 为 `914dc8f12a41a54ee2233f70834f24ed16330dcd`。Application 升至 `0.2.5`，System Prompt 升至 `real-estate-system-v0.2.4`；已有 accepted baseline 时，拒绝后的权威纠正、prompt receipt 和后续 root idle 都是运行协调状态，不写入 checklist sidecar；首张非法而无基线时直接失败关闭。因此 Skill bundle、Project state Schema、usage sidecar Schema 与 Run checklist sidecar Schema 均不变化，也不执行数据迁移。

## 兼容性规则

- Application 或 Prompt 升级不得自动改写 Project state Schema。
- Conversation usage sidecar 的变化不得借用 Project state Schema 或 Skill bundle 版本表达；必须记录独立 sidecar Schema 的兼容性。
- Run checklist sidecar 的变化不得写入 content-free 的 `run.json`，也不得借用 Project state Schema、usage sidecar 或 Skill bundle 版本表达。
- Schema 升级必须提供兼容范围、备份、迁移或重新初始化说明。
- Skill bundle 与应用必须在发布清单中记录已验证的组合。
- 只要应用与 Skill 的编排契约共同变化，回滚时必须恢复经过验证的成对组合。
- 前端、依赖或公开 API 未变化时应明确写“未变化”，不能用缺少记录代替结论。

## 后果

正面影响：

- 版本含义清晰，能够判断每次升级影响哪一层。
- 数据迁移只在必要时发生。
- 发布与回滚可以恢复到已验证的应用、Prompt 和 Skill 组合。

成本：

- Release notes 和 manifest 必须维护版本矩阵。
- 自动化需要检查各轴声明与实际文件一致。
- 构建身份与源代码修订必须纳入发布流程，不能只依赖人工命名。

## 被否决的方案

### 所有层使用同一个版本号

被否决，因为它混淆功能版本、Prompt 语义、Skill 方法和数据兼容性。

### 每次发布都提升 Schema

被否决，因为无数据契约变化时提升 Schema 会制造无意义迁移，并增加回滚风险。

## 验证要求

每次发布至少记录：

- 七轴版本矩阵；
- 兼容性和数据迁移结论；
- 应用与 Skill 的构建绑定；
- 构建清单和 SHA-256；
- 对应测试、E2E 与回滚入口。
