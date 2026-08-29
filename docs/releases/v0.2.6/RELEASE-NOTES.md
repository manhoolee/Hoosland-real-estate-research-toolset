# Hoosland 地产研究工作台 V0.2.6 发布说明

- 应用版本：`0.2.6`
- Build ID：`v0.2.6-scope-gate-20260829T101331Z`
- 基线：已上线的 V0.2.5 scope-gate release
- System Prompt：`real-estate-system-v0.2.4`（不变）
- Skill bundle：`2.3.1`（不变）
- Project state / usage / checklist Schema：`2.1.0` / `1` / `1`（不变）

## 本次变更

1. 后端、前端、健康接口和发布清单的 Application 版本统一为 `0.2.6`。
2. Scope gate v1.1 增加对混入地产项目话术的后台、服务端、接口、部署、版本和助手设定提取请求的本地拒绝。
3. Egress gate v1 继续在最终文本和文件输出边界 fail closed，避免内部运行标记进入 SSE、历史或公开文件。

被拒请求在创建 Harness run、读取附件或写入用户消息之前结束，因此不消耗 Provider token；固定项目范围答复保持不变。

## 验证与上线

- 后端自动化回归：159 项通过；
- Python 编译、前端 TypeScript 检查与生产构建通过；
- 3092 隔离候选 ready、对话刺探拒绝、空历史和零 token 检查通过；
- 生产 V2 / slot-b、gateway 和公网页面 ready 通过，公网页面 HTTP 200，公网 `/mcp` 保持 404；
- 旧 V0.2.5 release 与切换前环境备份保留，可原子回滚；无数据迁移。
