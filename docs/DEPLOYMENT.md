# 部署说明

本说明给出从空机开始的单机 Linux 基线：构建不可变 release，由单 worker Uvicorn 同时提供 API 与已构建 SPA，Nginx 负责 TLS、访问控制和 `/agent-tools` 子路径代理。

本项目目前是开发者预览。下面是可审计的参考基线，不代表已经完成组织级生产认证，也不代表任何现网拓扑。

## 1. 部署边界

- 支持 Linux `x86_64` / `arm64`，glibc `2.28+`；
- Python 基线为 `3.11`；
- 构建前端需要 Node.js `^20.19.0 || >=22.12.0`；
- bundled Harness runtime 本身不要求服务器额外安装 Node.js；PDF runtime 仍需要 Node.js；
- 只允许一个应用实例和 `--workers 1`；
- 普通项目、对话和文件 API 当前不包含完整多用户身份系统，公网入口必须由 Nginx 前置组织自己的 SSO、OIDC、VPN、mTLS、Basic Auth 或等效访问控制；
- 当前 SPA 不会自动发送 `APP_API_TOKEN`。直接设置该变量会让浏览器的普通 API 请求返回 401；它只适合纯 API 客户端或能够安全注入 header 的可信网关；
- 对外代理必须阻断 `/mcp`，内部 Harness 只通过 `127.0.0.1` 回连。

当前没有经过真实 Linux 容器验收的 Docker Compose、Kubernetes、多副本或滚动扩容方案，不能把它们列为已支持部署方式。

> 从旧 slug `hoosland-agent-tools` 迁移时，先停用旧 `hoosland-agent-tools.service`，再按备份、权限与验收流程迁移数据和入口。新旧 unit 不得同时监听 8000，也不得未经评估同时写同一 `DATA_DIR`。本仓库不会自动移动生产数据或 secrets。

## 2. 推荐目录

```text
/opt/hoosland-real-estate-research-toolset/
├── releases/{build-id}/
│   ├── .venv/
│   ├── backend/
│   ├── frontend/dist/
│   ├── skills/
│   └── deploy/
├── current -> releases/{build-id}
└── pdf-tool/                    可选、root-owned 的持久 PDF runtime

/srv/hoosland-real-estate-research-toolset/
└── data/                        业务状态与 Harness sessions

/etc/hoosland-real-estate-research-toolset/
└── agent.env                    root:root 0600
```

每个 release 都有独立 `.venv`。这样切回 `current` 时，源码、前端和 Python 依赖一起回滚；不要多个 release 共用一个会被原地升级的 venv。

## 3. 主机与构建环境检查

运行主机至少需要 Python 3.11、systemd、Nginx 和 Git。构建主机还需要 Node.js 与 npm：

```bash
python3.11 --version
getconf GNU_LIBC_VERSION
uname -m
systemctl --version
nginx -v
git --version
node --version
npm --version
```

Node 可以只存在于可信构建机；如果直接在服务器构建，服务器也必须满足前端 Node 版本要求。发行版自带 Node 往往过旧，应使用组织批准的 Node 22 LTS 安装渠道并在构建前检查版本。

## 4. 初始化服务用户与目录

首次部署时创建无登录服务用户：

```bash
sudo useradd \
  --system \
  --home-dir /srv/hoosland-real-estate-research-toolset \
  --create-home \
  --shell /usr/sbin/nologin \
  hoosland-agent
```

如果用户已存在，不要重复执行。创建目录并明确权限：

```bash
sudo install -d -o root -g root -m 0755 /opt/hoosland-real-estate-research-toolset/releases
sudo install -d -o root -g root -m 0750 /etc/hoosland-real-estate-research-toolset
sudo install -d -o hoosland-agent -g hoosland-agent -m 0750 /srv/hoosland-real-estate-research-toolset/data
```

release、配置模板和 PDF runtime 由 root 拥有且服务用户只读；只有 `/srv/hoosland-real-estate-research-toolset` 属于服务运行状态并允许写入。`hoosland-agent` 是兼容保留的内部服务账户名，不是项目正式名称。

