import { ArrowUp, Paperclip, Stop } from "@phosphor-icons/react";
import { useId, useLayoutEffect, useRef } from "react";
import type { TokenUsage } from "../types";

const exactTokenFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });

function formatTokenCount(value: number): string {
  const count = Math.max(0, Math.trunc(value));
  if (count < 1_000) return exactTokenFormatter.format(count);
  const units = [
    { threshold: 1_000_000_000, suffix: "B" },
    { threshold: 1_000_000, suffix: "M" },
    { threshold: 1_000, suffix: "K" },
  ];
  const unit = units.find(({ threshold }) => count >= threshold) || units[2];
  const scaled = count / unit.threshold;
  const digits = scaled >= 100 ? 0 : 1;
  return `${Number(scaled.toFixed(digits))}${unit.suffix}`;
}

interface ComposerProps {
  value: string;
  tokenUsage: TokenUsage;
  attachedFileCount: number;
  isSending: boolean;
  isStopping: boolean;
  terminationPending: boolean;
  isUploading: boolean;
  disabled?: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  onFilesSelected: (files: File[]) => void;
}

export function Composer({
  value,
  tokenUsage,
  attachedFileCount,
  isSending,
  isStopping,
  terminationPending,
  isUploading,
  disabled,
  onChange,
  onSend,
  onStop,
  onFilesSelected,
}: ComposerProps) {
  const usageDetailsId = useId();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composingRef = useRef(false);
  const canSend =
    value.trim().length > 0 &&
    !disabled &&
    !isSending &&
    !isStopping &&
    !terminationPending;
  const totalTokens = Math.max(0, Math.trunc(tokenUsage.totalTokens));
  const usageAnnouncement = [
    `本对话已消耗 ${exactTokenFormatter.format(totalTokens)} Tokens`,
    `非缓存输入 ${exactTokenFormatter.format(tokenUsage.uncachedInputTokens)}`,
    `输出 ${exactTokenFormatter.format(tokenUsage.outputTokens)}`,
    tokenUsage.reasoningTokens
      ? `其中推理 ${exactTokenFormatter.format(tokenUsage.reasoningTokens)}`
      : "",
    `缓存读取 ${exactTokenFormatter.format(tokenUsage.cacheReadTokens)}`,
    `缓存写入 ${exactTokenFormatter.format(tokenUsage.cacheWriteTokens)}`,
  ].filter(Boolean).join("，");

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 152)}px`;
  }, [value]);

  return (
    <div className="composer-region">
      <div className="token-usage-meter">
        <span className="token-usage-track" aria-hidden="true" />
        <output
          className={`token-usage-readout${isSending ? " is-running" : ""}`}
          aria-live="polite"
          aria-atomic="true"
          aria-label={usageAnnouncement}
          aria-describedby={usageDetailsId}
          tabIndex={0}
        >
          <span className="token-usage-dot" aria-hidden="true" />
          <span>本对话已消耗</span>
          <strong>{formatTokenCount(totalTokens)}</strong>
          <span>Tokens</span>
          {isSending ? <span className="token-usage-live">计量中</span> : null}
        </output>
        <span id={usageDetailsId} className="token-usage-tooltip" role="tooltip">
          <span>非缓存输入 {exactTokenFormatter.format(tokenUsage.uncachedInputTokens)}</span>
          <span>输出 {exactTokenFormatter.format(tokenUsage.outputTokens)}</span>
          {tokenUsage.reasoningTokens ? (
            <span>其中推理 {exactTokenFormatter.format(tokenUsage.reasoningTokens)}</span>
          ) : null}
          <span>缓存读取 {exactTokenFormatter.format(tokenUsage.cacheReadTokens)}</span>
          <span>缓存写入 {exactTokenFormatter.format(tokenUsage.cacheWriteTokens)}</span>
        </span>
      </div>
      <div className="composer-box">
        <label className="sr-only" htmlFor="message-input">
          输入你的问题
        </label>
        <textarea
          id="message-input"
          ref={textareaRef}
          value={value}
          rows={1}
          placeholder="描述任务、范围和希望得到的结果"
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onCompositionStart={() => {
            composingRef.current = true;
          }}
          onCompositionEnd={() => {
            composingRef.current = false;
          }}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !composingRef.current &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              if (canSend) onSend();
            }
          }}
        />

        <div className="composer-toolbar">
          <div className="composer-tools">
            <input
              ref={fileInputRef}
              className="sr-only"
              type="file"
              multiple
              accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.ppt,.pptx,.txt,.md,image/*"
              onChange={(event) => {
                const files = Array.from(event.target.files || []);
                if (files.length) onFilesSelected(files);
                event.currentTarget.value = "";
              }}
            />
            <button
              className="composer-tool-button"
              type="button"
              disabled={disabled || isUploading}
              onClick={() => fileInputRef.current?.click()}
            >
              <Paperclip size={18} weight="regular" aria-hidden="true" />
              <span>{isUploading ? "正在上传" : "添加资料"}</span>
            </button>
            {attachedFileCount > 0 ? (
              <span className="attachment-count">已引用 {attachedFileCount} 份资料</span>
            ) : null}
          </div>

          {isSending || isStopping || terminationPending ? (
            <button
              className="stop-button"
              type="button"
              onClick={onStop}
              aria-label={
                isStopping ? "正在停止" : terminationPending ? "再次确认终止" : "停止生成"
              }
              disabled={isStopping}
            >
              <Stop size={17} weight="fill" aria-hidden="true" />
              <span>{isStopping ? "停止中" : terminationPending ? "再次确认" : "停止"}</span>
            </button>
          ) : (
            <button
              className="send-button"
              type="button"
              disabled={!canSend}
              onClick={onSend}
              aria-label="发送消息"
            >
              <ArrowUp size={19} weight="bold" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
      <p className="composer-hint">Enter 发送，Shift + Enter 换行。重要结论请结合原始资料复核。</p>
    </div>
  );
}
