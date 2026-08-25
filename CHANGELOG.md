# 更新记录

本项目分别记录应用、System Prompt、Skill 套件和数据 Schema 版本；它们不会为了展示一致而同步跳号。

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
- 当前源码快照通过 83 个后端单元测试、Python 编译、前端类型检查与生产构建；
- Skill v2.3 smoke tests 通过。

## 历史 Skill 版本

Skill v2.1 与 v2.2 的历史方法和说明仍可在原 Skill 仓库历史中查阅；本统一仓库从 App 0.2.0 / Skill 2.3.0 开始维护。