## 5. 构建不可变 release

先以普通部署账户克隆私有仓库，不要把 GitHub 凭证交给服务用户或写入 release：

```bash
git clone https://github.com/manhoolee/Hoosland-real-estate-research-toolset.git
cd Hoosland-real-estate-research-toolset
git status --short
git rev-parse HEAD
```

运行回归并构建带 `/agent-tools` 前缀的前端：

```bash
python3.11 -m venv backend/.venv
. backend/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
PYTHON=python bash ./scripts/test.sh

VITE_API_BASE_URL=/hoosland-real-estate-research-toolset \
VITE_DEPLOYMENT_SLOT=single-linux \
VITE_APP_VERSION=0.2.2 \
npm --prefix frontend run build

test -s frontend/dist/index.html
```

部署前缀在前端构建时固定。更改 `/hoosland-real-estate-research-toolset` 必须同时修改：

- `VITE_API_BASE_URL` 并重新构建前端；
- Nginx `location`、message rate-limit map 与 `proxy_cookie_path`；
- 对外健康检查和书签地址。

生成 build ID，并把 Git 跟踪文件与前端构建复制到新 release：

```bash
HOOSLAND_BUILD_ID="v0.2.2-conversation-token-usage-20260828T023809Z"
HOOSLAND_RELEASE_DIR="/opt/hoosland-real-estate-research-toolset/releases/${HOOSLAND_BUILD_ID}"

sudo install -d -o root -g root -m 0755 "$HOOSLAND_RELEASE_DIR"
git archive HEAD | sudo tar -x -C "$HOOSLAND_RELEASE_DIR"
sudo install -d -o root -g root -m 0755 "$HOOSLAND_RELEASE_DIR/frontend/dist"
sudo cp -a frontend/dist/. "$HOOSLAND_RELEASE_DIR/frontend/dist/"

sudo python3.11 -m venv "$HOOSLAND_RELEASE_DIR/.venv"
sudo "$HOOSLAND_RELEASE_DIR/.venv/bin/python" -m pip install --upgrade pip
sudo "$HOOSLAND_RELEASE_DIR/.venv/bin/python" -m pip install \
  -r "$HOOSLAND_RELEASE_DIR/backend/requirements.txt"

sudo chown -R root:root "$HOOSLAND_RELEASE_DIR"
sudo chmod -R go-w "$HOOSLAND_RELEASE_DIR"
test -x "$HOOSLAND_RELEASE_DIR/.venv/bin/python"
test -s "$HOOSLAND_RELEASE_DIR/frontend/dist/index.html"
```

`requirements.txt` 除 Harness 外仍包含范围依赖，因此发布记录应保存实际安装清单：

```bash
sudo "$HOOSLAND_RELEASE_DIR/.venv/bin/python" -m pip freeze \
  | sudo tee "$HOOSLAND_RELEASE_DIR/python-freeze.txt" >/dev/null
sudo chmod 0444 "$HOOSLAND_RELEASE_DIR/python-freeze.txt"
```

首次部署建立 `current`：

```bash
sudo ln -s "$HOOSLAND_RELEASE_DIR" /opt/hoosland-real-estate-research-toolset/current
```

已有 `current` 时不要执行上面的首次命令，使用本文件后面的原子升级流程。

## 6. 配置生产环境

首次安装配置模板：

```bash
sudo install \
  -o root -g root -m 0600 \
  /opt/hoosland-real-estate-research-toolset/current/backend/.env.example \
  /etc/hoosland-real-estate-research-toolset/agent.env
sudoedit /etc/hoosland-real-estate-research-toolset/agent.env
```

生产关键值示例：

