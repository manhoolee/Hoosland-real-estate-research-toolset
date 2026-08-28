export const RELEASE_INFO = {
  releasedAt: "2026-08-28",
  iteration: "成果文件可靠持久化",
  compatibility: "兼容修复 · 无数据迁移 · V2 only",
  summary:
    "绑定唯一会话成果目录，在成功前核验本轮文件真实落盘，避免临时目录成果被误报为已交付。",
  changes: [
    {
      title: "唯一路径",
      description: "向研究助手明确注入当前会话 work 与 outputs 的唯一真实路径。",
    },
    {
      title: "成功硬门禁",
      description: "尝试生成成果但正式 outputs 未完整变化时，任务转为可重试失败，不再误报成功。",
    },
    {
      title: "原能力保留",
      description: "对话 Token 实时统计、旧文件读取和现有 conversation 数据均保持兼容。",
    },
  ],
} as const;
