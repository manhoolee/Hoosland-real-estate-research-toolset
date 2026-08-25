# GitHub 模板参照：报告视觉设计

本文件只记录参照方向，不复制第三方代码或素材。

## 参照

- [Google DESIGN.md](https://github.com/google-labs-code/design.md)：借鉴用 YAML front matter 定义颜色、字体、间距和组件 token，再用 Markdown 说明设计理由；其 lint/diff 思路适合做版本回归。
- [Quarto HTML Themes](https://quarto.org/docs/output-formats/html-themes.html)：借鉴主题与 CSS 分离、页面级样式和多种输出格式的组织方式。
- [Edinburgh Genome Foundry pdf_reports](https://github.com/Edinburgh-Genome-Foundry/pdf_reports)：借鉴模板、样式表和 PDF 渲染器分离，以及可复用 ReportWriter 的思路。
- [Black Lantern Security WriteHat](https://github.com/blacklanternsecurity/writehat)：借鉴“报告由组件组成、页面模板统一控制、HTML/PDF 共用组件”的结构。

## 吸收方式

v2.3 的报告设计以 `DESIGN.md` 或等价 token 文件作为视觉单一事实源；封面、摘要卡、表格、风险矩阵、来源页和页脚作为可复用组件；同一内容分别渲染 HTML、PDF 和移动版后再验收。
