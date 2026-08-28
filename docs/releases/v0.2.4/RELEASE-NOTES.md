# Hoosland 地产研究工作台 V0.2.4 候选说明

- 应用版本：`0.2.4`
- 候选 Build ID：`v0.2.4-task-checklist-20260828T043537Z`
- 基线 Build ID：`v0.2.3-output-persistence-20260828T040220Z`
- 基线 Git commit：`34d831a4779c204f08f25009a4d5dba4edfb3582`
- 源分支：`release/v0.2.4-task-checklist`
- System Prompt：`real-estate-system-v0.2.3`
- Skill bundle：`2.3.1`（无变化）
- Project state Schema：`2.1.0`（无变化）
- Conversation usage sidecar Schema：`1`（无变化）
- Run checklist sidecar Schema：`1`（首次引入）
- 兼容性：兼容新增；旧对话不迁移，清单按新运行惰性创建
- 发布状态：本地自动化与浏览器复核通过；真实 Provider E2E、隔离候选部署和线上切换尚未执行

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

## 放行状态

当前候选已完成：

- 后端单元与 HTTP 回归 124 项全部通过，Python `compileall` 通过；
- 前端类型检查与生产构建通过，只有既有的单 chunk 体积提示；
- Skill smoke 全部通过；
- 本地固定清单快照在 1440、1024、375 和 320px 浏览器视口复核，无横向溢出，任务/成果分组、终态 detail 与读屏结构正确，控制台 0 错误/警告。

本文件仍只登记候选身份，不代表已经上线。真实 Provider 流式 E2E、隔离候选部署、生产快照与原子切换尚未执行；完成这些门禁后才能生成不可变 release 并申请切换 V2 / slot-b。上线前线上仍应返回：

```json
{
  "version": "0.2.3",
  "slot": "slot-b",
  "build_id": "v0.2.3-output-persistence-20260828T040220Z"
}
```