```dotenv
APP_ENV=production
APP_SLOT=single-linux
BUILD_ID=v0.2.2-conversation-token-usage-20260828T023809Z
HOST=127.0.0.1
PORT=8000
DATA_DIR=/srv/hoosland-real-estate-research-toolset/data
FRONTEND_DIST=/opt/hoosland-real-estate-research-toolset/current/frontend/dist
HARNESS_CORDIS_PATH=/opt/hoosland-real-estate-research-toolset/current/backend/cordis.yml
HARNESS_SKILL_DIRS=/opt/hoosland-real-estate-research-toolset/current/skills
DEEPSEEK_API_KEY=
CAPABILITY_MCP_URL=http://127.0.0.1:8000/mcp
ADMIN_PASSWORD=
ADMIN_SESSION_SECRET=
CONFIG_ENCRYPTION_KEY=
ADMIN_COOKIE_SECURE=true
```

必须使用密码管理器或组织 secrets 系统填入真实值。`ADMIN_SESSION_SECRET` 建议至少 48 个随机字符；独立 `CONFIG_ENCRYPTION_KEY` 必须是 Fernet key。可以分别生成：

```bash
python3.11 -c "import secrets; print(secrets.token_urlsafe(48))"
/opt/hoosland-real-estate-research-toolset/current/.venv/bin/python -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

这两个值一旦用于现有 `DATA_DIR` 就必须跨升级、重启和恢复保持一致。丢失或更换加密 key 会使已保存的 runtime 配置无法解密。

`PORT`、Uvicorn `--port`、`CAPABILITY_MCP_URL` 和 Nginx upstream 必须一致。修改端口不能只改 `agent.env`，还要同步修改 systemd unit 和 Nginx。

## 7. 安装并启动 systemd 服务

安装仓库中的强化 unit：

```bash
sudo install \
  -o root -g root -m 0644 \
  /opt/hoosland-real-estate-research-toolset/current/deploy/systemd/hoosland-real-estate-research-toolset.service.example \
  /etc/systemd/system/hoosland-real-estate-research-toolset.service

sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/hoosland-real-estate-research-toolset.service
sudo systemctl enable --now hoosland-real-estate-research-toolset.service
sudo systemctl status hoosland-real-estate-research-toolset.service
```

systemd manager 可以读取 root-only `EnvironmentFile`，服务用户不需要直接读取它。unit 必须继续使用 `current/.venv/bin/python`、`WorkingDirectory=current/backend` 和 `--workers 1`。

查看日志：

```bash
sudo journalctl -u hoosland-real-estate-research-toolset.service -n 200 --no-pager
sudo journalctl -u hoosland-real-estate-research-toolset.service -f
```

日志和截图中不得粘贴环境文件、请求正文、附件内容、Provider 响应或密钥。

## 8. 配置 Nginx、TLS 与访问控制

仓库示例假设外部地址为 `https://real-estate-research-toolset.example.com/hoosland-real-estate-research-toolset/`，且 DNS 与 TLS 证书已经由运维系统准备。复制前必须：

1. 替换域名和证书路径；
2. 接入组织自己的 SSO、OIDC、VPN、mTLS、Basic Auth 或可信 IP 策略；
3. 保留 `/mcp` 的精确 404 阻断；
4. 保留 SSE 的 `proxy_buffering off`；
5. 保留 `proxy_pass http://127.0.0.1:8000/` 尾部的 `/`，它负责剥离外部 `/hoosland-real-estate-research-toolset/` 前缀；
6. 核对上传大小、速率限制、Cookie path 和超时。

Debian / Ubuntu 的一种落盘方式：

```bash
sudo install \
  -o root -g root -m 0644 \
  /opt/hoosland-real-estate-research-toolset/current/deploy/nginx/hoosland-real-estate-research-toolset.conf.example \
  /etc/nginx/sites-available/hoosland-real-estate-research-toolset.conf
sudo ln -s \
  /etc/nginx/sites-available/hoosland-real-estate-research-toolset.conf \
  /etc/nginx/sites-enabled/hoosland-real-estate-research-toolset.conf

sudo nginx -t
sudo systemctl reload nginx
```

其他发行版应把同一配置放到该发行版 `http` 上下文实际 include 的目录。示例中的 `map` 和 `limit_req_zone` 必须位于 Nginx `http` 上下文，不能放进 `server` 或 `location`。

## 9. 可选 PDF runtime

