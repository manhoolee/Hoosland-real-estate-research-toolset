export const RELEASE_INFO = {
  releasedAt: "2026-08-28",
  iteration: "对话 Token 消耗可见",
  compatibility: "兼容更新 · usage sidecar v1 · 无迁移",
  summary:
    "按对话累计并实时展示 Provider 返回的 Token 消耗，刷新、取消和失败后仍可恢复已记录用量。",
  changes: [
    {
      title: "对话级累计",
      description: "按 conversation 汇总主 Agent、子 Agent、重试与压缩步骤的 Provider 用量。",
    },
    {
      title: "实时可见",
      description: "输入框上方持续显示当前对话累计 Token，并通过流式事件同步最新数值。",
    },
    {
      title: "兼容持久化",
      description: "用量保存为可选 sidecar；旧对话无需迁移，旧版本也可忽略该文件。",
    },
  ],
} as const;
