import { ArrowUp, Paperclip, Stop } from "@phosphor-icons/react";
import { useLayoutEffect, useRef } from "react";

interface ComposerProps {
  value: string;
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composingRef = useRef(false);
  const canSend =
    value.trim().length > 0 &&
    !disabled &&
    !isSending &&
    !isStopping &&
    !terminationPending;

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 152)}px`;
  }, [value]);

  return (
    <div className="composer-region">
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