PDF 不是默认安装项，只在 Linux 上提供持久运行时基线。先安装 Poppler 与 Playwright Chromium 所需系统库。Debian / Ubuntu 可在组织批准的包源中安装 `poppler-utils`；Playwright 依赖必须按目标发行版安装。

复制并安装固定的 root-owned runtime：

```bash
sudo install -d -o root -g root -m 0755 /opt/hoosland-real-estate-research-toolset/pdf-tool
sudo cp -a \
  /opt/hoosland-real-estate-research-toolset/current/deploy/pdf-tool/. \
  /opt/hoosland-real-estate-research-toolset/pdf-tool/

sudo /opt/hoosland-real-estate-research-toolset/pdf-tool/install-runtime.sh \
  /opt/hoosland-real-estate-research-toolset/pdf-tool

sudo /opt/hoosland-real-estate-research-toolset/pdf-tool/node_modules/.bin/playwright \
  install-deps chromium
```

确认命令和依赖：

```bash
command -v hoosland-pdf-render
command -v hoosland-pdf-inspect
command -v pdftoppm
test -x /opt/hoosland-real-estate-research-toolset/pdf-tool/render-html-to-pdf.mjs
test -x /opt/hoosland-real-estate-research-toolset/pdf-tool/inspect-pdf.py
```

PDF wrapper 默认使用 `/opt/hoosland-real-estate-research-toolset/current/.venv/bin/python`。服务用户只能读取 PDF runtime，不得拥有或修改它。不要允许 Agent 在 conversation 内临时执行 `pip install`、`npm install`、`npx playwright install` 或系统包安装。

安装完成后，必须通过应用生成一份含中文、分页、图片和链接的真实 HTML → PDF，并逐页渲染检查；仅有命令存在不等于 PDF 能力已验收。

## 10. 放行检查

先检查文件和本机入口：

```bash
test -s /opt/hoosland-real-estate-research-toolset/current/frontend/dist/index.html
curl --fail http://127.0.0.1:8000/api/health/live
curl --fail http://127.0.0.1:8000/api/health/ready \
  | /opt/hoosland-real-estate-research-toolset/current/.venv/bin/python -c \
    'import json,sys; value=json.load(sys.stdin); assert value["ready"] and value["frontend_built"]'
curl --fail http://127.0.0.1:8000/api/capabilities
```

再从受访问控制保护的外部入口检查：

```bash
curl --fail https://real-estate-research-toolset.example.com/hoosland-real-estate-research-toolset/
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  https://real-estate-research-toolset.example.com/hoosland-real-estate-research-toolset/mcp)" = "404"
```

健康检查不能替代真实验收。正式放行还必须完成：

1. 浏览器加载首页与静态资源，API 请求路径正确；
2. 一个真实模型最小对话，并确认总控与专项 Skill 实际执行；
3. 本次涉及的每个 Provider 真实调用；
4. 上传、成果打开与下载；
5. 刷新恢复、停止、失败重试和幂等边界；
6. Markdown 与独立 HTML 的实际生成和打开；
7. 按需 PDF 的生成、文本提取和逐页渲染；
8. 未授权访问被反向代理拒绝，公网 `/mcp` 返回 404；
9. `journalctl`、磁盘、备份与告警入口可用。
10. 对话运行中输入框上方的 Token 数值随 SSE 更新，刷新后与 `GET /api/conversations/{conversation_id}/usage` 一致。

## 11. 数据备份与恢复

`DATA_DIR` 包含 conversation、附件、成果、Harness sessions、operation logs、加密 runtime 配置，以及 V0.2.2 起每个 conversation 可选的 `usage.json` accounting sidecar。备份必须同时保存数据和对应的 `ADMIN_SESSION_SECRET` / `CONFIG_ENCRYPTION_KEY`，但两者不应存放在同一低权限归档中。

`usage.json` 使用独立 sidecar Schema `1`；缺失时 V0.2.2 返回 0，V0.2.1 会忽略该文件。Project state Schema 保持 `2.1.0`。从 V0.2.1 升级不需要预生成文件或运行迁移器，但升级前的历史 Token 不会回填。

