# 配置参考

## 1. 配置方式

后端只读取进程环境变量，不自动读取 `.env` 文件。开发时可以使用 Uvicorn `--env-file`；生产应使用仅 root 可读的 systemd `EnvironmentFile`。不要把真实密钥写入仓库、命令历史、日志或截图。

以 [backend/.env.example](../backend/.env.example) 为唯一模板。

## 2. 应用与存储

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | `development` | 运行环境 |
| `APP_SLOT` | `slot-b` | 槽位或部署标识 |
| `BUILD_ID` | `development` | 不可变构建标识 |
| `HOST` | `127.0.0.1` | 文档化监听地址；Uvicorn 参数仍需一致 |
| `PORT` | `8080` | API 端口，同时影响默认内部 MCP URL |
| `DATA_DIR` | `backend/data` | 对话、文件、session、配置和日志根目录 |
| `FRONTEND_DIST` | `frontend/dist` | 构建后的 SPA 目录 |
| `LOG_LEVEL` | `info` | 应用日志级别 |
| `CORS_ORIGINS` | 空 | 逗号分隔的额外允许来源 |

## 3. Harness 与模型

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HARNESS_ENABLED` | `true` | 是否启用主 Agent |
| `HARNESS_PROVIDER` | `deepseek-official` | SDK Provider 标识 |
| `HARNESS_MODEL` | `deepseek-v4-flash` | 主模型 |
| `HARNESS_MAX_TOKENS` | `49152` | 主任务输出上限 |
| `HARNESS_RUNNER_CACHE_SIZE` | `4` | runner cache 上限 |
| `HARNESS_SKILL_DIRS` | 空 | `os.pathsep` 分隔的 Skill 根目录 |
| `HARNESS_CORDIS_PATH` | `backend/cordis.yml` | 当前 Cordis 组合 |
| `HARNESS_RUNTIME_BIN` | 空 | 可选 runtime 可执行文件 |
| `HARNESS_LAUNCH_ARGS_JSON` | 空 | 可选 JSON 字符串数组 |
| `HARNESS_REQUEST_TIMEOUT_SECONDS` | 空 | 空表示 SDK 默认策略 |
| `DEEPSEEK_BASE_URL` | Provider 默认 | 主模型 base URL |
| `DEEPSEEK_API_KEY` | 空 | 主模型凭证 |
| `DEEPSEEK_SEARCH_BASE_URL` | DeepSeek Anthropic endpoint | 原生搜索 base URL |
| `DEEPSEEK_SEARCH_API_KEY` | 回退主 key | 原生搜索凭证 |
| `DSH_SEARCH_MODEL` | 主模型 | 原生搜索模型 |

`HARNESS_SKILL_DIRS` 应指向本仓库 `skills/`。相对路径以 `backend/` 为基准解析。

## 4. 管理与安全

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ADMIN_PASSWORD` | 空 | 配置后台密码 |
| `ADMIN_SESSION_SECRET` | 空 | Cookie 签名密钥，建议至少 48 个随机字符 |
| `CONFIG_ENCRYPTION_KEY` | 空 | 可选独立 Fernet key；空时从 session secret 派生 |
| `ADMIN_SESSION_SECONDS` | `28800` | 管理会话有效期 |
| `ADMIN_COOKIE_SECURE` | `false` | HTTPS 生产环境必须为 `true` |
| `APP_API_TOKEN` | 空 | 可选 API bearer 保护 |
| `CAPABILITY_MCP_URL` | `http://127.0.0.1:{PORT}/mcp` | Harness 内部回连地址 |
| `CAPABILITY_MCP_TOKEN` | 空 | 部署级 token；正常运行优先使用 conversation 临时 token |

> 当前浏览器前端不会自动发送 `APP_API_TOKEN`。直接启用它会使 SPA 的普通 `/api/*` 请求返回 401；它只适合纯 API 客户端，或由可信反向代理安全注入 bearer header 的部署。浏览器部署应在 Nginx 前置组织级访问控制，详见[部署说明](DEPLOYMENT.md)。

生成随机值示例：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 5. 限额与日志

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `MAX_UPLOAD_BYTES` | `26214400` | 单文件 25 MiB |
| `MAX_REQUEST_BYTES` | `31457280` | 单请求 30 MiB |
| `MAX_CAPABILITY_RESPONSE_BYTES` | `8388608` | 外部能力响应上限 8 MiB |
| `MAX_CAPABILITY_FILE_BYTES` | `26214400` | 传给能力的文件上限 25 MiB |
| `CAPABILITY_TIMEOUT_SECONDS` | `120` | 外部能力超时 |
| `OPERATION_LOG_ENABLED` | `true` | 私有、内容无关的操作日志 |
| `OPERATION_LOG_RETENTION_DAYS` | `14` | 日志保留天数 |

## 6. 可选能力 Provider

能力前缀：

- `VISION_ANALYZE`
- `IMAGE_GENERATE`
- `WEB_SEARCH`
- `DOCUMENT_EXTRACT`
- `DELEGATE_TEXT`

每个前缀支持：

```text
{PREFIX}_API_BASE_URL
{PREFIX}_API_PATH
{PREFIX}_API_KEY
{PREFIX}_API_MODEL
{PREFIX}_AUTH_HEADER
{PREFIX}_AUTH_PREFIX
```

默认 endpoint：

| 能力 | 默认 path |
|---|---|
| 视觉分析 | `/chat/completions` |
| 图像生成 | `/images/generations` |
| 扩展搜索 | `/web-search` |
| 文档抽取 | `/extract` |
| 文本委派 | `/chat/completions` |

只有配置 base URL 后能力才会被标记为 configured。密钥存在但 base URL 为空仍属于未配置。

## 7. 前端构建

| 变量 | 说明 |
|---|---|
| `VITE_API_BASE_URL` | 构建时固定 API 前缀 |
| `VITE_API_PROXY_TARGET` | 开发服务器 `/api` 代理目标 |
| `VITE_DEPLOYMENT_SLOT` | 浏览器存储命名空间 |
| `VITE_APP_VERSION` | UI 展示版本 |

示例：

```bash
VITE_API_BASE_URL=/agent-tools \
VITE_DEPLOYMENT_SLOT=slot-b \
VITE_APP_VERSION=0.2.1 \
npm run build
```

## 8. 配置不变量

- `PORT`、Uvicorn `--port` 与 `CAPABILITY_MCP_URL` 必须一致；
- `HARNESS_CORDIS_PATH` 只指向当前 [backend/cordis.yml](../backend/cordis.yml)；
- 两个部署槽位不得共享 `DATA_DIR`、session、runtime config 或管理员 secret；
- 生产不把 `/mcp` 暴露到公网；
- 配置变更后丢弃已有 runner，再以健康检查和真实最小任务复验。
