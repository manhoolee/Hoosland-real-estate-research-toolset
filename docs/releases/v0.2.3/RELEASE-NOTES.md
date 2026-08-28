# Hoosland 地产研究工作台 V0.2.3 发布说明

- 应用版本：`0.2.3`
- Build ID：`v0.2.3-output-persistence-20260828T040220Z`
- System Prompt：`real-estate-system-v0.2.2`
- Skill bundle：`2.3.1`
- Project state Schema：`2.1.0`
- Conversation usage sidecar Schema：`1`
- 兼容性：兼容修复，无数据迁移，仅发布 V2 / slot-b

## 修复内容

复杂研究任务可能先用 persistent Bash 在临时目录处理网页。Bash 的当前目录会跨调用保持，但 write/edit 文件工具仍使用自己的文件后端；模型若把 `${PWD}/outputs` 当作正式成果目录，就可能把成品写入 `/tmp/**/outputs` 或工作区的嵌套 outputs。旧后端只在任务成功后审计顶层 `workspace/outputs`，因此文件缺失仍可能显示成功。

V0.2.3 建立三层防线：

1. Cordis 开启动态 runtime context，让模型持续获得 canonical session workspace。
2. 每轮应用 Prompt 注入唯一的 workspace、work 与 outputs 绝对路径，并说明 Bash `cd` 不改变文件工具根，临时或嵌套 outputs 不能交付。
3. 后端在写入成功状态和发送最终消息之前，比对本轮前后的顶层 outputs 指纹；只要模型尝试生成的任一输出目标没有持久化，就返回可重试失败并记录内容无关的目标标识。

## 数据、安全与回滚

- 不迁移、不删除、不改写旧 conversation、附件、成果或 `usage.json`。
- 不从共享 PrivateTmp 自动复制文件，避免并发 conversation 之间误关联或越权。
- 私有日志不记录文件名、原始路径或文件内容，只记录尝试数量、格式和 canonical/misplaced 分类。
- 回滚时切回上一不可变 V0.2.2 release 及其 `real-estate-system-v0.2.1` Cordis；持久数据无需降级。

## 验收要求

- 后端完整单元与 HTTP 回归、Python 编译、前端类型检查和生产构建全部通过。
- 真实 Provider 任务必须生成 Markdown 与 HTML，随后更新同名文件；API、页面刷新与服务重启后文件仍存在且内容为更新版本。
- 错写 `/tmp/**/outputs` 的模拟任务必须进入可重试失败，不能出现成功终态。
- 发布前后分别核对 V1 / slot-a 的 Build 与健康状态，V1 不重启、不改配置、不改数据。