优先使用文件系统或云盘的一致性快照。小型单机环境可以在维护窗口停服务后归档：

```bash
sudo systemctl stop hoosland-real-estate-research-toolset.service
sudo tar --acls --xattrs \
  -C /srv/hoosland-real-estate-research-toolset \
  -czf /secure-backup-location/hoosland-data-backup.tar.gz \
  data
sudo systemctl start hoosland-real-estate-research-toolset.service
```

备份路径、保留期、加密、异地副本与恢复演练由组织策略决定。恢复必须在隔离环境验证数据、密钥、Schema 与 release 兼容后再切回入口。

## 12. 原子升级

1. 在普通部署账户的独立 checkout 获取目标 commit；
2. 运行完整自动化测试和本次能力的真实验收；
3. 按第 5 节创建新的独立 release 与 `.venv`；
4. 核对 Schema、配置和数据兼容性并完成备份；
5. 记录当前 `readlink -f /opt/hoosland-real-estate-research-toolset/current`；
6. 原子切换 symlink，重启服务并执行完整放行检查。

V0.2.2 会惰性引入 usage sidecar Schema `1`：应用首次记录 Provider usage 时按 conversation 创建文件。不要为了“初始化”而批量改写旧 conversation，也不要把缺少 `usage.json` 视为数据损坏。

切换命令示例：

```bash
HOOSLAND_NEW_RELEASE="/opt/hoosland-real-estate-research-toolset/releases/replace-with-new-build-id"
HOOSLAND_SWITCH_LINK="/opt/hoosland-real-estate-research-toolset/current.replace-with-new-build-id"

sudo ln -s "$HOOSLAND_NEW_RELEASE" "$HOOSLAND_SWITCH_LINK"
sudo mv -Tf "$HOOSLAND_SWITCH_LINK" /opt/hoosland-real-estate-research-toolset/current
sudo systemctl restart hoosland-real-estate-research-toolset.service
sudo systemctl status hoosland-real-estate-research-toolset.service
```

仅切换 symlink 不会更新已经运行的进程，必须显式 `systemctl restart`。不要修改在线 release；配置变化后也必须重启，让旧 runner 全部退出。

真正无停机的 A/B 部署需要两个独立 service、端口、环境文件、`DATA_DIR`、secret 与 Nginx upstream。本仓库当前只提供单实例模板，不能把单实例步骤描述成已经完成 A/B。

## 13. 回滚

确认前一 release 与当前数据 Schema 仍兼容，然后原子切回并重启：

```bash
HOOSLAND_PREVIOUS_RELEASE="/opt/hoosland-real-estate-research-toolset/releases/replace-with-previous-build-id"
HOOSLAND_ROLLBACK_LINK="/opt/hoosland-real-estate-research-toolset/rollback.$(date +%s)"

sudo ln -s "$HOOSLAND_PREVIOUS_RELEASE" "$HOOSLAND_ROLLBACK_LINK"
sudo mv -Tf "$HOOSLAND_ROLLBACK_LINK" /opt/hoosland-real-estate-research-toolset/current
sudo systemctl restart hoosland-real-estate-research-toolset.service
```

回滚后重新检查 live、ready + `frontend_built`、外部页面、真实最小对话和成果读取。保留故障 release、日志与脱敏诊断用于复盘，不要为了回滚删除客户数据或覆盖另一份备份。

从 V0.2.2 回滚到 V0.2.1 时保留 `usage.json`：旧应用不会读取或更新它，删除反而会丢失已经观测到的统计；再次升级到 V0.2.2 时可继续读取回滚前的累计值。必须接受并记录一个边界：V0.2.1 回滚运行期间产生的 Token 不会计入 sidecar，重新升级后也无法回填这段缺口。

## 14. 停用

停用服务和入口：

```bash
sudo systemctl disable --now hoosland-real-estate-research-toolset.service
```

随后由运维系统移除 Nginx 入口并执行 `nginx -t`。停用不等于删除；在明确备份、保留期、客户授权和恢复要求之前，不要删除 `/srv/hoosland-real-estate-research-toolset/data`、secrets、release 或 PDF runtime。
