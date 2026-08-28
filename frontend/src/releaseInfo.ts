export const RELEASE_INFO = {
  releasedAt: "2026-08-28",
  iteration: "清单写入自动恢复",
  compatibility: "兼容修复 · 无数据迁移 · V2 候选",
  summary:
    "任务清单写入被服务端拒绝时，自动同步最近一次已接受状态并继续逐项执行。",
  changes: [
    {
      title: "自动同步",
      description: "清单状态发生分叉时，将已接受的权威清单回注到当前运行并要求立即重置。",
    },
    {
      title: "门禁不放宽",
      description: "仍然拒绝批量完成、改名重排和缺少任务或成果要求的非法快照。",
    },
    {
      title: "快速止损",
      description: "连续忽略纠正或回注失败时立即终止并允许重试，避免任务长时间空跑。",
    },
  ],
} as const;
