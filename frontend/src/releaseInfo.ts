export const RELEASE_INFO = {
  releasedAt: "2026-08-27",
  iteration: "生产基线归档与版本信息可见",
  compatibility: "兼容更新 · 无数据迁移",
  summary:
    "将已在线验证的总控优先、默认双格式与失败关闭行为纳入可重建源码基线，并补齐公开版本身份。",
  changes: [
    {
      title: "生产行为归档",
      description: "固化总控优先路由、总控缺失时失败关闭，以及本轮输出格式审计。",
    },
    {
      title: "默认双格式交付",
      description: "地产研究与报告类任务在未指定格式时默认生成 Markdown 与独立 HTML。",
    },
    {
      title: "版本来源可见",
      description: "页面展示实时应用版本与 Build ID，并提供 GitHub 源码和完整更新记录入口。",
    },
  ],
} as const;
