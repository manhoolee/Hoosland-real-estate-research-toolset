export const RELEASE_INFO = {
  releasedAt: "2026-09-16",
  iteration: "研究请求与成果检查边界修复",
  compatibility: "兼容升级 · 无数据迁移",
  summary: "改善政策、销售模型、项目供应商等正常研究请求的识别，保留内部信息保护，并补充文本成果检查。",
  changes: [
    { title: "正常研究更顺畅", description: "购房政策、销售模型参数、营销工具和供应商分析可正常处理。" },
    { title: "来源链接正常显示", description: "公开来源网址中的普通路径可正常通过成果检查。" },
    { title: "文本成果完整检查", description: "检查大文本文件的中间内容，并识别改扩展名的纯文本。" },
  ],
} as const;
