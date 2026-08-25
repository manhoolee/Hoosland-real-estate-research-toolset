# GitHub 公开参照与吸收原则

本文件只记录公开项目的结构性启发，不直接复制其代码、品牌、文字或平台自动化实现。

## 1. 社交内容拆解与再利用

- [coreyhaines31/marketingskills — social/SKILL.md](https://github.com/coreyhaines31/marketingskills/blob/main/skills/social/SKILL.md)

吸收：先问目标、受众、品牌语气和资源，再把长内容拆成 content atoms，按平台改写，并安排发布节奏。

取舍：本套件增加地产证据等级、项目承诺边界、规划/工程状态和发布授权闸门。

## 2. 图文与社交封面视觉

- [op7418/guizang-ppt-skill](https://github.com/op7418/guizang-ppt-skill)

吸收：视觉系统先于模板，允许同一内容生成公众号封面、社交卡片、轮播和视频缩略图等多个比例。

取舍：本套件坚持图表必须来自真实数据，效果图、概念图和AI生成图必须显式标注。

## 3. 数据图和 Markdown 交付

- [markdown-viewer/skills](https://github.com/markdown-viewer/skills)

吸收：将图表、流程图和文档作为可复用技能资源，保持 Markdown 到交付物的可追溯关系。

取舍：本套件优先使用项目数据、来源和口径，不用图形替代风险、来源和法定条件表格。

## 4. 小红书发布自动化的安全边界

- [white0dew/XiaohongshuSkills](https://github.com/white0dew/XiaohongshuSkills)
- [jackwener/xhs-cli](https://github.com/jackwener/xhs-cli/blob/main/SKILL.md)

吸收：发布动作应独立于内容生成，先预览再发布，平台登录和本地会话由用户掌握。

取舍：本套件不保存 Cookie、验证码、恢复码，不默认执行自动评论、关注、私信或绕过风控；真实发布须获得明确授权。

## 5. Skill 结构与渐进式加载

- [MengTo/Skills](https://github.com/MengTo/Skills)
- [GitHub Copilot custom skills 文档](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/skills)

吸收：SKILL.md 保持工作流简洁，平台规则、视觉参照和示例放进 references，减少每次调用的上下文负担。

## 参照结论

本子 skill 采用“内容生成—平台适配—视觉素材—发布前质检—明确授权发布”的五段式结构，避免把社交媒体宣传做成单纯文案改写或未经审核的自动发帖器。
