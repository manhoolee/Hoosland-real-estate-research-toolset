# Skill 套件 v2.3.0

本目录包含 1 个总控和 10 个专项 Skill。Harness 通过各 `SKILL.md` 的 `name` 与 `description` 自动发现和路由。

正式交付链：

```text
业务责任专项 → real-estate-report-editorial → real-estate-report-design
→ 按需 hoosland-pdf-output → real-estate-delivery-qa
```

运行 smoke tests：

```bash
bash ./tests/run_smoke_tests.sh
```

`manifest.json` 是套件版本和 Skill 顺序的机器可读清单。项目状态文件中的 Schema `2.1.0` 与套件版本 `2.3.0` 独立管理。
