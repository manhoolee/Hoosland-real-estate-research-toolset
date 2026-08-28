# Skill 套件 v2.3.1

本目录包含 1 个总控和 10 个专项 Skill。Harness 通过各 `SKILL.md` 的 `name` 与 `description` 自动发现；应用每轮确定性提交 `/comprehensive-real-estate-expert` 入口命令，Prompt/Skill 契约只允许该总控根据描述路由子 Skill，专项不得绕过总控成为入口。会话首行只证明入口命令已提交；总控正文是否实际加载仍需未来的显式回执或等价集成证据。

正式交付链：

```text
业务责任专项 → real-estate-report-editorial → real-estate-report-design
→ 按需 hoosland-pdf-output → real-estate-delivery-qa
```

运行 smoke tests：

```bash
bash ./tests/run_smoke_tests.sh
```

`manifest.json` 是套件版本和 Skill 顺序的机器可读清单。Skill 使用的 project_state / case payload Schema 仍为 `2.1.0`，套件版本仍为 `2.3.1`。V0.2.2 新增的 conversation `usage.json` 使用独立 sidecar Schema `1`，不修改 case payload 或 Skill 内容。
