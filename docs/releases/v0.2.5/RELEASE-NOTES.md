# Hoosland 地产研究工作台 V0.2.5 发布说明

- 应用版本：`0.2.5`
- Build ID：`v0.2.5-todo-write-recovery-20260828T090530Z`
- 基线 Build ID：`v0.2.4-task-checklist-20260828T043537Z`
- 基线部署源码 commit：`de24812edb0920d728b0e1ea7d9e0954218ef7ce`
- 发布分支父 commit：`6351cd2622a6903796a24e655ab2a98c02005fb1`
- 部署源码 commit：`914dc8f12a41a54ee2233f70834f24ed16330dcd`
- 源分支：`release/v0.2.5-todo-write-recovery`
- System Prompt：`real-estate-system-v0.2.4`
- Skill bundle：`2.3.1`（无变化）
- Harness SDK / runtime package：`0.1.1rc1`（无变化）
- Project state Schema：`2.1.0`（无变化）
- Conversation usage sidecar Schema：`1`（无变化）
- Run checklist sidecar Schema：`1`（无变化）
- 数据迁移：无
- 发布状态：已于 `2026-08-28T09:36:50Z` 上线 V2 / slot-b

## 修复的问题

V0.2.4 已能拒绝首张预完成、单次批量完成和项目集合变化，但 Harness 的原生 `todo_write` 与应用持久化层是两个状态边界。模型看到本地工具调用成功后，可能继续按那张非法快照执行；应用虽然正确地拒绝了持久化，却没有把拒绝结果送回仍在运行的根 Agent。最终会出现：

```text
Harness 本地清单已更新
→ 应用拒绝该快照
→ 模型不知道拒绝并继续执行
→ 持久清单停留在旧 revision
→ success 门禁报 AGENT_CHECKLIST_MISSING
```

本次没有放宽持久化规则，而是补齐两个状态边界之间的恢复协议。

## 同会话权威恢复

1. 持久化层使用有界 rejection reason 拒绝非法快照，原快照不会覆盖最后一张已接受状态。
2. 当前 run 已有 accepted items 时，应用读取最后一张持久快照，构造只包含拒绝原因、accepted revision 和 `authoritative_todos` 的服务端纠正；若首张快照非法而没有权威基线，则以 `AGENT_CHECKLIST_RECOVERY_FAILED` 直接失败关闭，不会伪造可恢复状态。
3. 纠正通过同一个根 Harness session 注入，不创建第二个应用 run，也不递归启动第二个 runner。
4. 下一张 `todo/write` 必须与权威 todos 的内容、顺序和状态完全一致；恢复前禁止搜索、命令、文件、其他实质工具和 final。
5. 精确重置被持久化后，模型才可以继续逐项工作；此后仍保持每个 revision 最多新增一个 completed。

同一恢复 incident 如果再次提交不匹配快照会立即失败，不会无限发送纠正。每轮最多处理 3 个彼此独立的拒绝事件，第 4 个事件以 `AGENT_CHECKLIST_RECOVERY_EXHAUSTED` 失败。纠正注入、清单读取/写入或协议错误也全部 fail closed，并丢弃不可继续复用的 runner。

## 为什么不会被旧 idle 截断

锁定的 SDK convenience turn 会在观察到 idle 时返回。如果原 prompt 的旧 idle 已经排队，而应用刚注入纠正，直接沿用旧边界可能在纠正执行前提前结束。

V0.2.5 由应用持有该 run 唯一的 session notification subscription：

- 每个 initial/followup prompt 都取得 message ID；
- 只有观察到对应的 `agent/inbox/spliced` 才确认 prompt 已进入 session；
- 仍有待确认 prompt 时忽略排队的旧 idle；
- 纠正回执、纠正后的 todo 快照和后续根 idle 到达后，才收口最终回复与 finish reason。

生产代码不依赖 sleep 或猜测模型时序。确定性 wire gate 使用真实 `deepseek-harness-sdk==0.1.1rc1` 的 stdio reader、response waiter、subscription 和 `session_prompt`，固定发送：

```text
initial receipt → todo #1 → old final → old idle
→ correction receipt → todo #2 → corrected final → new idle
```

门禁只有在最终回复为纠正后的 `RECOVERY_RUNTIME_OK` 时通过；旧 final 不得成为运行结果。

## 执行与交付清单是否真正处理

本次从四层分别验证，不使用模型自述作为证据：

- 存储层：非法快照仍被拒绝，最后一张 accepted revision 不变；精确基线重置后才产生下一 revision。
- HTTP / SSE 层：生产缩小序列完成“批量拒绝 → 权威重置 → 逐项完成 → 成功终态”；pending repair 不能提交 success。
- Harness wire 层：同一 session 的纠正 prompt、inbox receipt、第二张 todo 快照和后续 idle 顺序被真实 SDK 观察到。
- 真实 Provider 层：3092 候选与生产公网均实际产生 2 个任务、3 项成果要求和 8 个 revision，以 5 次独立完成更新收口；终态 checklist 早于 final，两个成果文件、assistant、run、sidecar 和 Token usage 在服务重启后保持一致。

因此，本次不仅修改了提示词或错误文案；持久化状态机、同会话交互、成功门禁和交付持久化均有独立证据。

## 自动化与发布结果

- 精确源码提交的 GitHub Actions run `33157910758` 成功；
- 本地归档源码与服务器不可变 release 均完成 132 项后端单元/HTTP 回归并全部通过；
- Python `compileall`、前端 TypeScript 检查与生产构建、`pip check`、Skill manifest / smoke、release manifest 与制品 SHA-256 全部通过；
- 3092 隔离候选真实 Provider E2E、SDK recovery wire gate 和重启持久化复验全部通过，候选停止后端口不再监听且候选数据目录已清理；
- 切换前后生产 running conversation 均为 0；本机、gateway 与公网 Ready 均返回 Application `0.2.5`、slot-b 和本 Build ID；
- 生产公网真实 Provider E2E 与服务重启复验通过，`NRestarts=0`，priority 0..3 journal 与 checklist/recovery failure journal 均为空；
- 公网 `/mcp` 保持 404；V1 服务/公网快照、Nginx 容器与配置、Skill bundle 指纹前后完全一致。

上线后健康身份为：

```json
{
  "version": "0.2.5",
  "slot": "slot-b",
  "build_id": "v0.2.5-todo-write-recovery-20260828T090530Z"
}
```

访问受控的发布证据保存在服务器 `/srv/real-estate-agent-2/release-evidence/v0.2.5-todo-write-recovery-20260828T090530Z`，目录内 `EVIDENCE-SHA256SUMS` 已复核通过。

## 兼容性与回滚

- requirements、Node 依赖、Harness、Skill、环境变量、公开 API 和全部持久化 Schema 不变；
- recovery attempt、pending receipt 和权威重置预期只存在于单次运行内存及脱敏 operation log，不写入 checklist sidecar；
- 现有 conversation、消息、附件、成果文件、usage 和 checklist sidecar 不迁移、不覆盖；
- 直接回滚点为不可变 V0.2.4 release `v0.2.4-task-checklist-20260828T043537Z` 及切换前环境备份；回滚不需要删除 V0.2.5 运行产生的 sidecar；
- 自动回滚脚本已验证目标 Ready 身份为 Application `0.2.4` 和前一 Build，但本次发布未触发回滚。
