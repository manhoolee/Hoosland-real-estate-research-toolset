# 安装指南

本指南说明如何从源码安装 Hoosland-real-estate-research-toolset V2 产品线。它覆盖本地开发、单进程演示和 Windows + WSL2；面向服务器的 systemd、Nginx、升级与回滚步骤见[部署说明](DEPLOYMENT.md)。

## 1. 选择安装方式

| 方式 | 适用场景 | 进程入口 | 当前状态 |
|---|---|---|---|
| 本地开发 | 开发、调试、Skill 迭代 | Vite `5173` + Uvicorn `8000` | 推荐开发方式 |
| 本地单进程演示 | 内网试用、验收生产静态托管形态 | Uvicorn 同时提供 SPA 与 API | 可用，仍属开发者预览 |
| Linux + systemd + Nginx | 单机私有部署 | Nginx → 单 worker Uvicorn | 当前服务器基线 |
| Docker / Kubernetes / 多副本 | 容器或集群 | 未提供 | 尚未完成真实运行时验收 |

当前锁、任务表、取消状态和 Harness runner cache 都在进程内，因此所有方式必须保持 **一个应用实例、一个 Uvicorn worker**。不要使用 `--workers 2`、Gunicorn 多 worker、Compose 多副本或 Kubernetes replicas。

## 2. 支持平台

完整 Agent 依赖固定版本 `deepseek-harness-runtime-bin==0.1.1rc1`：

| 平台 | 支持情况 |
|---|---|
| Linux `x86_64` / `arm64` | 支持；glibc 需满足 `manylinux_2_28` |
| Windows + WSL2 | 推荐；在 WSL2 的 Linux 文件系统中安装 |
| macOS 14+ Apple Silicon | 支持 |
| 原生 Windows | 当前 runtime wheel 不支持 |
| Intel Mac、Alpine / musl | 当前 runtime wheel 不支持 |

平台范围与 DeepSeek Harness Python SDK 的[官方前置条件](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/python-sdk.md)一致。原生 Windows 可以单独运行前端，但不能据此声称完整 Agent 已安装。

## 3. 前置条件

- Git；
- Python `3.11`；
- Node.js `^20.19.0 || >=22.12.0`，建议 Node 22 LTS；
- npm 与 Bash；
- 有权限访问本私有仓库的 GitHub 账户；
- DeepSeek 或兼容接口的真实凭证；
- 至少一个只供本应用使用的可写数据目录。

安装前检查：

```bash
git --version
python3.11 --version
node --version
npm --version
```

Linux 还可以检查 glibc：

```bash
getconf GNU_LIBC_VERSION
uname -m
```

## 4. 获取源码与安装依赖

```bash
git clone https://github.com/manhoolee/Hoosland-real-estate-research-toolset.git
cd Hoosland-real-estate-research-toolset

python3.11 -m venv backend/.venv
. backend/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

npm --prefix frontend ci
cp backend/.env.example backend/.env.local
chmod 0600 backend/.env.local
```

不要使用普通 `npm install` 替代 `npm ci`；前者可能偏离已提交的 lockfile。安装脚本不会替你安装系统依赖，也不会自动写入任何模型密钥。

## 5. 最低配置

编辑 `backend/.env.local`，至少确认：

```dotenv
APP_ENV=development
APP_SLOT=local
BUILD_ID=dev
HOST=127.0.0.1
PORT=8000
DATA_DIR=./data
FRONTEND_DIST=../frontend/dist
HARNESS_CORDIS_PATH=./cordis.yml
HARNESS_SKILL_DIRS=../skills
DEEPSEEK_API_KEY=
CAPABILITY_MCP_URL=http://127.0.0.1:8000/mcp
ADMIN_COOKIE_SECURE=false
```

把真实 `DEEPSEEK_API_KEY` 填进未提交的 `.env.local`，不要写入 README、命令历史、聊天、日志或截图。相对路径由后端以 `backend/` 为根解析，因此上面的 `../skills` 与 `../frontend/dist` 是有效值。

管理配置页面需要同时设置 `ADMIN_PASSWORD` 和 `ADMIN_SESSION_SECRET`。仅本地试运行且不使用管理配置时可以暂不启用；服务器部署必须配置，并保持加密密钥跨升级不变。完整变量见[配置参考](CONFIGURATION.md)。

