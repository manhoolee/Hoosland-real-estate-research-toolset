# Hoosland 地产研究工作台 V0.2.2 发布说明

- 发布状态：已上线（V2 / slot-b）
- 发布日期：2026-08-28
- 应用版本：`0.2.2`
- Build ID：`v0.2.2-conversation-token-usage-20260828T023809Z`
- System Prompt：`real-estate-system-v0.2.1`
- Skill bundle：`2.3.1`
- Project state Schema：`2.1.0`
- Conversation usage sidecar Schema：`1`
- 兼容性：兼容更新，惰性创建 sidecar，无批量迁移

## 1. 发布摘要

V0.2.2 在输入框上方显示当前对话累计 Token 消耗。后端按 `conversation_id` 汇总 Harness 可观察到的 Provider usage，通过 SSE 推送增量 snapshot，并提供独立读取接口，使刷新、切换对话、取消或失败后仍能恢复已经持久化的统计。

本次升级 Application，并新增独立的 Conversation usage sidecar Schema 轴。System Prompt 继续使用 `real-estate-system-v0.2.1`，Skill bundle 继续使用 `2.3.1`，Project state Schema 继续使用 `2.1.0`。

## 2. 版本轴

| 版本轴 | V0.2.2 | 变化 |
|---|---:|---|
| Product line | V2 | 不变 |
| Application | `0.2.2` | 从 `0.2.1` 升级 |
| System Prompt | `real-estate-system-v0.2.1` | 不变 |
| Skill bundle | `2.3.1` | 不变 |
| Project state Schema | `2.1.0` | 不变 |
| Conversation usage sidecar Schema | `1` | 首次引入 |
| Product model contract | `2.3.0` | 不变 |

`usage.json` 是 conversation 存储层的独立 accounting projection，不是 Skill 使用的 project_state / case payload。为避免迫使无关的 Skill 契约与 bundle 跳号，本次为 sidecar 建立独立 Schema `1`；Project state Schema 保持 `2.1.0`，case 文件和 Skill 内容均未修改。

## 3. Token 统计与显示

### 统计范围

- 主 Agent 的 Provider usage；
- SDK notification tree 中子 Agent 的 Provider usage；
- 收到 `llm/retry-started` 后实际开始的每个重试 attempt；
- 成功写入 `compaction/summary` 的压缩模型调用。

同一 session、turn、step 和 attempt 的 usage chunk 与最终 assistant message 使用后到值替换，避免重复累计。不同 attempt 与不同子 session 独立相加。`reasoning_tokens` 是 `output_tokens` 的子集，只作为明细展示，不再次加入 `total_tokens`。

### 用户界面

- Token 统计位于输入框上方，与当前 conversation 绑定；
- 新建或没有统计的对话显示 0；
- 消息流建立时先发送当前累计 snapshot，后续在 Provider usage 到达时更新；
- 切换或刷新页面后从持久化接口重新读取。

### API

- `GET /api/conversations/{conversation_id}/usage` 返回当前累计值；
- 消息 SSE 新增 `type=usage` 事件，携带同形 snapshot；
- 明细包含 uncached input、output、reasoning、cache read、cache write、total、更新时间与统计来源；
- `includes_subagents=true` 明确表示子 Agent 已纳入。

## 4. 持久化与数据兼容性

每个 conversation 可以包含独立的 `usage.json`：

- 文件缺失时 V0.2.2 按 0 返回；
- 首次收到新的 Provider usage 时惰性创建或更新；
- 写入使用原子替换，并保存足够的 attempt/event identity 来抵御重复事件与旧事件回放；
- 不包含用户消息正文、附件内容或模型输出正文；
- V0.2.1 不读取该文件，因此旧应用能够继续打开同一 conversation。

本次没有批量迁移器，也不应预先为所有旧 conversation 生成空文件。升级前发生的历史 Token 无可靠 Provider 事件可重放，因此不会估算或回填；升级后的累计从首次可观察 usage 开始。

## 5. 回滚语义

从 V0.2.2 回滚到 V0.2.1 时：

1. 保留 `usage.json`，不要删除或改写；
2. V0.2.1 会忽略 sidecar，既有对话、消息、附件和成果仍可读取；
3. V0.2.1 运行期间不会更新 Token 统计；
4. 再次升级到 V0.2.2 后会继续使用回滚前的累计值，但回滚期间的 Token 形成不可恢复的缺口。

因此本次属于兼容、惰性引入 usage sidecar Schema `1`；Project state Schema 没有变化。回滚不需要数据降级脚本，但统计连续性只在持续运行 V0.2.2 时成立。

## 6. 配置与部署

- Python requirements 与 Node dependencies 不变；
- 没有新增环境变量；
- 前端生产构建必须设置 `VITE_APP_VERSION=0.2.2`；
- 后端 `BUILD_ID` 固定为 `v0.2.2-conversation-token-usage-20260828T023809Z`；
- `DATA_DIR` 备份必须包含 conversation 下已经存在的 `usage.json`；
- 部署后应核对输入框上方数值、SSE snapshot、刷新恢复和 `GET /usage` 一致。

## 7. 验证

发布源码与生产验证完成：

- 后端单元与 HTTP 回归：94 项全部通过；
- `python -m compileall -q app tests`：通过；
- 前端 TypeScript 检查：通过；
- 前端生产构建：通过；
- Skill manifest 与 smoke tests：通过；
- 自动化覆盖 chunk/final 替换、重试 attempt、子 Agent、压缩、取消、持久化、事件重放、旧 conversation 缺省、404 和 conversation 隔离。

生产放行验证：

- 隔离候选与生产均使用真实 Provider 完成最小对话，SSE 正值 snapshot、最终 `GET /usage`、conversation 隔离与 sidecar 落盘一致；
- 候选与生产分别重启服务，确认同一统计 snapshot 完整恢复；
- 本机、网关与公网 Ready 均返回 Application `0.2.2` 和精确 Build ID，公网 `/mcp` 继续为 404，前端资产哈希一致；
- 输入框上方 Token 控件在桌面与 390px 窄屏通过视觉验收，真实对话的汇总和分项明细正确，浏览器控制台无错误或警告；
- V1 本机与公网快照在切换前后完全一致；发布 manifest、测试日志与 SHA-256 证据已经归档。

## 8. 已知边界

- “实时”以 Provider usage 事件为更新边界，不是逐 Token 字符动画；某些 Provider 只在一次调用结束时返回 usage；
- 只统计 Harness 事件中可观察到的 Provider usage。失败且没有 `compaction/summary` 的压缩调用、未返回 usage 的 Provider 调用，以及独立 Capability Gateway 上游调用当前无法计入；
- 历史对话不会估算或回填升级前的 Token；
- V0.2.1 回滚期间会产生统计缺口；
- Token 数量不是费用估算，不同 Provider 的缓存计费规则仍以各自账单为准。

完整历史见 [CHANGELOG](../../../CHANGELOG.md)，版本策略见 [版本与升级指南](../../VERSIONING-AND-UPGRADES.md)。
