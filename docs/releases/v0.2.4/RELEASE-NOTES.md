# Hoosland 地产研究工作台 V0.2.4 发布说明

- 应用版本：`0.2.4`
- Build ID：`v0.2.4-task-checklist-20260828T043537Z`
- 基线 Build ID：`v0.2.3-output-persistence-20260828T040220Z`
- 基线 Git commit：`34d831a4779c204f08f25009a4d5dba4edfb3582`
- 部署源码 commit：`de24812edb0920d728b0e1ea7d9e0954218ef7ce`
- 源分支：`release/v0.2.4-task-checklist`
- System Prompt：`real-estate-system-v0.2.3`
- Skill bundle：`2.3.1`（无变化）
- Project state Schema：`2.1.0`（无变化）
- Conversation usage sidecar Schema：`1`（无变化）
- Run checklist sidecar Schema：`1`（首次引入）
- 兼容性：兼容新增；旧对话不迁移，清单按新运行惰性创建
- 发布状态：已于 `2026-08-28T06:09:01Z` 上线 V2 / slot-b（observing）

## 目标

用户发送需求后，研究助手先把本轮工作拆成“任务清单”和“成果要求”，再在执行过程中逐项更新。每项只有在完成并复核后才显示为已完成；运行结束时，尚未完成或尚未复核的项目明确显示为未完成，不再被总进度条掩盖。

## 实现范围

1. 复用锁定版本 DeepSeek Harness `0.1.1rc1` 的原生 `todo_write` 整表协议和成功后的 `todo/write` 持久事件，不从普通模型文本或失败的工具调用参数猜测任务状态。
2. 应用把根 Agent 的清单事件绑定到当前 `run_id`，转换成带 revision 的完整快照；子 Agent、旧运行、重复或乱序事件不能覆盖当前清单。
3. 每轮清单同时包含任务与成果要求。首张清单必须早于实质工具操作且不能预先完成项目；后续每次最多新增一个 completed，已完成项不能回退，成功前必须观察到首张后的逐项更新。
4. 文件成果在终态时与本轮顶层 `workspace/outputs` 的真实新增或更新格式交叉核验；缺失格式、未完成复核或未完成任务均保留为未完成。
5. SSE、刷新恢复、停止、失败、重试和历史消息都读取同一份持久快照；内部 committing 与幂等补偿保证 checklist、assistant、run 三者写入失败或重启后仍收敛到同一终态，成功清单不会早于 durable run 发出。

文件成果的自动证据校验粒度是“扩展名 + 本轮非空新增或更新”，不等同于逐文件内容验收；同一扩展名的多个成果应合并在一个成果要求中描述，并继续由任务复核承担内容完整性判断。

## 数据与回滚

清单使用独立的 Run checklist sidecar Schema `1`，不写入刻意保持 content-free 的 `run.json`，也不改变 Skill 的 project state。V0.2.3 会忽略新增 sidecar，因此回滚不需要删除或改写既有 conversation；回滚期间的新运行不会产生清单，但消息、附件、成果文件和 Token usage 均继续按 V0.2.3 行为工作。

## 验收与上线结果

本次发布已完成：

- 后端单元与 HTTP 回归 124 项全部通过，Python `compileall` 通过；
- 前端类型检查与生产构建通过，只有既有的单 chunk 体积提示；
- Skill smoke 全部通过；
- 本地固定清单快照在 1440、1024、375 和 320px 浏览器视口复核，无横向溢出，任务/成果分组、终态 detail 与读屏结构正确，控制台 0 错误/警告。
- 精确源码提交的 GitHub Actions run `33146036939` 成功；服务器侧 124 项回归、`pip check`、release manifest 与 Skill manifest 均通过。
- 3092 隔离候选与生产公网真实 Provider E2E 均生成 2 个任务、3 项成果要求和 8 个 checklist revision；首次完整清单无 completed，随后以 5 次独立 revision 逐项完成，终态清单早于 final 发送。
- 候选与生产分别重启 V2 后，刷新接口、assistant checklist、run 终态、sidecar SHA-256、2 个真实成果文件和 Provider Token 用量均精确保持。
- 生产切换前后 running conversation 均为 0；上线后本机、gateway 与公网 Ready 均返回 Application `0.2.4`、slot-b 和本 Build ID，公网 `/mcp` 保持 404。
- V1 服务与公网健康快照、Nginx 容器/配置指纹、Skill bundle 指纹前后完全一致；V0.2.3 release 和切换前环境备份均保留为直接回滚点。

上线后线上返回：

```json
{
  "version": "0.2.4",
  "slot": "slot-b",
  "build_id": "v0.2.4-task-checklist-20260828T043537Z"
}
```

访问受控的发布证据保存在服务器 `/srv/real-estate-agent-2/release-evidence/v0.2.4-task-checklist-20260828T043537Z`，目录内 `EVIDENCE-SHA256SUMS` 已复核通过。
