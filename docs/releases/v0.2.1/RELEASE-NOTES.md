# Hoosland 地产研究工作台 V0.2.1 发布说明

- 发布状态：release candidate
- 发布日期：2026-08-27
- 应用版本：`0.2.1`
- Build ID：`v0.2.1-production-sync-version-info-20260827T062425Z`
- System Prompt：`real-estate-system-v0.2.1`
- Skill bundle：`2.3.1`
- Project state Schema：`2.1.0`
- 兼容性：兼容更新，无数据迁移

## 1. 发布摘要

V0.2.1 将服务器已经验证的 controller-first、总控缺失失败关闭、默认 Markdown + HTML 和输出格式审计正式归档到 GitHub 可重建源码，并补齐 Application 与 Skill patch 版本。

页面品牌区新增 GitHub 源码入口、可见版本号和版本档案。版本档案从公开健康接口读取实时 Application 与 Build ID，同时展示发布日期、兼容性和本次修改摘要。

## 2. 版本轴

| 版本轴 | V0.2.1 | 变化 |
|---|---:|---|
| Product line | V2 | 不变 |
| Application | `0.2.1` | 从 `0.2.0` 升级 |
| System Prompt | `real-estate-system-v0.2.1` | 不变 |
| Skill bundle | `2.3.1` | 从 `2.3.0` 升级 |
| Project state Schema | `2.1.0` | 不变 |
| Product model contract | `2.3.0` | 不变 |

Application 与 Skill 的 patch 升级用于关闭 V0.2.0 热修中“行为已变化但 SemVer 未变化”的版本债务。System Prompt、项目状态 Schema 和产品测算输入契约没有语义变化，因此不机械跟随跳号。

## 3. 生产源码归档

- 应用每轮 Prompt 首行确定性激活 `comprehensive-real-estate-expert`。
- 缺少总控 Skill 时，Ready 与运行均明确失败，不静默退化为专项直达。
- 子 Skill 只向总控返回下一节点需求，不直接编排下游。
- 报告类任务未指定格式时默认生成 Markdown 与独立 HTML。
- 运行日志记录本轮实际新增或更新的输出格式，并判断默认格式对是否存在。
- 发布探针验证总控命令位于实际 Harness Prompt 首行。

这些行为已经在上一生产 Build 中运行；V0.2.1 的变化是把它们从“服务器存在、Git 不可重建”的状态恢复为可审计源码基线。

## 4. 页面版本档案

### 可见入口

- 桌面品牌区展示 `V0.2.1` 和 GitHub 按钮。
- 窄屏把版本号压入楼宇标识，不额外占用顶栏宽度。
- 点击版本号或楼宇标识打开版本档案。

### 档案内容

- 实时 Application 版本；
- 精确 Build ID；
- 发布日期和兼容性；
- 生产行为归档、默认双格式、版本来源可见三组修改摘要；
- GitHub 仓库和完整 `CHANGELOG.md` 入口。

页面通过 `/api/health/live` 获取运行身份；读取失败时保留前端 release 版本作为降级展示，但不会伪造 Build ID。

### 可访问性与响应式

- Escape 和遮罩点击可关闭；
- 关闭后焦点返回原触发按钮；
- 弹层内保持键盘焦点循环；
- 外部链接使用 `target="_blank"` 与 `rel="noopener noreferrer"`；
- 支持减少动画偏好；
- 1440、1024、375 和 320px 均无横向溢出。

## 5. 验证

本次源码完成：

- 后端单元与 HTTP 回归：86 项全部通过；
- `python -m compileall -q app tests`：通过；
- 前端 TypeScript 检查：通过；
- 前端生产构建：通过；
- Skill v2.3.1 manifest、11 个 `_meta.json` 与 smoke tests：通过；
- 微信离线失败路径 smoke：通过；
- 页面版本档案四档响应式浏览器验收：通过；
- 浏览器控制台错误：0。

## 6. 兼容性、配置和数据

- 既有公开业务 API 路径不变。
- Project state Schema 不变，无数据迁移。
- Python requirements 和 Node dependencies 不变。
- Provider、管理员和持久数据配置含义不变。
- 前端生产构建应显式设置 `VITE_APP_VERSION=0.2.1`。
- 运行环境应把 `BUILD_ID` 设置为本次不可变 Build ID，并将 Skill 绑定到对应的 v2.3.1 目录。

## 7. 发布与回滚

本次必须创建新的不可变应用 release 和版本化 Skill 目录，重新生成语义正确的 release manifest、Skill manifest 与 SHA-256。不得原地修改旧 release，也不得把旧 release 中已经过期的 `RELEASE_MANIFEST.md` 复制到新版本。

切换失败时，应成对恢复：

1. 前一应用 release；
2. 前一 Skill 绑定；
3. 前一 Build ID；
4. 服务进程及健康状态。

由于没有数据迁移，正常回滚不需要改写既有项目或对话数据。

## 8. 已知边界

- 总控后的子 Skill 顺序和去重仍以 Prompt/Skill 契约与运行审计为主，不是完整后端状态机。
- 默认双格式仍是执行契约加软审计，尚未把缺少文件自动升级为运行失败。
- 页面显示的版本身份依赖公开健康接口与部署环境中的正确 Build ID。
- 项目仍处于开发者预览阶段，不承诺稳定公开接口或长期兼容性。

完整历史见 [CHANGELOG](../../../CHANGELOG.md)，版本策略见 [版本与升级指南](../../VERSIONING-AND-UPGRADES.md)。
