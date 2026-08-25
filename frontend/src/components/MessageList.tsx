import {
  ArrowClockwise,
  Buildings,
  ChatsTeardrop,
  ClockCountdown,
  FileText,
  User,
  WarningCircle,
} from "@phosphor-icons/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { RefObject } from "react";
import { presentResearchAssistantCopy } from "../api";
import type { ChatMessage } from "../types";

interface MessageListProps {
  messages: ChatMessage[];
  isHydrating: boolean;
  scrollRef: RefObject<HTMLDivElement | null>;
  onPromptSelect: (prompt: string) => void;
  onRetry: (messageId: string) => void;
}

const starterPrompts = [
  "比较两份项目资料，整理核心差异",
  "读取市场报告，输出一页投资摘要",
  "结合公开信息，核查材料中的关键数据",
];

function formatMessageTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function MessageSkeleton({ label, showLabel = true }: { label?: string; showLabel?: boolean }) {
  return (
    <div className="message-skeleton" aria-label={label || "正在生成回复"} role="status">
      {label && showLabel ? <p className="stream-status">{label}</p> : null}
      <span className="skeleton-line skeleton-line-long" />
      <span className="skeleton-line skeleton-line-medium" />
      <span className="skeleton-line skeleton-line-short" />
    </div>
  );
}

function AssistantProgress({ message }: { message: ChatMessage }) {
  if (message.status !== "streaming" || !message.progress) return null;
  const progress = message.progress;
  const progressValue = Math.round(
    ((progress.currentStep - 1) / progress.totalSteps) * 100,
  );

  return (
    <section
      className="assistant-progress"
      aria-label="研究进度"
      aria-live="polite"
      role="status"
    >
      <div className="assistant-progress-heading">
        <ClockCountdown size={16} weight="regular" aria-hidden="true" />
        <strong>{progress.label}</strong>
        <span>第 {progress.currentStep}/{progress.totalSteps} 阶段</span>
      </div>
      <div
        className="assistant-progress-track"
        aria-label={`已进入第 ${progress.currentStep} 个阶段`}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={progressValue}
        role="progressbar"
      >
        {Array.from({ length: progress.totalSteps }, (_, index) => (
          <span
            className={
              index < progress.currentStep - 1
                ? "complete"
                : index === progress.currentStep - 1
                  ? "current"
                  : ""
            }
            key={index}
          />
        ))}
      </div>
      <p>
        尚余约 {progress.remainingSteps} 个阶段（部分阶段可能合并）
        <span aria-hidden="true"> · </span>
        {progress.etaLabel}
      </p>
    </section>
  );
}

function EmptyConversation({ onPromptSelect }: Pick<MessageListProps, "onPromptSelect">) {
  return (
    <section className="empty-conversation" aria-labelledby="empty-title">
      <div className="empty-icon" aria-hidden="true">
        <ChatsTeardrop size={28} weight="regular" />
      </div>
      <h1 id="empty-title">从一个具体问题开始</h1>
      <p>
        上传市场报告、户型图或表格，再说明希望得到的结论。未指定格式时，默认交付 Markdown 与 HTML 双格式成果；需要 PDF 时可直接生成并打开下载。
      </p>
      <div className="starter-prompts" aria-label="示例问题">
        {starterPrompts.map((prompt) => (
          <button key={prompt} type="button" onClick={() => onPromptSelect(prompt)}>
            <span>{prompt}</span>
            <span className="prompt-action">填入</span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function MessageList({
  messages,
  isHydrating,
  scrollRef,
  onPromptSelect,
  onRetry,
}: MessageListProps) {
  return (
    <div className="message-viewport" ref={scrollRef}>
      <div className="message-column" aria-busy={isHydrating}>
        {isHydrating ? (
          <div className="history-loading">
            <MessageSkeleton label="正在读取对话" />
            <MessageSkeleton />
          </div>
        ) : messages.length === 0 ? (
          <EmptyConversation onPromptSelect={onPromptSelect} />
        ) : (
          messages.map((message) => (
            <article className={`message-row ${message.role}`} key={message.id}>
              <div className="message-avatar" aria-hidden="true">
                {message.role === "assistant" ? (
                  <Buildings size={18} weight="regular" />
                ) : (
                  <User size={18} weight="regular" />
                )}
              </div>
              <div className="message-body">
                <div className="message-meta">
                  <span>{message.role === "assistant" ? "研究助手" : "你"}</span>
                  <time dateTime={message.createdAt}>{formatMessageTime(message.createdAt)}</time>
                </div>

                {message.attachments?.length ? (
                  <div className="message-attachments" aria-label="本条消息引用的资料">
                    {message.attachments.map((attachment) => (
                      <span key={attachment.id}>
                        <FileText size={15} weight="regular" aria-hidden="true" />
                        {attachment.name}
                      </span>
                    ))}
                  </div>
                ) : null}

                {message.role === "assistant" ? <AssistantProgress message={message} /> : null}

                <div className="message-content">
                  {message.content ? (
                    message.role === "assistant" ? (
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          a: ({ children, ...props }) => (
                            <a {...props} target="_blank" rel="noreferrer">
                              {children}
                            </a>
                          ),
                        }}
                      >
                        {presentResearchAssistantCopy(message.content)}
                      </ReactMarkdown>
                    ) : (
                      <p>{message.content}</p>
                    )
                  ) : null}

                  {message.status === "error" ? (
                    <div className="message-error" role="alert">
                      <WarningCircle size={19} weight="regular" aria-hidden="true" />
                      <div>
                        <strong>研究暂未完成</strong>
                        <p>{message.errorMessage || "请检查服务连接后重试。"}</p>
                      </div>
                      {message.retryable !== false ? (
                        <button type="button" onClick={() => onRetry(message.id)}>
                          <ArrowClockwise size={16} weight="regular" aria-hidden="true" />
                          重试
                        </button>
                      ) : null}
                    </div>
                  ) : null}

                  {message.status === "stopped" ? (
                    <div className="message-stopped">
                      <span>生成已停止</span>
                      {message.retryable !== false ? (
                        <button type="button" onClick={() => onRetry(message.id)}>
                          <ArrowClockwise size={15} weight="regular" aria-hidden="true" />
                          重新生成
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  );
}
