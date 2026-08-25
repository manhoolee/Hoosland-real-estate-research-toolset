# 贡献指南

感谢改进 Hoosland Agent Tools。提交前请先阅读 [架构说明](docs/ARCHITECTURE.md) 和 [迭代原则](docs/ITERATION-PRINCIPLES.md)。

## 修改边界

- LLM/Provider、Harness、Skill 和 Application 分层修改；
- 全局安全、证据与权限规则只维护在 versioned System Prompt；
- Skill 只定义领域触发、方法、输入输出与质量闸门；
- Schema 变化必须附迁移器、兼容说明和回滚方案；
- 不提交客户数据、真实凭证、Cookie、日志、浏览器 profile、运行目录或生成包。

## 开发流程

1. 从 `main` 创建短生命周期分支；
2. 说明问题、影响层、版本变化和验收条件；
3. 为 bug 增加回归测试，为 Skill 变化增加触发/边界用例；
4. 更新 README、配置模板、使用说明或 CHANGELOG；
5. 运行完整验证；
6. 提交小而清楚的 commit，并在 PR 中记录测试结果和已知限制。

## 验证

```bash
bash ./scripts/test.sh
```

涉及模型、Provider、PDF 或浏览器行为时，还必须记录对应真实 E2E 结果。自动化测试不能替代真实能力验收。

## 提交要求

- 保持 `.sh`、`.py`、YAML 和部署文件为 LF；
- 保留所有运行脚本的 Unix 可执行位；
- `git diff --check` 无空白错误；
- 暂存区无密钥、客户材料、构建产物或内部拓扑；
- 第三方代码、字体、图片、模板或文字附来源和许可边界；
- 不把用户与 Agent 的对话、提示词、内部推理或质检流水写入正式示例。

建议 commit 前缀：`feat:`、`fix:`、`docs:`、`test:`、`refactor:`、`release:`。

## 许可

提交贡献即表示贡献者有权提交相应内容，并同意代码和 Skill 规则按 MIT、原创文档和示例按 CC BY 4.0 授权，除非双方另有书面约定。
