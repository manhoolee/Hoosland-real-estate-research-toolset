# 部署说明

本说明提供脱敏的单机 Linux 基线，不代表现网拓扑。生产必须补充 TLS、访问控制、备份、配额、监控和组织自身的安全策略。

## 1. 目录建议

```text
/opt/hoosland-agent-tools/
├── releases/{build-id}/
├── current -> releases/{build-id}
└── venv/

/srv/hoosland-agent-tools/data/
/etc/hoosland-agent-tools/agent.env
```

每个 release 不可变；`current` 只在验收通过后原子切换。

## 2. 构建前端

```bash
cd frontend
npm ci
VITE_API_BASE_URL=/agent-tools \
VITE_DEPLOYMENT_SLOT=slot-b \
VITE_APP_VERSION=demo_v0.2 \
npm run build
```

## 3. 安装后端

```bash
python3.11 -m venv /opt/hoosland-agent-tools/venv
/opt/hoosland-agent-tools/venv/bin/pip install \
  -r /opt/hoosland-agent-tools/current/backend/requirements.txt
```

将 `backend/.env.example` 复制到 `/etc/hoosland-agent-tools/agent.env` 后修改路径和密钥。建议权限：

```bash
chown root:root /etc/hoosland-agent-tools/agent.env
chmod 0600 /etc/hoosland-agent-tools/agent.env
```

生产关键值示例：

```dotenv
APP_ENV=production
APP_SLOT=slot-b
BUILD_ID=replace-with-immutable-build-id
HOST=127.0.0.1
PORT=8000
DATA_DIR=/srv/hoosland-agent-tools/data
FRONTEND_DIST=/opt/hoosland-agent-tools/current/frontend/dist
HARNESS_CORDIS_PATH=/opt/hoosland-agent-tools/current/backend/cordis.yml
HARNESS_SKILL_DIRS=/opt/hoosland-agent-tools/current/skills
CAPABILITY_MCP_URL=http://127.0.0.1:8000/mcp
ADMIN_COOKIE_SECURE=true
```

## 4. systemd

复制 [systemd 示例](../deploy/systemd/hoosland-agent-tools.service.example)，按实际用户和目录调整：

```bash
systemctl daemon-reload
systemctl enable --now hoosland-agent-tools.service
systemctl status hoosland-agent-tools.service
```

保持 `--workers 1`。两个槽位应使用不同服务用户、端口、`DATA_DIR`、EnvironmentFile 和 secret。

## 5. Nginx

参考 [Nginx 示例](../deploy/nginx/hoosland-agent-tools.conf.example)。关键要求：

- TLS 终止；
- 对公网 `/mcp` 及其子路径返回 404；
- SSE 禁用代理缓冲；
- 长任务设置足够的 read/send timeout；
- 限制上传大小和消息请求频率；
- 管理 Cookie path 与部署前缀一致。

修改后：

```bash
nginx -t
systemctl reload nginx
```

## 6. PDF runtime

PDF 不是默认格式。需要 PDF 时，在固定路径预装一次运行时：

```bash
sudo install -d -m 0755 /opt/hoosland-agent-tools/pdf-tool
sudo cp -a deploy/pdf-tool/. /opt/hoosland-agent-tools/pdf-tool/
sudo /opt/hoosland-agent-tools/pdf-tool/install-runtime.sh \
  /opt/hoosland-agent-tools/pdf-tool
```

生产前确认以下命令在服务用户的 PATH 中：

```bash
command -v hoosland-pdf-render
command -v hoosland-pdf-inspect
test -x /opt/hoosland-agent-tools/pdf-tool/render-html-to-pdf.mjs
test -x /opt/hoosland-agent-tools/pdf-tool/inspect-pdf.py
```

安装脚本以 Linux、Playwright Chromium 和 Poppler 为基线。不要允许 Agent 在 conversation 内临时执行 `pip install`、`npm install`、`npx playwright install` 或系统包安装。

## 7. 放行检查

```bash
curl --fail http://127.0.0.1:8000/api/health/live
curl --fail http://127.0.0.1:8000/api/health/ready
curl --fail http://127.0.0.1:8000/api/capabilities
```

此外必须完成：

1. 一个真实模型最小对话；
2. 本次涉及的每个 Provider 真实调用；
3. 上传、成果打开与下载；
4. 刷新恢复、停止和失败重试；
5. 正式 Markdown/HTML，按需 PDF 的实际生成与渲染；
6. `/mcp` 公网阻断；
7. 另一槽位的服务与数据未受影响。

## 8. 回滚

1. 将入口切回前一稳定槽或移除新入口；
2. 恢复前一 Nginx 配置并执行 `nginx -t`；
3. 原子切回前一 `current` symlink 或启动前一槽；
4. 复测 live、ready、最小对话和成果读取；
5. 保留故障 release、日志和脱敏诊断用于复盘；
6. 不删除或覆盖另一槽的数据。