## 6. 启动方式 A：本地开发

终端一启动后端：

```bash
cd backend
. .venv/bin/activate
python -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1 \
  --env-file .env.local
```

终端二从仓库根目录启动前端：

```bash
npm --prefix frontend run dev
```

访问 <http://127.0.0.1:5173>。Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`。

## 7. 启动方式 B：本地单进程演示

先构建前端：

```bash
npm --prefix frontend run build
test -s frontend/dist/index.html
```

再启动后端：

```bash
cd backend
. .venv/bin/activate
python -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1 \
  --env-file .env.local
```

访问 <http://127.0.0.1:8000>。FastAPI 只在启动时发现 `FRONTEND_DIST/index.html` 存在时挂载 SPA；如果在后端启动之后才执行前端构建，需要重启后端。

## 8. Windows 使用 WSL2

当前 Python Harness runtime 没有原生 Windows wheel。Windows 用户应在管理员 PowerShell 中安装 WSL2：

```powershell
wsl --install -d Ubuntu
```

按系统提示重启后进入 WSL：

```powershell
wsl -d Ubuntu
```

随后在 WSL 终端执行本指南的 Linux 命令。建议把仓库放在 WSL 的 Linux 文件系统，例如 `~/Hoosland-real-estate-research-toolset`，不要放在 `/mnt/c/`，以避免文件监听、权限和大量小文件访问变慢。

服务在 WSL 内监听后，通常可以直接从 Windows 浏览器访问：

```powershell
Start-Process http://127.0.0.1:5173
```

## 9. 安装验证

自动化回归：

```bash
. backend/.venv/bin/activate
PYTHON=python bash ./scripts/test.sh
```

该脚本要求 Python 与前端依赖已经安装；它执行后端测试、Python 编译、前端类型检查与构建以及 11 个 Skill 的 smoke tests，但不会调用真实模型、真实 Provider 或 PDF runtime。

启动应用后检查：

```bash
curl --fail http://127.0.0.1:8000/api/health/live
curl --fail http://127.0.0.1:8000/api/health/ready
curl --fail http://127.0.0.1:8000/api/capabilities
```

`ready=200` 只证明 SDK 可导入、Cordis 存在且主凭证已配置，不证明 bundled runtime 与模型已经真实完成任务。放行前还必须：

1. 在页面完成一个真实最小对话；
2. 确认总控与至少一个专项 Skill 被实际调用；
3. 上传一个文件并成功读取；
4. 生成、打开和下载 Markdown 与 HTML 成果；
5. 刷新页面后确认任务与结果可恢复；
6. 涉及可选 Provider 或 PDF 时分别完成真实验收。

## 10. 常见安装问题

### `No matching distribution found for deepseek-harness-runtime-bin`

当前操作系统或 CPU 架构不在支持范围内。Windows 请使用 WSL2；Intel Mac 和 Alpine 不属于当前已发布 wheel 的目标。

### `ready` 返回 503

检查 `DEEPSEEK_API_KEY`、`HARNESS_CORDIS_PATH`、`HARNESS_SKILL_DIRS` 和 Python 环境。`live=200` 只表示 Web 进程存活，不表示 Agent 可用。

### 页面只有 API 或返回 404

确认 `frontend/dist/index.html` 存在、`FRONTEND_DIST` 正确，并在构建完成后重启后端。

### 内部 MCP 调用失败

确认 `PORT`、Uvicorn `--port` 与 `CAPABILITY_MCP_URL` 使用同一端口。生产环境中 `/mcp` 只允许本机 Harness 回连，不得暴露给公网。

### 多 worker 后出现重复任务或取消失效

当前版本不支持多 worker 或多副本。恢复为一个应用进程和 `--workers 1`。

## 11. 下一步

- 日常操作：[使用说明](USAGE.md)
- 全部环境变量：[配置参考](CONFIGURATION.md)
- Linux systemd、Nginx、PDF、升级与回滚：[部署说明](DEPLOYMENT.md)
- 长期演进约束：[迭代原则](ITERATION-PRINCIPLES.md)
