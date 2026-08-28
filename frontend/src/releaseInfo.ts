export const RELEASE_INFO = {
  releasedAt: "2026-08-28",
  iteration: "任务清单与成果复核",
  compatibility: "兼容新增 · sidecar 惰性创建 · V2 候选",
  summary:
    "把每轮需求拆成任务与成果要求，运行中逐项更新，结束后保留已完成与未完成的复核结果。",
  changes: [
    {
      title: "需求拆解",
      description: "运行开始后生成任务与成果要求两组清单，并绑定到本轮任务。",
    },
    {
      title: "逐项复核",
      description: "执行中按项同步状态，文件成果还会与本轮实际落盘格式交叉核验。",
    },
    {
      title: "可靠恢复",
      description: "刷新、停止、失败和重试后仍显示对应运行的完整清单，不覆盖旧轮次。",
    },
  ],
} as const;
