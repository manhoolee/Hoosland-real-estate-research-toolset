# Hoosland 地产研究工作台 V0.2.0 发布说明

- 发布状态：online / observing
- 发布日期：2026-08-25
- 应用版本：`0.2.0`
- System Prompt：`real-estate-system-v0.2.1`
- Skill bundle：`2.3.0`
- Project state Schema：`2.1.0`

本文是脱敏的公开发布记录。具体 Build ID、文件校验值和部署证据由对应构建清单保存。

## 1. 发布摘要

V0.2.0 建立了完整的地产研究工作台，并在后续热修中关闭了两个真实回归问题：

1. 页面刷新后没有自动接回仍在运行的后台任务。
2. 单专项请求可能绕过综合总控，且报告类任务可能只生成 Markdown。

当前版本把 `comprehensive-real-estate-expert` 固定为每轮入口，再由总控调用必要专项；地产研究、项目分析、策划方案和管理报告在未指定格式时默认生成 Markdown 与独立 HTML。

## 2. 版本轴

| 轴 | 本次版本 | 兼容性结论 |
|---|---:|---|
| Application | `0.2.0` | 发布事实；行为与 Ready 状态已变化但 patch 未提升，登记为版本债务 |
| System Prompt | `real-estate-system-v0.2.1` | 编排与交付全局规则升级 |
| Skill bundle | `2.3.0` | 版本化内容修订；后续内容变化应提升 patch version |
| Project state Schema | `2.1.0` | 未变化，无数据迁移 |
| Build ID | 构建唯一 | 记录在构建清单中 |

版本策略见 [ADR-0001](../../adr/0001-version-axes.md)。

## 3. 主要能力

### 3.1 Agent 与 Skill

- 使用 FastAPI、React、Harness 与 Cordis 组成工作台执行链。
- 集成 1 个总控和 10 个专项，共 11 个房地产 Skill。
- System Prompt 统一身份、安全、证据、权限和执行真实性。
- 未配置能力返回明确不可用状态，不用模型猜测替代真实调用。

### 3.2 项目与长任务

- 支持项目、多对话、附件和成果管理。
- REST + SSE 提供安全进度和最终结果。
- `run.json`、请求标识和一致性对账支持页面刷新恢复。
- 取消、重试、多标签竞态和进程重启后的中断状态均有持久化处理。

### 3.3 正式交付

- 固定“业务专项 → 编辑 → 设计 → 按需 PDF → 最终 QA”。
- Markdown 与独立 HTML 是报告类主成果的默认格式。
- PDF 继续按需生成，并与最终内容/发布 QA 明确分责。

## 4. 本次总控优先修复

### 问题

旧路由允许单一专项任务由 Harness 直接选择对应 Skill。真实测试因此只调用研究专项，没有经过综合总控。

### 修复

- 应用构造的每轮 Prompt 第一行固定激活 `comprehensive-real-estate-expert`。
- 用户请求使用 JSON 编码，用户自带 slash 文本不能替换服务端入口。
- 总控文件缺失时 Ready 和运行 fail closed。
- 总控成为唯一编排者，子 Skill 返回下一节点需求，不直接调用下游。
- 总控维护本轮逻辑调用集合，约定同一专项最多调用一次。

### 保证边界

第一行注入和总控文件存在检查是后端硬约束；专项顺序、去重与下游交接目前是 Prompt/Skill 契约。运行日志提供软审计，发布 E2E 验证真实会话首行和实际专项调用链。详见 [ADR-0003](../../adr/0003-controller-first.md)。

## 5. 本次默认双格式修复

### 问题

默认格式虽然存在于 runtime 配置，但没有稳定进入每轮执行契约。真实测试只生成了 Markdown。

### 修复

- System Prompt、每轮交付策略和总控 Skill 同时声明报告类主成果默认 Markdown + HTML。
- 用户明确格式、不要文件、简短问答和专项输出契约继续优先。
- 默认不生成 PDF。
- 运行完成日志增加本轮实际格式和默认格式对存在标记。

