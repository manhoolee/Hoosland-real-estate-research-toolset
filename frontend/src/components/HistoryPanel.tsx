import {
  ArrowClockwise,
  CaretDown,
  ChatsTeardrop,
  ClockCounterClockwise,
  FolderOpen,
  LockKey,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { adminLogin, listProjects, type ProjectSummary } from "../api";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

interface HistoryPanelProps {
  currentProjectId: string | null;
  currentConversationId: string | null;
  onClose: () => void;
  onSelect: (projectId: string, conversationId: string) => boolean | Promise<boolean>;
}

function errorStatus(value: unknown): number | undefined {
  return value instanceof Error
    ? (value as Error & { status?: number }).status
    : undefined;
}

function formatHistoryTime(value: string | undefined): string {
  if (!value) return "更新时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "更新时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function HistoryPanel({
  currentProjectId,
  currentConversationId,
  onClose,
  onSelect,
}: HistoryPanelProps) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [expandedProjectIds, setExpandedProjectIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsAuthentication, setNeedsAuthentication] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);
  const [selectingId, setSelectingId] = useState<string | null>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const currentButtonRef = useRef<HTMLButtonElement>(null);
  const passwordInputRef = useRef<HTMLInputElement>(null);
  const loadSequenceRef = useRef(0);
  const initialFocusSetRef = useRef(false);

  const loadHistory = useCallback(async () => {
    const sequence = ++loadSequenceRef.current;
    setLoading(true);
    setError(null);
    setNeedsAuthentication(false);
    try {
      const nextProjects = await listProjects();
      if (sequence !== loadSequenceRef.current) return;
      setProjects(nextProjects);
      setExpandedProjectIds((current) => {
        const valid = new Set(
          [...current].filter((id) => nextProjects.some((project) => project.id === id)),
        );
        const preferred =
          nextProjects.find((project) => project.id === currentProjectId)?.id ||
          nextProjects[0]?.id;
        if (valid.size === 0 && preferred) valid.add(preferred);
        return valid;
      });
    } catch (caught) {
      if (sequence !== loadSequenceRef.current) return;
      setProjects([]);
      if (errorStatus(caught) === 401) {
        setNeedsAuthentication(true);
      } else {
        setError(caught instanceof Error ? caught.message : "无法读取历史项目。");
      }
    } finally {
      if (sequence === loadSequenceRef.current) setLoading(false);
    }
  }, [currentProjectId]);

  useEffect(() => {
    void loadHistory();
    return () => {
      loadSequenceRef.current += 1;
    };
  }, [loadHistory]);

  useEffect(() => {
    if (loading || initialFocusSetRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      (
        (needsAuthentication ? passwordInputRef.current : currentButtonRef.current) ||
        closeButtonRef.current ||
        dialogRef.current
      )?.focus();
      initialFocusSetRef.current = true;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [loading, needsAuthentication]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !selectingId && !loggingIn) {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      const activeIsInside = active instanceof HTMLElement && focusable.includes(active);
      if (event.shiftKey && (active === first || !activeIsInside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !activeIsInside)) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [loggingIn, onClose, selectingId]);

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const suppliedPassword = password.trim();
    if (!suppliedPassword || loggingIn) return;
    setLoggingIn(true);
    setLoginError(null);
    try {
      await adminLogin(suppliedPassword);
      setPassword("");
      initialFocusSetRef.current = false;
      await loadHistory();
    } catch (caught) {
      setLoginError(caught instanceof Error ? caught.message : "无法验证管理密码。");
    } finally {
      setLoggingIn(false);
    }
  };

  const toggleProject = (projectId: string) => {
    if (selectingId) return;
    setExpandedProjectIds((current) => {
      const next = new Set(current);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  };

  const handleSelect = async (projectId: string, conversationId: string) => {
    if (selectingId) return;
    if (conversationId === currentConversationId) {
      onClose();
      return;
    }

    setSelectingId(conversationId);
    setError(null);
    try {
      const selected = await onSelect(projectId, conversationId);
      if (selected) onClose();
      else setSelectingId(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法打开这个对话。");
      setSelectingId(null);
    }
  };

  return (
    <div
      className="history-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !selectingId && !loggingIn) onClose();
      }}
    >
      <aside
        id="history-dialog"
        ref={dialogRef}
        className="history-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-title"
        aria-describedby="history-description"
        aria-busy={loading || loggingIn || Boolean(selectingId)}
        tabIndex={-1}
      >
        <header className="history-header">
          <div>
            <h2 id="history-title">历史项目与对话</h2>
            <p id="history-description">先选择项目，再打开其中保存的对话。</p>
          </div>
          <button
            ref={closeButtonRef}
            className="history-close"
            type="button"
            onClick={onClose}
            aria-label="关闭历史项目与对话"
            disabled={Boolean(selectingId) || loggingIn}
          >
            <X size={20} weight="regular" aria-hidden="true" />
          </button>
        </header>

        <div className="history-content">
          {loading ? (
            <div className="history-loading" role="status">
              <span className="sr-only">正在读取历史项目</span>
              <span aria-hidden="true" />
              <span aria-hidden="true" />
              <span aria-hidden="true" />
            </div>
          ) : needsAuthentication ? (
            <div className="history-login-wrap">
              <form className="history-login" onSubmit={(event) => void handleLogin(event)}>
                <span className="history-login-icon" aria-hidden="true">
                  <LockKey size={21} weight="regular" />
                </span>
                <div>
                  <h3>解锁历史项目</h3>
                  <p id="history-login-help">项目可能包含客户资料，仅管理员可以查看。</p>
                </div>
                <label className="history-password-field">
                  <span>管理密码</span>
                  <input
                    ref={passwordInputRef}
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="current-password"
                    aria-describedby="history-login-help"
                    disabled={loggingIn}
                  />
                </label>
                {loginError ? <p className="history-login-error" role="alert">{loginError}</p> : null}
                <button
                  className="history-login-button"
                  type="submit"
                  disabled={loggingIn || !password.trim()}
                >
                  <LockKey size={17} weight="regular" aria-hidden="true" />
                  {loggingIn ? "正在验证" : "解锁历史项目"}
                </button>
              </form>
            </div>
          ) : error ? (
            <div className="history-error" role="alert">
              <ClockCounterClockwise size={24} weight="regular" aria-hidden="true" />
              <div>
                <h3>历史项目暂时无法读取</h3>
                <p>{error}</p>
              </div>
              <button type="button" onClick={() => void loadHistory()}>
                <ArrowClockwise size={17} weight="regular" aria-hidden="true" />
                重试
              </button>
            </div>
          ) : projects.length === 0 ? (
            <div className="history-empty">
              <ChatsTeardrop size={28} weight="regular" aria-hidden="true" />
              <h3>还没有历史项目</h3>
              <p>新建项目并开始研究后，项目与对话会出现在这里。</p>
            </div>
          ) : (
            <nav aria-label="已保存的项目与对话">
              <ul className="history-project-list">
                {projects.map((project) => {
                  const expanded = expandedProjectIds.has(project.id);
                  const isCurrentProject = project.id === currentProjectId;
                  const groupId = `history-project-${project.id}`;
                  return (
                    <li key={project.id} className={`history-project ${isCurrentProject ? "is-current" : ""}`}>
                      <button
                        className="history-project-toggle"
                        type="button"
                        aria-expanded={expanded}
                        aria-controls={groupId}
                        disabled={Boolean(selectingId)}
                        onClick={() => toggleProject(project.id)}
                      >
                        <span className="history-project-icon" aria-hidden="true">
                          <FolderOpen size={18} weight="regular" />
                        </span>
                        <span className="history-project-main">
                          <strong>{project.title || "未命名项目"}</strong>
                          <small>
                            {formatHistoryTime(project.updatedAt)} · {project.conversationCount} 条对话
                          </small>
                        </span>
                        {isCurrentProject ? <span className="history-project-current">当前项目</span> : null}
                        <CaretDown
                          className="history-project-caret"
                          size={16}
                          weight="regular"
                          aria-hidden="true"
                        />
                      </button>

                      {expanded ? (
                        <div id={groupId} className="history-conversation-rail">
                          {project.conversations.length ? (
                            <ul className="history-conversation-list">
                              {project.conversations.map((conversation) => {
                                const isCurrent = conversation.id === currentConversationId;
                                return (
                                  <li key={conversation.id}>
                                    <button
                                      ref={isCurrent ? currentButtonRef : undefined}
                                      className={`history-conversation-item ${isCurrent ? "is-current" : ""}`}
                                      type="button"
                                      aria-current={isCurrent ? "page" : undefined}
                                      disabled={Boolean(selectingId)}
                                      onClick={() => void handleSelect(project.id, conversation.id)}
                                    >
                                      <span className="history-conversation-dot" aria-hidden="true" />
                                      <span className="history-conversation-main">
                                        <strong>{conversation.title || "未命名对话"}</strong>
                                        {conversation.preview ? <small>{conversation.preview}</small> : null}
                                      </span>
                                      <span className="history-conversation-meta">
                                        <time dateTime={conversation.updatedAt}>
                                          {formatHistoryTime(conversation.updatedAt)}
                                        </time>
                                        <span>{conversation.messageCount} 条消息</span>
                                        {isCurrent ? <span className="history-current-label">当前对话</span> : null}
                                        {selectingId === conversation.id ? <span>正在打开</span> : null}
                                      </span>
                                    </button>
                                  </li>
                                );
                              })}
                            </ul>
                          ) : (
                            <p className="history-project-empty">这个项目还没有对话。</p>
                          )}
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </nav>
          )}
        </div>
      </aside>
    </div>
  );
}
