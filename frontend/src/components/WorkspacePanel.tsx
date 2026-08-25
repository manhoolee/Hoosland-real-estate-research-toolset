import {
  ArrowSquareOut,
  CheckCircle,
  DownloadSimple,
  FileText,
  Globe,
  ImageSquare,
  MagnifyingGlass,
  Question,
  UploadSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import type { CapabilityState, CapabilityView, WorkspaceFile } from "../types";

interface WorkspacePanelProps {
  open: boolean;
  conversationId: string | null;
  capabilities: CapabilityView[];
  files: WorkspaceFile[];
  isUploading: boolean;
  onClose: () => void;
  onFilesSelected: (files: File[]) => void;
  getDownloadUrl: (file: WorkspaceFile) => string;
  getOpenUrl: (file: WorkspaceFile) => string;
}

function CapabilityIcon({ id }: { id: string }) {
  if (id === "vision" || id === "image") return <ImageSquare size={19} weight="regular" />;
  if (id === "search") return <Globe size={19} weight="regular" />;
  if (id === "documents") return <FileText size={19} weight="regular" />;
  return <MagnifyingGlass size={19} weight="regular" />;
}

function StateIcon({ state }: { state: CapabilityState }) {
  if (state === "available") return <CheckCircle size={17} weight="regular" />;
  if (state === "unavailable") return <WarningCircle size={17} weight="regular" />;
  return <Question size={17} weight="regular" />;
}

function stateText(state: CapabilityState): string {
  if (state === "available") return "可用";
  if (state === "unavailable") return "未配置";
  if (state === "checking") return "检测中";
  return "待确认";
}

function formatFileSize(size: number): string {
  if (!size) return "大小未知";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function canOpenOutput(file: WorkspaceFile): boolean {
  if (file.kind !== "output") return false;
  return /\.(md|html|pdf)$/i.test(file.name);
}

function useDrawerViewport(): boolean {
  const [isDrawerViewport, setIsDrawerViewport] = useState(
    () => window.matchMedia("(max-width: 980px)").matches,
  );

  useEffect(() => {
    const query = window.matchMedia("(max-width: 980px)");
    const update = () => setIsDrawerViewport(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return isDrawerViewport;
}

export function WorkspacePanel({
  open,
  conversationId,
  capabilities,
  files,
  isUploading,
  onClose,
  onFilesSelected,
  getDownloadUrl,
  getOpenUrl,
}: WorkspacePanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const isDrawerViewport = useDrawerViewport();
  const drawerHidden = isDrawerViewport && !open;
  const fileGroups = [
    { id: "outputs", label: "研究成果", items: files.filter((file) => file.kind === "output") },
    { id: "inputs", label: "参考资料", items: files.filter((file) => file.kind !== "output") },
  ].filter((group) => group.items.length > 0);

  useEffect(() => {
    if (!isDrawerViewport || !open) return;
    const frame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [isDrawerViewport, open]);

  return (
    <aside
      id="workspace-panel"
      className={`workspace-panel ${open ? "is-open" : ""}`}
      aria-label="本次工作资料"
      aria-hidden={drawerHidden}
      inert={drawerHidden}
    >
      <div className="panel-heading">
        <div>
          <h2>本次工作</h2>
          <p>能力与资料</p>
        </div>
        <button
          ref={closeButtonRef}
          className="panel-close"
          type="button"
          onClick={onClose}
          aria-label="关闭工作资料"
        >
          <X size={19} weight="regular" aria-hidden="true" />
        </button>
      </div>

      <section className="panel-section" aria-labelledby="capabilities-title">
        <div className="section-heading-row">
          <h3 id="capabilities-title">可调用能力</h3>
        </div>
        <div className="capability-list">
          {capabilities.map((capability) => (
            <div className="capability-row" key={capability.id}>
              <span className="capability-icon" aria-hidden="true">
                <CapabilityIcon id={capability.id} />
              </span>
              <span className="capability-copy">
                <strong>{capability.label}</strong>
                <small>{capability.description}</small>
              </span>
              <span className={`capability-state ${capability.state}`}>
                <StateIcon state={capability.state} />
                {stateText(capability.state)}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel-section files-section" aria-labelledby="files-title">
        <div className="section-heading-row">
          <div>
            <h3 id="files-title">工作资料</h3>
            <p>{files.length ? `共 ${files.length} 份` : "尚未添加"}</p>
          </div>
        </div>

        <input
          ref={inputRef}
          className="sr-only"
          type="file"
          multiple
          accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.ppt,.pptx,.txt,.md,image/*"
          onChange={(event) => {
            const selected = Array.from(event.target.files || []);
            if (selected.length) onFilesSelected(selected);
            event.currentTarget.value = "";
          }}
        />
        <button
          className="upload-button"
          type="button"
          disabled={isUploading}
          onClick={() => inputRef.current?.click()}
        >
          <UploadSimple size={18} weight="regular" aria-hidden="true" />
          {isUploading ? "正在上传资料" : "上传资料"}
        </button>

        {files.length ? (
          <div className="file-list">
            {fileGroups.map((group) => (
              <section className="file-group" key={group.id} aria-labelledby={`file-group-${group.id}`}>
                <div className="file-group-heading">
                  <h4 id={`file-group-${group.id}`}>{group.label}</h4>
                  <span>{group.items.length} 份</span>
                </div>
                <div>
                  {group.items.map((file) => (
                    <div className={`file-row ${file.status}`} key={file.id}>
                      <span className="file-icon" aria-hidden="true">
                        <FileText size={19} weight="regular" />
                      </span>
                      <span className="file-copy">
                        <strong title={file.name}>{file.name}</strong>
                        <small>
                          {file.status === "uploading"
                            ? "正在上传"
                            : file.status === "error"
                              ? file.errorMessage || "上传失败"
                              : formatFileSize(file.size)}
                        </small>
                      </span>
                      {file.status === "ready" && conversationId ? (
                        <span className="file-actions">
                          {canOpenOutput(file) ? (
                            <a
                              className="file-open"
                              href={getOpenUrl(file)}
                              target="_blank"
                              rel="noreferrer"
                              aria-label={`打开 ${file.name}`}
                              title="打开文件"
                            >
                              <ArrowSquareOut size={18} weight="regular" aria-hidden="true" />
                            </a>
                          ) : null}
                          <a
                            className="file-download"
                            href={getDownloadUrl(file)}
                            download={file.name}
                            aria-label={`下载 ${file.name}`}
                            title="下载文件"
                          >
                            <DownloadSimple size={18} weight="regular" aria-hidden="true" />
                          </a>
                        </span>
                      ) : file.status === "error" ? (
                        <WarningCircle size={18} weight="regular" aria-label="上传失败" />
                      ) : null}
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <div className="files-empty">
            <FileText size={24} weight="regular" aria-hidden="true" />
            <p>PDF、表格、文档和图片都会出现在这里。</p>
          </div>
        )}
      </section>
    </aside>
  );
}