### 保证边界

本轮格式记录属于软审计，不会自动把缺少文件的成功运行改成失败。同主名、非空、可打开和 HTML 结构由发布 E2E 验证。详见 [ADR-0004](../../adr/0004-default-md-html.md)。

## 6. 测试与验收

本次发布完成：

- 后端单元与 HTTP 回归：86 项通过；
- Python 编译检查：通过；
- Skill smoke tests：通过；
- Python 依赖一致性检查：通过；
- 隔离候选环境真实 E2E：通过；
- 切换后公开入口真实 E2E：通过。

总控与双格式 E2E 验证了：

- 实际 Harness Prompt 首行是总控命令；
- 有效链为总控 → Research → Editorial → Design → Delivery QA；
- 四个 runtime 子 Skill 各调用一次，无重复和失败；
- 未要求 PDF 时没有误调用 PDF Skill；
- 同轮 Markdown 与 HTML 同主名、非空、可下载、可打开；
- HTML 基本结构有效；
- 本轮格式软审计同时包含 `md` 和 `html`。

这组 E2E 覆盖了研究报告主路径，不代表 Product、Social、Wechat、显式单格式和按需 PDF 等所有分支已经获得同等覆盖。

## 7. 部署与隔离

- 使用不可变应用 release 和版本化 Skill 目录。
- 先在隔离候选环境验证，再切换目标槽位。
- 切换前确认没有活动任务。
- 应用与 Skill 绑定作为一个一致性单元恢复；服务停止期间分别以原子文件操作完成切换。
- 另一槽、现有代理路由和持久客户数据不因本次热修改变。

本次热修没有修改前端构建、Python requirements、反向代理配置或 Project state Schema，也没有执行客户数据迁移。Ready 响应增加了总控是否已配置的兼容性字段。

双槽原则见 [ADR-0002](../../adr/0002-dual-slot-data-isolation.md)。

## 8. 回滚

若总控路由、Skill 交接或默认交付出现阻断问题，应：

1. 停止受影响槽位并保留脱敏诊断证据。
2. 恢复前一已验证的应用 release。
3. 同时恢复与该 release 匹配的环境配置和 Skill 绑定。
4. 启动并验证旧版本、槽位和 Agent Ready。
5. 复测最小对话，确认另一槽不受影响。

由于本次没有数据迁移，正常应用回滚不需要改写既有 conversation 数据。不得删除失败 release 或 E2E 证据来“清理”故障。

## 9. 已知限制

- 项目仍处于开发者预览阶段，不承诺稳定生产兼容性。
- 总控后的专项顺序和调用去重不是服务端强制状态机。
- 总控配置检查只验证文件存在，不验证 Skill 内容哈希或语义。
- 默认双格式是 Prompt/Skill 契约加软审计，缺失文件不会自动让运行失败。
- 本轮输出指纹基于文件路径、大小和修改时间，不是内容哈希。
- 同主名和内容对应度由 E2E 检查，尚未成为每轮在线硬闸门。
- 当前运行锁和 runner cache 位于单进程内，尚不支持无状态水平扩容。
- 当前身份能力不是完整的多租户授权系统。

## 10. 后续升级要求

- Skill 内容再次变化时提升 Skill bundle patch version。
- 下一 canonical release 将 Application 至少提升到 `0.2.1`，关闭本次 Build-only 应用行为热修的版本债务。
- 为 Product、Social、Wechat、显式格式覆盖和按需 PDF 增加独立 E2E。
- 评估是否把 Skill 去重、完整交付链和默认双格式提升为机器可读的后端状态机。
- 每次发布继续保留版本矩阵、构建清单、SHA-256、测试证据和成对回滚入口。
- 遵守 [Skill 编排契约](../../SKILL-ORCHESTRATION.md)，不得重新引入专项直达入口。

