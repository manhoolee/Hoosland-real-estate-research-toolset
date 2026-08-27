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

项目独立维护五个版本轴：

| 版本轴 | 表达内容 | 何时升级 |
|---|---|---|
| Application SemVer | API、应用行为、前后端功能 | 应用发布按 SemVer 规则升级 |
| System Prompt version | 全局身份、安全、证据、编排与交付规则 | 全局 Prompt 语义变化时升级 |
| Skill bundle SemVer | Skill manifest、领域方法和交接契约 | Skill 内容或套件接口变化时升级 |
| Project state Schema version | 持久化项目/案例数据契约 | 只有持久化 Schema 变化时升级 |
| Build ID | 一次不可变构建及其部署身份 | 每次可部署构建均生成唯一值 |

Build ID 必须能够关联构建清单、文件校验值和源代码修订。它不是 API 版本，也不能替代 SemVer。

## V0.2 版本矩阵

| 轴 | V0.2 当前值 | 说明 |
|---|---:|---|
| Application | `0.2.0` | 发布事实；热修改变运行编排、Ready 状态和默认交付行为但未提升 patch，形成版本债务 |
| System Prompt | `real-estate-system-v0.2.1` | 新增总控优先与默认报告交付契约 |
| Skill bundle | `2.3.0` | 本次以构建绑定的版本化 Skill 内容修订上线 |
| Project state Schema | `2.1.0` | 无数据结构变化，无迁移 |
| Build ID | 每个构建唯一 | 由发布清单记录，不在本文固定具体值 |

V0.2 热修改变了应用运行编排、Ready 状态和用户可见默认交付行为，却仍沿用 Application `0.2.0`；Skill 内容也发生修订但 manifest 仍为 `2.3.0`。这两项都是已记录的发布事实与版本债务，不应成为后续惯例。下一次 canonical release 应至少升级 Application 到 `0.2.1`、Skill bundle 到 `2.3.1`。

V0.2.1 canonical release 已按该决策把 Application 提升为 `0.2.1`、Skill bundle 提升为 `2.3.1`。System Prompt 与 Project state Schema 没有变化，继续分别使用 `real-estate-system-v0.2.1` 与 `2.1.0`；历史 V0.2.0 版本债务记录保留，不倒改旧发布事实。

## 兼容性规则

- Application 或 Prompt 升级不得自动改写 Project state Schema。
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

- 五轴版本矩阵；
- 兼容性和数据迁移结论；
- 应用与 Skill 的构建绑定；
- 构建清单和 SHA-256；
- 对应测试、E2E 与回滚入口。
