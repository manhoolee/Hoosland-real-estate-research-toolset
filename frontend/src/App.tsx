import {
  ArrowLeft,
  Buildings,
  ClockCounterClockwise,
  Cloud,
  CloudCheck,
  CloudSlash,
  Files,
  FolderPlus,
  GearSix,
  GithubLogo,
  Plus,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createConversation,
  createProject,
  cancelConversation,
  fileDownloadUrl,
  fileOpenUrl,
  getCapabilities,
  getConversation,
  getConversationRun,
  getConversationUsage,
  getReleaseIdentity,
  getPendingIntake,
  listFiles,
  listMessages,
  prepareIntake,
  cancelPendingIntake,
  presentResearchAssistantCopy,
  sendMessage,
  uploadFile,
  type ApiCapability,
  type CapabilityResponse,
  type ConversationRunState,
  type ReleaseIdentity,
} from "./api";
import { Composer } from "./components/Composer";
import { HistoryPanel } from "./components/HistoryPanel";
import { MessageList } from "./components/MessageList";
import { ReleaseInfoDialog } from "./components/ReleaseInfoDialog";
import { SettingsPanel } from "./components/SettingsPanel";
import { WorkspacePanel } from "./components/WorkspacePanel";
import { createClientId } from "./clientId";
import {
  APP_TITLE,
  APP_VERSION,
  GITHUB_REPOSITORY_URL,
  STORAGE_NAMESPACE,
} from "./deployment";
import type {
  AssistantProgress,
  CapabilityState,
  CapabilityView,
  ChatMessage,
  ClarificationAnswer,
  ClarificationPlan,
  PendingClarification,
  RunChecklist,
  TokenUsage,
  WorkspaceFile,
} from "./types";

const SESSION_CONVERSATION_KEY = `${STORAGE_NAMESPACE}:conversation`;
const SESSION_PROJECT_KEY = `${STORAGE_NAMESPACE}:project`;
const HOOSLAND_HOME_URL = "http://hoosland.com/";
const RECOVERY_RECONNECT_NOTICE = "后台任务仍在运行，页面正在重新连接；无需重复发送。";

const EMPTY_TOKEN_USAGE: TokenUsage = {
  uncachedInputTokens: 0,
  outputTokens: 0,
  cacheReadTokens: 0,
  cacheWriteTokens: 0,
  totalTokens: 0,
};

const capabilityDefinitions = [
  {
    id: "documents",
    label: "文档读取",
    description: "PDF、表格与办公文档",
    aliases: ["document", "file", "pdf", "office", "read"],
  },
  {
    id: "pdf-output",
    label: "PDF 输出",
    description: "正式报告直接生成与逐页质检",
    aliases: ["pdf_output", "pdf export", "pdf render", "pdf output"],
  },
  {
    id: "vision",
    label: "视觉理解",
    description: "户型图、截图与扫描件",
    aliases: ["vision", "ocr", "visual", "image analysis"],
  },
  {
    id: "search",
    label: "联网检索",
    description: "公开信息检索与核查",
    aliases: ["search", "web", "browser", "internet"],
  },
  {
    id: "image",
    label: "图像生成",
    description: "报告配图与图像处理",
    aliases: ["image generation", "image_generate", "image", "draw"],
  },
];

function createInitialCapabilities(): CapabilityView[] {
  return capabilityDefinitions.map(({ id, label, description }) => ({
    id,
    label,
    description,
    state: "checking",
  }));
}

function capabilityState(item: ApiCapability | undefined): CapabilityState {
  if (!item) return "unknown";
  if (item.available === true || item.enabled === true || item.configured === true) return "available";
  if (item.available === false || item.enabled === false || item.configured === false) return "unavailable";
  const state = String(item.status || item.state || "").toLowerCase();
  if (["ready", "available", "healthy", "ok", "connected", "enabled", "configured"].includes(state)) {
    return "available";
  }
  if (["disabled", "unavailable", "error", "missing", "offline", "not_configured"].includes(state)) {
    return "unavailable";
  }
  return "unknown";
}

function normaliseCapabilityItems(response: CapabilityResponse): ApiCapability[] {
  if (Array.isArray(response.items)) return response.items;
  if (Array.isArray(response.capabilities)) return response.capabilities;
  if (response.capabilities && typeof response.capabilities === "object") {
    return Object.entries(response.capabilities).map(([key, value]) => ({
      id: key,
      name: key,
      available: typeof value === "boolean" ? value : undefined,
      status: typeof value === "string" ? value : undefined,
    }));
  }
  return [];
}

function mapCapabilities(response: CapabilityResponse): CapabilityView[] {
  const items = normaliseCapabilityItems(response);
  return capabilityDefinitions.map((definition) => {
    const item = items.find((candidate) => {
      const key = [candidate.id, candidate.key, candidate.name, candidate.label]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return definition.aliases.some((alias) => key.includes(alias));
    });
    return {
      id: definition.id,
      label: definition.label,
      description: definition.description,
      state: capabilityState(item),
    };
  });
}

function initialConversationId(): string | null {
  const queryId = new URLSearchParams(window.location.search).get("conversation");
  return queryId || window.sessionStorage.getItem(SESSION_CONVERSATION_KEY);
}

function initialProjectId(): string | null {
  const queryId = new URLSearchParams(window.location.search).get("project");
  return queryId || window.sessionStorage.getItem(SESSION_PROJECT_KEY);
}

function syncConversationUrl(projectId: string | null, conversationId: string | null): void {
  const url = new URL(window.location.href);
  if (projectId) url.searchParams.set("project", projectId);
  else url.searchParams.delete("project");
  if (conversationId) url.searchParams.set("conversation", conversationId);
  else url.searchParams.delete("conversation");
  window.history.replaceState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

function isMissingConversation(error: unknown): boolean {
  return error instanceof Error && (error as Error & { status?: number }).status === 404;
}

interface FailedRequest {
  content: string;
  attachmentIds: string[];
  retryOf?: string;
  clientRequestId?: string;
  /** Conversation captured when an optimistic turn was created. */
  conversationId?: string;
  intake?: {
    id: string;
    action: "confirm" | "skip";
    answers: ClarificationAnswer[];
  };
}

type ServiceState = "checking" | "connected" | "unavailable";

const INITIAL_RESEARCH_PROGRESS: AssistantProgress = {
  stage: "brief",
  label: "正在确认研究目标与交付要求",
  currentStep: 1,
  totalSteps: 4,
  remainingSteps: 4,
  etaLabel: "复杂任务通常还需 5–12 分钟",
};

const RECOVERED_RESEARCH_PROGRESS: AssistantProgress = {
  stage: "recovery",
  label: "后台任务仍在运行，正在同步最新结果",
  currentStep: 1,
  totalSteps: 4,
  remainingSteps: 4,
  etaLabel: "刷新不会中断任务",
};

function errorCode(error: unknown): string | undefined {
  return error instanceof Error
    ? (error as Error & { code?: string }).code
    : undefined;
}

function errorStatus(error: unknown): number | undefined {
  return error instanceof Error
    ? (error as Error & { status?: number }).status
    : undefined;
}

function errorReplyTo(error: unknown): string | undefined {
  return error instanceof Error
    ? (error as Error & { replyTo?: string }).replyTo
    : undefined;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function mergeTokenUsage(previous: TokenUsage | undefined, next: TokenUsage): TokenUsage {
  if (!previous) return next;
  const previousTime = Date.parse(previous.updatedAt || "");
  const nextTime = Date.parse(next.updatedAt || "");
  if (Number.isFinite(previousTime) && Number.isFinite(nextTime)) {
    return nextTime < previousTime ? previous : next;
  }
  if (Number.isFinite(nextTime)) return next;

  const merged = {
    ...next,
    conversationId: next.conversationId || previous.conversationId,
    uncachedInputTokens: Math.max(previous.uncachedInputTokens, next.uncachedInputTokens),
    outputTokens: Math.max(previous.outputTokens, next.outputTokens),
    cacheReadTokens: Math.max(previous.cacheReadTokens, next.cacheReadTokens),
    cacheWriteTokens: Math.max(previous.cacheWriteTokens, next.cacheWriteTokens),
    reasoningTokens: Math.max(previous.reasoningTokens || 0, next.reasoningTokens || 0),
    updatedAt: previous.updatedAt,
  };
  return {
    ...merged,
    totalTokens: Math.max(
      previous.totalTokens,
      next.totalTokens,
      merged.uncachedInputTokens +
        merged.outputTokens +
        merged.cacheReadTokens +
        merged.cacheWriteTokens,
    ),
  };
}

function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = () => {
      window.clearTimeout(timer);
      resolve();
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function publicResearchError(error: unknown): string {
  const message = error instanceof Error ? presentResearchAssistantCopy(error.message.trim()) : "";
  if (
    [
      "INTAKE_NOT_FOUND",
      "INTAKE_EXPIRED",
      "INTAKE_ID_MISMATCH",
      "INTAKE_PAYLOAD_MISMATCH",
      "INTAKE_RETRY_MISMATCH",
      "INTAKE_ALREADY_PENDING",
      "INTAKE_ALREADY_CONSUMED",
      "INTAKE_ACTION_CONFLICT",
      "INTAKE_ID_REQUIRED",
      "INTAKE_PROTOCOL_INVALID",
      "MISSING_ANSWER",
      "INVALID_ANSWER",
      "INVALID_ANSWERS",
      "INVALID_ACTION",
      "UNKNOWN_OPTION",
      "UNKNOWN_QUESTION",
      "EMPTY_ANSWER",
      "TOO_MANY_OPTIONS",
      "TOO_MANY_ANSWERS",
      "CUSTOM_NOT_ALLOWED",
      "CUSTOM_TOO_LONG",
      "POLICY_REJECTED",
    ].includes(errorCode(error) || "")
  ) return message || "任务引导已失效，请重新确认后再开始。";
  if (
    ["RUN_ACTIVE", "RUN_TERMINATING", "RUN_CLEANUP_PENDING", "CONFIG_UPDATE_ACTIVE"].includes(
      errorCode(error) || "",
    ) || /上一轮研究|上一条消息|后台运行|正在终止|配置正在更新/.test(message)
  ) return message;
  return "本轮研究暂未完成，请重试；详细原因已记录在后台。";
}

function userRequest(message: ChatMessage): FailedRequest {
  return {
    content: message.content,
    attachmentIds: message.attachmentIds || [],
    retryOf: message.id.startsWith("msg_") ? message.id : undefined,
  };
}

function sameAttachmentIds(left: string[] = [], right: string[] = []): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function requestWasPersisted(
  request: FailedRequest,
  run: ConversationRunState,
  history: ChatMessage[],
  clientRequestId: string,
): boolean {
  if (run.clientRequestId !== clientRequestId || !run.userMessageId) return false;
  const user = history.find(
    (message) => message.role === "user" && message.id === run.userMessageId,
  );
  return Boolean(
    user &&
    user.content.trim() === request.content.trim() &&
    sameAttachmentIds(user.attachmentIds, request.attachmentIds),
  );
}

function guidedRequestWasPersisted(
  request: FailedRequest,
  run: ConversationRunState,
  history: ChatMessage[],
  clientRequestId: string,
): boolean {
  // Guided turns must use the same server-issued request/run correlation as
  // ordinary turns.  Matching only content, attachments, or a stale
  // user-message id can silently accept an older identical request after a
  // setup failure.  Keeping the optimistic error in that ambiguous case is
  // safer: the user can retry once the authoritative run snapshot converges.
  return requestWasPersisted(request, run, history, clientRequestId);
}

function sameRunSnapshot(
  left: ConversationRunState,
  right: ConversationRunState,
): boolean {
  return (
    left.status === right.status &&
    left.active === right.active &&
    left.retryable === right.retryable &&
    left.clientRequestId === right.clientRequestId &&
    left.userMessageId === right.userMessageId &&
    left.startedAt === right.startedAt &&
    left.updatedAt === right.updatedAt &&
    left.completedAt === right.completedAt &&
    left.checklist?.revision === right.checklist?.revision
  );
}

function withNewerChecklist(
  message: ChatMessage,
  checklist: RunChecklist | undefined,
): ChatMessage {
  if (!checklist) return message;
  const current = message.checklist;
  if (current) {
    if (current.revision > checklist.revision) return message;
    if (current.revision === checklist.revision) {
      const currentIsActive = ["planning", "running"].includes(current.phase);
      const nextIsTerminal = !["planning", "running"].includes(checklist.phase);
      // A pending durable commit is deliberately projected as running. Once
      // /run repairs that commit, the same persisted revision may converge to
      // its terminal phase; no other same-revision replacement is accepted.
      if (!currentIsActive || !nextIsTerminal) return message;
    }
  }
  return { ...message, checklist };
}

function withRunChecklist(
  messages: ChatMessage[],
  run: ConversationRunState,
): ChatMessage[] {
  if (!run.checklist || !run.userMessageId) return messages;
  let targetIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "assistant" && message.replyTo === run.userMessageId) {
      targetIndex = index;
      break;
    }
  }
  if (targetIndex < 0) return messages;
  const current = messages[targetIndex];
  const updated = withNewerChecklist(current, run.checklist);
  if (updated === current) return messages;
  const next = messages.slice();
  next[targetIndex] = updated;
  return next;
}

function withAttachmentNames(
  history: ChatMessage[],
  savedFiles: WorkspaceFile[],
): ChatMessage[] {
  const names = new Map(savedFiles.map((file) => [file.id, file.name] as const));
  return history.map((message) => {
    if (message.role !== "user" || !message.attachmentIds?.length) return message;
    return {
      ...message,
      attachments: message.attachmentIds.map((id) => ({
        id,
        name: names.get(id) || "历史附件",
      })),
    };
  });
}

function reconcileMessages(
  history: ChatMessage[],
  run: ConversationRunState,
): ChatMessage[] {
  const projectedHistory = withRunChecklist(history, run);
  const successfulReplies = new Set(
    projectedHistory
      .filter((message) => message.role === "assistant" && message.status === "complete")
      .map((message) => message.replyTo)
      .filter((value): value is string => Boolean(value)),
  );
  const activeUserId = run.active ? run.userMessageId : undefined;
  const latestTerminalReplies = new Map<string, string>();
  for (const message of projectedHistory) {
    if (
      message.role === "assistant" &&
      (message.status === "error" || message.status === "stopped") &&
      message.replyTo
    ) latestTerminalReplies.set(message.replyTo, message.id);
  }
  const cleaned = projectedHistory.filter((message) => !(
    message.role === "assistant" &&
    (message.status === "error" || message.status === "stopped") &&
    message.replyTo &&
    (
      successfulReplies.has(message.replyTo) ||
      message.replyTo === activeUserId ||
      latestTerminalReplies.get(message.replyTo) !== message.id
    )
  ));
  const replied = new Set(
    cleaned
      .filter((message) => message.role === "assistant" && message.replyTo)
      .map((message) => message.replyTo as string),
  );
  const unresolvedUser = (
    activeUserId
      ? cleaned.find((message) => message.role === "user" && message.id === activeUserId)
      : undefined
  ) || (
    !activeUserId
      ? [...cleaned].reverse().find(
        (message) => message.role === "user" && !replied.has(message.id),
      )
      : undefined
  );
  if (!unresolvedUser || replied.has(unresolvedUser.id)) return cleaned;

  if (run.active) {
    return [
      ...cleaned,
      {
        id: `recovered-running-${unresolvedUser.id}`,
        role: "assistant",
        content: "",
        createdAt: run.startedAt || unresolvedUser.createdAt,
        status: "streaming",
        replyTo: unresolvedUser.id,
        retryable: false,
        progress: RECOVERED_RESEARCH_PROGRESS,
        checklist: run.checklist,
      },
    ];
  }

  if (
    !run.retryable ||
    !["failed", "cancelled", "interrupted"].includes(run.status)
  ) return cleaned;
  const stopped = run.status === "cancelled";
  return [
    ...cleaned,
    {
      id: `recovered-terminal-${unresolvedUser.id}`,
      role: "assistant",
      content: "",
      createdAt: run.completedAt || new Date().toISOString(),
      status: stopped ? "stopped" : "error",
      replyTo: unresolvedUser.id,
      retryable: true,
      checklist: run.checklist,
      errorMessage: stopped
        ? "本次研究已终止，可以重新生成。"
        : "上次后台任务没有保存完整结果，可以从原请求继续重试。",
    },
  ];
}

function recoverFailedRequests(messages: ChatMessage[]): Map<string, FailedRequest> {
  const users = new Map(
    messages
      .filter((message) => message.role === "user")
      .map((message) => [message.id, message] as const),
  );
  const result = new Map<string, FailedRequest>();
  for (const message of messages) {
    if (
      message.role !== "assistant" ||
      (message.status !== "error" && message.status !== "stopped") ||
      message.retryable === false ||
      !message.replyTo
    ) continue;
    const user = users.get(message.replyTo);
    if (user) result.set(message.id, userRequest(user));
  }
  return result;
}

export default function App() {
  const initialIdRef = useRef(initialConversationId());
  const initialProjectIdRef = useRef(initialProjectId());
  const [projectId, setProjectId] = useState<string | null>(initialProjectIdRef.current);
  const projectIdRef = useRef<string | null>(initialProjectIdRef.current);
  const [conversationId, setConversationId] = useState<string | null>(initialIdRef.current);
  const conversationIdRef = useRef<string | null>(initialIdRef.current);
  const conversationPromiseRef = useRef<Promise<string> | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tokenUsageByConversation, setTokenUsageByConversation] = useState<
    Record<string, TokenUsage>
  >({});
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilityView[]>(createInitialCapabilities);
  const [serviceState, setServiceState] = useState<ServiceState>("checking");
  const [releaseIdentity, setReleaseIdentity] = useState<ReleaseIdentity | null>(null);
  const [draft, setDraft] = useState("");
  const [pendingClarification, setPendingClarification] = useState<PendingClarification | null>(null);
  const [isPreparingIntake, setIsPreparingIntake] = useState(false);
  const [isHydrating, setIsHydrating] = useState(Boolean(initialIdRef.current));
  const [isSending, setIsSending] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [terminationPending, setTerminationPending] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [isContextChanging, setIsContextChanging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const panelTriggerRef = useRef<HTMLButtonElement>(null);
  const historyTriggerRef = useRef<HTMLButtonElement>(null);
  const settingsTriggerRef = useRef<HTMLButtonElement>(null);
  const releaseReturnFocusRef = useRef<HTMLElement | null>(null);
  const activeRequestRef = useRef<AbortController | null>(null);
  const preparingIntakeRef = useRef(false);
  const clarificationSubmittingRef = useRef(false);
  const cancellationRequestsRef = useRef(new Map<AbortController, Promise<boolean>>());
  const pendingCancellationRef = useRef<{
    controller: AbortController;
    conversationId: string;
  } | null>(null);
  const failedRequestsRef = useRef(new Map<string, FailedRequest>());
  const recoveryGenerationRef = useRef(0);
  const recoveryControllerRef = useRef<AbortController | null>(null);

  const readyFiles = useMemo(
    () => files.filter((file) => file.status === "ready" && file.kind !== "output"),
    [files],
  );
  const tokenUsage = useMemo(
    () => conversationId
      ? tokenUsageByConversation[conversationId] || {
          ...EMPTY_TOKEN_USAGE,
          conversationId,
        }
      : EMPTY_TOKEN_USAGE,
    [conversationId, tokenUsageByConversation],
  );
  const isUploading = files.some((file) => file.status === "uploading");

  const closePanel = useCallback(() => {
    setPanelOpen(false);
    window.requestAnimationFrame(() => panelTriggerRef.current?.focus());
  }, []);

  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    window.requestAnimationFrame(() => settingsTriggerRef.current?.focus());
  }, []);

  const closeHistory = useCallback(() => {
    setHistoryOpen(false);
    window.requestAnimationFrame(() => historyTriggerRef.current?.focus());
  }, []);

  const openReleaseInfo = useCallback((trigger: HTMLElement) => {
    releaseReturnFocusRef.current = trigger;
    setReleaseOpen(true);
  }, []);

  const closeReleaseInfo = useCallback(() => {
    setReleaseOpen(false);
    window.requestAnimationFrame(() => releaseReturnFocusRef.current?.focus());
  }, []);

  const commitContextIds = useCallback((nextProjectId: string, nextConversationId: string) => {
    initialProjectIdRef.current = nextProjectId;
    initialIdRef.current = nextConversationId;
    projectIdRef.current = nextProjectId;
    conversationIdRef.current = nextConversationId;
    conversationPromiseRef.current = null;
    setProjectId(nextProjectId);
    setConversationId(nextConversationId);
    window.sessionStorage.setItem(SESSION_PROJECT_KEY, nextProjectId);
    window.sessionStorage.setItem(SESSION_CONVERSATION_KEY, nextConversationId);
    syncConversationUrl(nextProjectId, nextConversationId);
    setServiceState("connected");
  }, []);

  const activateConversation = useCallback((
    nextProjectId: string,
    nextConversationId: string,
    nextMessages: ChatMessage[] = [],
    nextFiles: WorkspaceFile[] = [],
    options: {
      preserveDraft?: boolean;
      terminationPending?: boolean;
      pendingClarification?: PendingClarification | null;
    } = {},
  ) => {
    commitContextIds(nextProjectId, nextConversationId);
    setMessages(nextMessages);
    setFiles(nextFiles);
    if (!options.preserveDraft) setDraft("");
    failedRequestsRef.current = recoverFailedRequests(nextMessages);
    pendingCancellationRef.current = null;
    setTerminationPending(options.terminationPending === true);
    setPendingClarification(options.pendingClarification ?? null);
    setIsPreparingIntake(false);
    preparingIntakeRef.current = false;
    clarificationSubmittingRef.current = false;
  }, [commitContextIds]);

  const applyConversationTokenUsage = useCallback((id: string, next: TokenUsage) => {
    if (next.conversationId && next.conversationId !== id) return;
    const usage = { ...next, conversationId: id };
    setTokenUsageByConversation((current) => {
      const merged = mergeTokenUsage(current[id], usage);
      return merged === current[id] ? current : { ...current, [id]: merged };
    });
  }, []);

  const refreshConversationTokenUsage = useCallback(async (
    id: string,
    signal?: AbortSignal,
  ) => {
    const usage = await getConversationUsage(id, signal);
    applyConversationTokenUsage(id, usage);
  }, [applyConversationTokenUsage]);

  const refreshCapabilities = useCallback(async () => {
    try {
      const response = await getCapabilities();
      setCapabilities(mapCapabilities(response));
      setServiceState("connected");
    } catch {
      setCapabilities((current) => current.map((item) => ({ ...item, state: "unknown" })));
      setServiceState("unavailable");
    }
  }, []);

  useEffect(() => {
    void refreshCapabilities();
  }, [refreshCapabilities]);

  useEffect(() => {
    const controller = new AbortController();
    getReleaseIdentity(controller.signal)
      .then(setReleaseIdentity)
      .catch(() => setReleaseIdentity(null));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!conversationId) return;
    const controller = new AbortController();
    let requestActive = false;
    const refresh = async () => {
      if (requestActive || controller.signal.aborted) return;
      requestActive = true;
      try {
        await refreshConversationTokenUsage(conversationId, controller.signal);
      } catch (error) {
        // Usage is supplementary UI. A rolling deploy may briefly expose the
        // frontend before the endpoint, so keep chat functionality unaffected.
        if (isAbortError(error)) return;
      } finally {
        requestActive = false;
      }
    };
    void refresh();
    const interval = isSending ? window.setInterval(() => void refresh(), 1_500) : undefined;
    return () => {
      controller.abort();
      if (interval !== undefined) window.clearInterval(interval);
    };
  }, [conversationId, isSending, refreshConversationTokenUsage]);

  const beginDetachedRunRecovery = useCallback((
    nextProjectId: string,
    nextConversationId: string,
  ) => {
    recoveryControllerRef.current?.abort();
    const generation = recoveryGenerationRef.current + 1;
    recoveryGenerationRef.current = generation;
    const controller = new AbortController();
    recoveryControllerRef.current = controller;
    activeRequestRef.current = controller;
    setIsSending(true);
    setServiceState("connected");

    void (async () => {
      let consecutiveFailures = 0;
      let hydratedActiveTurn = false;
      try {
        while (
          !controller.signal.aborted &&
          recoveryGenerationRef.current === generation &&
          conversationIdRef.current === nextConversationId
        ) {
          try {
            const run = await getConversationRun(nextConversationId, controller.signal);
            consecutiveFailures = 0;
            if (run.active) {
              setTerminationPending(run.status === "termination_requested");
              if (hydratedActiveTurn && run.checklist) {
                setMessages((current) => withRunChecklist(current, run));
              }
              if (!hydratedActiveTurn) {
                const [history, savedFiles] = await Promise.all([
                  listMessages(nextConversationId, controller.signal),
                  listFiles(nextConversationId, controller.signal),
                ]);
                const latestRun = await getConversationRun(
                  nextConversationId,
                  controller.signal,
                );
                if (
                  latestRun.active &&
                  recoveryGenerationRef.current === generation &&
                  conversationIdRef.current === nextConversationId
                ) {
                  activateConversation(
                    nextProjectId,
                    nextConversationId,
                    reconcileMessages(withAttachmentNames(history, savedFiles), latestRun),
                    savedFiles,
                    {
                      preserveDraft: true,
                      terminationPending: latestRun.status === "termination_requested",
                    },
                  );
                  hydratedActiveTurn = true;
                } else {
                  continue;
                }
              }
              await abortableDelay(1_500, controller.signal);
              continue;
            }
            const [history, savedFiles] = await Promise.all([
              listMessages(nextConversationId, controller.signal),
              listFiles(nextConversationId, controller.signal),
            ]);
            const latestRun = await getConversationRun(nextConversationId, controller.signal);
            if (
              recoveryGenerationRef.current !== generation ||
              conversationIdRef.current !== nextConversationId
            ) return;
            if (latestRun.active) {
              hydratedActiveTurn = false;
              continue;
            }
            activateConversation(
              nextProjectId,
              nextConversationId,
              reconcileMessages(withAttachmentNames(history, savedFiles), latestRun),
              savedFiles,
              { preserveDraft: true },
            );
            setNotice((current) => (
              current === RECOVERY_RECONNECT_NOTICE ? null : current
            ));
            setServiceState("connected");
            return;
          } catch (error) {
            if (
              isAbortError(error) ||
              controller.signal.aborted ||
              recoveryGenerationRef.current !== generation
            ) return;
            if (isMissingConversation(error)) {
              setNotice("后台对话已不存在，无法继续恢复。请新建对话后重试。");
              setServiceState("unavailable");
              return;
            }
            consecutiveFailures += 1;
            if (consecutiveFailures === 3) {
              setNotice(RECOVERY_RECONNECT_NOTICE);
            }
            await abortableDelay(
              Math.min(2_000 * (2 ** Math.min(consecutiveFailures - 1, 3)), 10_000),
              controller.signal,
            );
          }
        }
      } finally {
        if (recoveryGenerationRef.current === generation) {
          if (activeRequestRef.current === controller) activeRequestRef.current = null;
          if (recoveryControllerRef.current === controller) {
            recoveryControllerRef.current = null;
          }
          cancellationRequestsRef.current.delete(controller);
          setIsSending(false);
        }
      }
    })();
  }, [activateConversation]);

  const reconcileConversation = useCallback(async (
    id: string,
    shouldApply: (
      run: ConversationRunState,
      history: ChatMessage[],
    ) => boolean = () => true,
  ): Promise<{ run: ConversationRunState; history: ChatMessage[] }> => {
    const readPending = async (
      fallback: ClarificationPlan | null,
      allowFallback = true,
    ): Promise<ClarificationPlan | null> => {
      try {
        return await getPendingIntake(id);
      } catch (error) {
        if (errorCode(error) === "INTAKE_PROTOCOL_INVALID") throw error;
        if (allowFallback) return fallback;
        // The second read is the authority.  Reusing a previously observed
        // card after a transient failure can resurrect a sidecar another tab
        // has already consumed, so let the caller retain its current UI and
        // retry instead of applying stale pending state.
        throw error;
      }
    };
    const [context, initialRun, initialPending] = await Promise.all([
      getConversation(id),
      getConversationRun(id),
      readPending(null),
    ]);
    let run = initialRun;
    let history: ChatMessage[] = [];
    let savedFiles: WorkspaceFile[] = [];

    // Read the run marker both before and after messages/files. If the task
    // finishes between those reads, discard the mixed snapshot and read again
    // so a refresh cannot observe a terminal run without its final reply.
    while (true) {
      const [historySnapshot, nextFiles] = await Promise.all([
        listMessages(id),
        listFiles(id),
      ]);
      const latestRun = await getConversationRun(id);
      if (sameRunSnapshot(run, latestRun)) {
        run = latestRun;
        savedFiles = nextFiles;
        history = withAttachmentNames(historySnapshot, nextFiles);
        break;
      }
      run = latestRun;
    }
    // The sidecar can be consumed while the history/run snapshots above are
    // being read.  Re-read it after the stable run marker so a refresh cannot
    // resurrect a question that was already confirmed in another tab.
    const pending = await readPending(initialPending, false);
    if (!shouldApply(run, history)) return { run, history };
    const reconciled = reconcileMessages(history, run);
    const preserveDraft = conversationIdRef.current === context.conversationId;
    activateConversation(
      context.projectId,
      context.conversationId,
      reconciled,
      savedFiles,
      {
        preserveDraft,
        terminationPending: run.status === "termination_requested",
        pendingClarification: pending
          ? { plan: pending, answers: [] }
          : null,
      },
    );
    if (run.active) {
      beginDetachedRunRecovery(context.projectId, context.conversationId);
    }
    return { run, history };
  }, [activateConversation, beginDetachedRunRecovery]);

  useEffect(() => {
    const id = initialIdRef.current;
    if (!id) return;
    let cancelled = false;
    reconcileConversation(id, () => !cancelled)
      .catch((error: unknown) => {
        if (cancelled) return;
        if (isMissingConversation(error)) {
          initialIdRef.current = null;
          initialProjectIdRef.current = null;
          projectIdRef.current = null;
          conversationIdRef.current = null;
          conversationPromiseRef.current = null;
          setProjectId(null);
          setConversationId(null);
          setMessages([]);
          setFiles([]);
          setPendingClarification(null);
          setIsPreparingIntake(false);
          setServiceState("connected");
          window.sessionStorage.removeItem(SESSION_PROJECT_KEY);
          window.sessionStorage.removeItem(SESSION_CONVERSATION_KEY);
          syncConversationUrl(null, null);
          setNotice("未找到这个对话，链接可能已失效。已为你打开新的研究页面。");
        } else {
          setNotice(error instanceof Error ? error.message : "无法读取上次对话。");
        }
      })
      .finally(() => {
        if (!cancelled) setIsHydrating(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reconcileConversation]);

  useEffect(() => () => {
    recoveryGenerationRef.current += 1;
    recoveryControllerRef.current?.abort();
    recoveryControllerRef.current = null;
  }, []);

  useEffect(() => {
    const viewport = scrollRef.current;
    if (!viewport) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [messages, isHydrating, pendingClarification]);

  useEffect(() => {
    if (!panelOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closePanel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closePanel, panelOpen]);

  const ensureConversation = useCallback(async (): Promise<string> => {
    if (conversationIdRef.current) return conversationIdRef.current;
    if (conversationPromiseRef.current) return conversationPromiseRef.current;
    const currentProjectId = projectIdRef.current;
    const creation = currentProjectId
      ? createConversation(currentProjectId)
      : createProject();
    conversationPromiseRef.current = creation
      .then((context) => {
        commitContextIds(context.projectId, context.conversationId);
        return context.conversationId;
      })
      .finally(() => {
        conversationPromiseRef.current = null;
      });
    return conversationPromiseRef.current;
  }, [commitContextIds]);

  const updateAssistantMessage = useCallback(
    (id: string, updater: (message: ChatMessage) => ChatMessage) => {
      setMessages((current) =>
        current.map((message) => (message.id === id ? updater(message) : message)),
      );
    },
    [],
  );

  const streamResponse = useCallback(
    async (assistantId: string, request: FailedRequest) => {
      const controller = new AbortController();
      const clientRequestId = request.clientRequestId || createClientId();
      activeRequestRef.current = controller;
      setIsSending(true);
      setNotice(null);
      failedRequestsRef.current.set(assistantId, request);

      updateAssistantMessage(assistantId, (message) => ({
        ...message,
        content: "",
        status: "streaming",
        progress: INITIAL_RESEARCH_PROGRESS,
        errorMessage: undefined,
      }));

      let id: string | null = null;
      let receivedChecklistForThisRun = false;
      try {
        // Guided confirmation is tied to the conversation whose sidecar was
        // rendered. If navigation/context switching wins the race while the
        // request is being scheduled, abort locally instead of posting the
        // answer into the newly active conversation.
        if (request.conversationId) {
          if (conversationIdRef.current !== request.conversationId) {
            throw new DOMException("conversation changed", "AbortError");
          }
          id = request.conversationId;
        } else {
          id = await ensureConversation();
        }
        if (request.conversationId && conversationIdRef.current !== request.conversationId) {
          throw new DOMException("conversation changed", "AbortError");
        }
        const finalContent = await sendMessage(
          id,
          request.content,
          request.attachmentIds,
          request.retryOf,
          clientRequestId,
          {
            onReplace: (content) => {
              updateAssistantMessage(assistantId, (message) => ({
                ...message,
                content: presentResearchAssistantCopy(content),
              }));
            },
            onProgress: (progress) => {
              updateAssistantMessage(assistantId, (message) => ({
                ...message,
                progress:
                  !message.progress || progress.currentStep >= message.progress.currentStep
                    ? progress
                    : message.progress,
              }));
            },
            onChecklist: (checklist) => {
              const isFirstSnapshot = !receivedChecklistForThisRun;
              receivedChecklistForThisRun = true;
              updateAssistantMessage(assistantId, (message) => isFirstSnapshot
                ? { ...message, checklist }
                : withNewerChecklist(message, checklist));
            },
            onUsage: (usage) => {
              if (id) applyConversationTokenUsage(id, usage);
            },
          },
          controller.signal,
          request.intake,
        );
        const cancellation = cancellationRequestsRef.current.get(controller);
        const wasCancelled = cancellation ? await cancellation.catch(() => false) : false;
        if (wasCancelled) {
          updateAssistantMessage(assistantId, (message) => ({
            ...message,
            status: "stopped",
            progress: undefined,
          }));
          return;
        }
        updateAssistantMessage(assistantId, (message) => ({
          ...message,
          content: presentResearchAssistantCopy(
            message.content || finalContent || "任务已完成，但后端没有返回可显示的文本。",
          ),
          status: "complete",
          progress: undefined,
        }));
        failedRequestsRef.current.delete(assistantId);
        try {
          setFiles(await listFiles(id));
        } catch {
          setNotice("回复已完成，但成果文件列表暂时无法刷新。");
        }
      } catch (error) {
        const cancellation = cancellationRequestsRef.current.get(controller);
        const wasCancelled = cancellation ? await cancellation.catch(() => false) : false;
        const code = errorCode(error);
        const stopped = code === "AGENT_CANCELLED" || (cancellation
          ? wasCancelled
          : error instanceof DOMException && error.name === "AbortError");
        const status = errorStatus(error);
        const retryOf = request.retryOf || errorReplyTo(error);
        const intakeError = Boolean(code && (
          code.startsWith("INTAKE_") ||
          [
            "MISSING_ANSWER",
            "INVALID_ANSWER",
            "INVALID_ANSWERS",
            "INVALID_ACTION",
            "UNKNOWN_QUESTION",
            "UNKNOWN_OPTION",
            "EMPTY_ANSWER",
            "TOO_MANY_OPTIONS",
            "TOO_MANY_ANSWERS",
            "CUSTOM_NOT_ALLOWED",
            "CUSTOM_TOO_LONG",
            "POLICY_REJECTED",
          ].includes(code)
        ));
        if (retryOf) {
          failedRequestsRef.current.set(assistantId, { ...request, retryOf });
        }
        if (
          !stopped &&
          !cancellation &&
          id &&
          status === 409 &&
          code === "TURN_ALREADY_COMPLETED"
        ) {
          try {
            await reconcileConversation(id);
            setNotice("这轮研究已经完成，已同步最终结果。");
            setServiceState("connected");
            return;
          } catch {
            // Fall through and retain the local retry state if reconciliation
            // itself is temporarily unavailable.
          }
        } else if (!stopped && !cancellation && id && status === 409 && [
          "RUN_ACTIVE",
          "RUN_TERMINATING",
          "RUN_CLEANUP_PENDING",
        ].includes(code || "")) {
          try {
            await reconcileConversation(id);
            if (!request.retryOf) setDraft(request.content);
            setNotice(`${publicResearchError(error)} 刚才的输入已保留，未重复发送。`);
            setServiceState("connected");
            return;
          } catch {
            // Fall through and retain the optimistic request if reconciliation
            // itself is temporarily unavailable.
          }
        } else if (
          !stopped &&
          !cancellation &&
          id &&
          request.intake &&
          status === 409 &&
          ["INTAKE_ALREADY_CONSUMED", "INTAKE_ID_MISMATCH"].includes(code || "")
        ) {
          // Another tab may have consumed the sidecar (or replaced it) while
          // this optimistic stream was being posted. Reconcile first so the
          // local placeholder does not remain beside a durable turn/card.
          try {
            await reconcileConversation(id);
            setNotice(
              code === "INTAKE_ID_MISMATCH"
                ? "任务引导已更新，已同步最新问题。"
                : "这次任务引导已由其他请求提交，已同步当前对话。",
            );
            setServiceState("connected");
            return;
          } catch {
            // Fall through and retain the local error if the authoritative
            // snapshot is temporarily unavailable.
          }
        } else if (
          !stopped &&
          !cancellation &&
          id &&
          (status === undefined || (request.intake && status >= 500))
        ) {
          let accepted = false;
          try {
            await reconcileConversation(id, (run, history) => {
              accepted = request.intake
                ? guidedRequestWasPersisted(
                  request,
                  run,
                  history,
                  clientRequestId,
                )
                : requestWasPersisted(
                  request,
                  run,
                  history,
                  clientRequestId,
                );
              return accepted;
            });
            if (accepted) {
              setServiceState("connected");
              return;
            }
          } catch {
            // Fall through to the safe local error projection when the
            // authoritative run snapshot is temporarily unavailable.
          }
        }
        const shouldCheckPendingIntake = Boolean(request.intake) || intakeError;
        if (!stopped && !cancellation && shouldCheckPendingIntake && id) {
          // An answer can become stale after a refresh or a second browser
          // tab submits it.  Re-read the sidecar so the user can correct the
          // choices instead of being left with a dead optimistic turn.
          const pending = await getPendingIntake(id).catch(() => null);
          if (pending) {
            if (request.intake) {
              // The guided request has not become a durable user turn when
              // its sidecar is still awaiting input. Remove the temporary
              // user/assistant pair so a stale tab does not leave a visible
              // failed duplicate next to the restored decision card.
              setMessages((current) => {
                const optimisticAssistant = current.find((message) => message.id === assistantId);
                const optimisticUserId = optimisticAssistant?.replyTo;
                return current.filter((message) => (
                  message.id !== assistantId &&
                  (!optimisticUserId || message.id !== optimisticUserId)
                ));
              });
              failedRequestsRef.current.delete(assistantId);
            }
            setPendingClarification({
              plan: pending,
              answers: pending.id === request.intake?.id ? request.intake?.answers || [] : [],
            });
            setDraft(request.content);
            setNotice(
              code === "POLICY_REJECTED"
                ? "自定义条件触发了安全边界，请修改补充内容后再开始。"
                : request.intake && status === undefined
                  ? "网络暂时中断，已保留这次任务引导；请确认后重试。"
                  : "这组选择已过期，请重新确认后再开始。",
            );
          } else if (intakeError) {
            setDraft(request.content);
            setNotice(
              code === "POLICY_REJECTED"
                ? "自定义条件触发了安全边界，请修改补充内容后再开始。"
                : "这次任务引导已失效，请重新发送原始任务。",
            );
          }
        }
        if (!stopped && !cancellation && status !== undefined && !request.retryOf) {
          setDraft(request.content);
        }
        updateAssistantMessage(assistantId, (message) => ({
          ...message,
          status: stopped ? "stopped" : "error",
          replyTo: retryOf || message.replyTo,
          progress: undefined,
          errorMessage: cancellation && !wasCancelled
            ? "终止请求仍在处理中，请稍后再次确认。"
            : publicResearchError(error),
        }));
        if (!stopped && !cancellation) {
          setServiceState(status === undefined ? "unavailable" : "connected");
        }
      } finally {
        if (request.intake) clarificationSubmittingRef.current = false;
        cancellationRequestsRef.current.delete(controller);
        if (activeRequestRef.current === controller) {
          activeRequestRef.current = null;
          setIsSending(false);
        }
      }
    },
    [
      applyConversationTokenUsage,
      ensureConversation,
      reconcileConversation,
      updateAssistantMessage,
    ],
  );

  const startOptimisticRun = useCallback((request: FailedRequest) => {
    const now = new Date().toISOString();
    const userId = createClientId();
    const assistantId = createClientId();
    const attachments = request.attachmentIds.map((id) => {
      const file = files.find((item) => item.id === id);
      return { id, name: file?.name || "历史附件" };
    });
    setMessages((current) => [
      ...current,
      {
        id: userId,
        role: "user",
        content: request.content,
        createdAt: now,
        status: "complete",
        attachments,
        attachmentIds: request.attachmentIds,
      },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        createdAt: now,
        status: "streaming",
        replyTo: userId,
        progress: INITIAL_RESEARCH_PROGRESS,
      },
    ]);
    void streamResponse(assistantId, request);
  }, [files, streamResponse]);

  const handleSend = useCallback(async () => {
    const content = draft.trim();
    if (
      !content ||
      isSending ||
      preparingIntakeRef.current ||
      isPreparingIntake ||
      pendingClarification ||
      isStopping ||
      isContextChanging ||
      terminationPending
    ) return;
    const attachmentIds = readyFiles.map((file) => file.id);
    const prepareRequestId = createClientId();
    preparingIntakeRef.current = true;
    setIsPreparingIntake(true);
    setNotice("正在识别任务类型，准备关键问题…");
    let preparedConversationId: string | null = null;
    try {
      const id = await ensureConversation();
      preparedConversationId = id;
      let prepared;
      try {
        prepared = await prepareIntake(id, content, attachmentIds, prepareRequestId);
      } catch (error) {
        // Older rolling releases do not expose intake yet. Keep the original
        // send path available while the deployment converges.
        if (errorStatus(error) !== 404) throw error;
        prepared = { required: false };
      }
      // A context switch can be initiated by browser navigation or another
      // window while the local preflight is in flight.  Never project an old
      // plan into the newly active conversation.
      if (conversationIdRef.current !== id) return;
      if (prepared.required && prepared.plan) {
        setPendingClarification({ plan: prepared.plan, answers: [] });
        setDraft("");
        setNotice(null);
        return;
      }
      setDraft("");
      startOptimisticRun({
        content,
        attachmentIds,
        clientRequestId: prepareRequestId,
        conversationId: id,
      });
    } catch (error) {
      // Another tab may have reserved the conversation's intake slot while
      // this preflight was in flight.  Reconcile the authoritative card so a
      // user never has to retype the task or receives only a generic 409.
      if (
        errorCode(error) === "INTAKE_ALREADY_PENDING" &&
        preparedConversationId &&
        conversationIdRef.current === preparedConversationId
      ) {
        const pending = await getPendingIntake(preparedConversationId).catch(() => null);
        if (pending) {
          setPendingClarification({ plan: pending, answers: [] });
          setDraft("");
          setNotice("当前对话已有待确认的任务引导，请先完成或取消它。");
          return;
        }
      }
      setDraft(content);
      setNotice(error instanceof Error ? error.message : "暂时无法开始任务引导。请稍后重试。");
      setServiceState(errorStatus(error) && errorStatus(error)! >= 500 ? "unavailable" : "connected");
    } finally {
      preparingIntakeRef.current = false;
      setIsPreparingIntake(false);
    }
  }, [
    draft,
    ensureConversation,
    isContextChanging,
    isPreparingIntake,
    isSending,
    isStopping,
    pendingClarification,
    readyFiles,
    startOptimisticRun,
    terminationPending,
  ]);

  const handleClarificationSubmit = useCallback((answers: ClarificationAnswer[]) => {
    const pending = pendingClarification;
    if (!pending || isSending || isPreparingIntake || clarificationSubmittingRef.current) return;
    clarificationSubmittingRef.current = true;
    setPendingClarification({ ...pending, answers, submitting: true });
    startOptimisticRun({
      content: pending.plan.originalContent,
      attachmentIds: pending.plan.attachmentIds,
      intake: {
        id: pending.plan.id,
        action: "confirm",
        answers,
      },
      clientRequestId: createClientId(),
      conversationId: conversationIdRef.current || undefined,
    });
    setPendingClarification(null);
  }, [isPreparingIntake, isSending, pendingClarification, startOptimisticRun]);

  const handleClarificationSkip = useCallback(() => {
    const pending = pendingClarification;
    if (!pending || isSending || isPreparingIntake || clarificationSubmittingRef.current) return;
    clarificationSubmittingRef.current = true;
    setPendingClarification({ ...pending, submitting: true });
    startOptimisticRun({
      content: pending.plan.originalContent,
      attachmentIds: pending.plan.attachmentIds,
      intake: {
        id: pending.plan.id,
        action: "skip",
        answers: [],
      },
      clientRequestId: createClientId(),
      conversationId: conversationIdRef.current || undefined,
    });
    setPendingClarification(null);
  }, [isPreparingIntake, isSending, pendingClarification, startOptimisticRun]);

  const handleRetry = useCallback(
    (messageId: string) => {
      if (isSending || isPreparingIntake || pendingClarification || isStopping || terminationPending) return;
      const request = failedRequestsRef.current.get(messageId);
      if (request) {
        void streamResponse(messageId, {
          ...request,
          // A retry is a new transport attempt. Keep the original intake
          // choices/content, but use a fresh correlation id so recovery cannot
          // confuse this run with the failed request that produced the card.
          clientRequestId: createClientId(),
          conversationId: conversationIdRef.current || request.conversationId,
        });
      }
    },
    [isPreparingIntake, isSending, isStopping, pendingClarification, streamResponse, terminationPending],
  );

  const handleFilesSelected = useCallback(
    async (selectedFiles: File[]) => {
      if (!selectedFiles.length) return;
      if (isContextChanging || isPreparingIntake || pendingClarification) {
        setNotice("请先完成当前任务引导，再添加或替换资料。");
        return;
      }
      setNotice(null);
      const pending = selectedFiles.map((file) => ({
        localId: createClientId(),
        file,
      }));
      setFiles((current) => [
        ...pending.map(({ localId, file }) => ({
          id: localId,
          name: file.name,
          size: file.size,
          contentType: file.type || "application/octet-stream",
          status: "uploading" as const,
        })),
        ...current,
      ]);

      try {
        const id = await ensureConversation();
        await Promise.all(
          pending.map(async ({ localId, file }) => {
            try {
              const uploaded = await uploadFile(id, file);
              setFiles((current) =>
                current.map((item) => (item.id === localId ? uploaded : item)),
              );
            } catch (error) {
              setFiles((current) =>
                current.map((item) =>
                  item.id === localId
                    ? {
                        ...item,
                        status: "error",
                        errorMessage:
                          error instanceof Error ? error.message.trim() : "上传失败",
                      }
                    : item,
                ),
              );
            }
          }),
        );
      } catch (error) {
        const message = error instanceof Error ? error.message.trim() : "无法创建对话。";
        setFiles((current) =>
          current.map((item) =>
            pending.some(({ localId }) => localId === item.id)
              ? { ...item, status: "error", errorMessage: message }
              : item,
          ),
        );
        setServiceState("unavailable");
      }
    },
    [ensureConversation, isContextChanging, isPreparingIntake, pendingClarification],
  );

  const stopActiveResponse = useCallback(async (showError = true): Promise<boolean> => {
    const pendingAtStart = pendingCancellationRef.current;
    const controller = activeRequestRef.current || pendingAtStart?.controller;
    if (!controller) return true;
    if (isStopping) return false;
    const id = conversationIdRef.current || pendingAtStart?.conversationId || null;
    setIsStopping(true);
    let terminationWasRequested = Boolean(pendingAtStart);
    let clientAbortedForIdleRace = false;
    const cancellation = id
      ? (async () => {
          let result = await cancelConversation(id);
          if (result.status === "cancelled" && result.cancelled) return true;
          if (result.status === "idle" && !pendingAtStart) {
            clientAbortedForIdleRace = true;
            controller.abort();
            await new Promise((resolve) => window.setTimeout(resolve, 120));
            result = await cancelConversation(id);
          }
          if (result.status === "cancelled" && result.cancelled) return true;
          if (result.status === "idle") return true;
          terminationWasRequested =
            terminationWasRequested ||
            result.status === "termination_requested" ||
            result.requested === true;
          if (!terminationWasRequested) return false;

          const deadline = Date.now() + 15_000;
          while (Date.now() < deadline) {
            await new Promise((resolve) => window.setTimeout(resolve, 500));
            result = await cancelConversation(id);
            if (result.status === "cancelled" && result.cancelled) return true;
            if (result.status === "idle") return true;
          }
          return false;
        })()
      : Promise.resolve(true);
    cancellationRequestsRef.current.set(controller, cancellation);
    try {
      const cancelled = await cancellation;
      if (cancelled) {
        pendingCancellationRef.current = null;
        setTerminationPending(false);
        controller.abort();
        if (id) {
          try {
            await reconcileConversation(id);
          } catch (error) {
            if (showError) {
              setNotice(
                error instanceof Error
                  ? error.message
                  : "任务已停止，但历史状态暂时无法刷新。",
              );
            }
          }
        }
      } else if (id && terminationWasRequested) {
        pendingCancellationRef.current = { controller, conversationId: id };
        setTerminationPending(true);
      }
      if (!cancelled && showError) setNotice("研究进程仍在终止，请稍后再次确认。");
      return cancelled;
    } catch (error) {
      if (id && (terminationWasRequested || clientAbortedForIdleRace)) {
        pendingCancellationRef.current = { controller, conversationId: id };
        setTerminationPending(true);
      } else {
        cancellationRequestsRef.current.delete(controller);
      }
      if (showError) {
        setNotice(error instanceof Error ? error.message : "暂时无法停止本轮研究。");
      }
      return false;
    } finally {
      setIsStopping(false);
    }
  }, [isStopping, reconcileConversation]);

  const discardPendingClarification = useCallback(async (): Promise<boolean> => {
    const pending = pendingClarification;
    const id = conversationIdRef.current;
    if (!pending) return true;
    if (!id) {
      setPendingClarification(null);
      return true;
    }
    try {
      await cancelPendingIntake(id, pending.plan.id);
      // Navigation can complete while DELETE is in flight. Never clear the
      // newly active conversation's card from a stale cancellation response.
      if (conversationIdRef.current !== id) return true;
      setPendingClarification(null);
      return true;
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "无法取消待确认的任务引导。");
      return false;
    }
  }, [pendingClarification]);

  const handleClarificationCancel = useCallback(() => {
    const pending = pendingClarification;
    const id = conversationIdRef.current;
    if (!pending || !id || isSending || isPreparingIntake || clarificationSubmittingRef.current) return;
    clarificationSubmittingRef.current = true;
    setPendingClarification({ ...pending, submitting: true });
    void (async () => {
      try {
        await cancelPendingIntake(id, pending.plan.id);
        if (conversationIdRef.current !== id) return;
        setPendingClarification(null);
        setDraft(pending.plan.originalContent);
        setNotice("已取消本次任务引导；你可以修改原始任务后重新发送。");
      } catch (error) {
        if (conversationIdRef.current === id) {
          const current = await getPendingIntake(id).catch(() => null);
          if (current) {
            setPendingClarification({
              plan: current,
              answers: current.id === pending.plan.id ? pending.answers : [],
            });
          } else {
            setPendingClarification(null);
          }
          setNotice(error instanceof Error ? error.message : "无法取消本次任务引导。");
        }
      } finally {
        clarificationSubmittingRef.current = false;
      }
    })();
  }, [isPreparingIntake, isSending, pendingClarification]);

  const handleSelectConversation = useCallback(async (
    _selectedProjectId: string,
    id: string,
  ): Promise<boolean> => {
    if (id === conversationIdRef.current) {
      setIsHydrating(true);
      try {
        await reconcileConversation(id);
        return true;
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "暂时无法刷新当前对话。");
        return false;
      } finally {
        setIsHydrating(false);
      }
    }
    if (isUploading) {
      setNotice("文件仍在上传，请等待上传完成后再切换项目或对话。");
      return false;
    }
    if (isPreparingIntake) {
      setNotice("正在生成关键问题，请稍后再切换对话。");
      return false;
    }
    const hasPendingWork = Boolean(
      activeRequestRef.current ||
      pendingCancellationRef.current ||
      pendingClarification ||
      draft.trim(),
    );
    if (
      hasPendingWork &&
      !window.confirm("切换历史对话会终止当前回复并清空未发送内容。是否继续？")
    ) {
      return false;
    }
    if (
      (activeRequestRef.current || pendingCancellationRef.current) &&
      !(await stopActiveResponse())
    ) {
      return false;
    }
    if (!(await discardPendingClarification())) return false;

    setIsHydrating(true);
    setNotice(null);
    try {
      await reconcileConversation(id);
      return true;
    } catch (error) {
      const message = isMissingConversation(error)
        ? "这个历史对话已不存在。"
        : error instanceof Error
          ? error.message
          : "无法打开历史对话。";
      setNotice(message);
      throw error;
    } finally {
      setIsHydrating(false);
    }
  }, [discardPendingClarification, draft, isPreparingIntake, isUploading, pendingClarification, reconcileConversation, stopActiveResponse]);

  const handleNewProject = useCallback(async () => {
    if (isContextChanging || isHydrating || isStopping || isPreparingIntake) return;
    if (isUploading) {
      setNotice("文件仍在上传，请等待上传完成后再新建项目。");
      return;
    }
    const hasCurrentWork = messages.length > 0 || files.length > 0 || Boolean(draft.trim()) || Boolean(pendingClarification);
    if (
      hasCurrentWork &&
      !window.confirm("新建项目会离开当前项目；原项目及其中的对话仍会保留在历史中。是否继续？")
    ) return;
    if (
      (activeRequestRef.current || pendingCancellationRef.current) &&
      !(await stopActiveResponse())
    ) return;
    if (!(await discardPendingClarification())) return;

    setIsContextChanging(true);
    setNotice(null);
    try {
      const context = await createProject();
      activateConversation(context.projectId, context.conversationId);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "无法新建项目。");
    } finally {
      setIsContextChanging(false);
    }
  }, [activateConversation, discardPendingClarification, draft, files.length, isContextChanging, isHydrating, isPreparingIntake, isStopping, isUploading, messages.length, pendingClarification, stopActiveResponse]);

  const handleNewConversation = useCallback(async () => {
    if (isContextChanging || isHydrating || isStopping || isPreparingIntake) return;
    const currentProjectId = projectIdRef.current;
    if (!currentProjectId) {
      setNotice("请先新建项目；第一条消息也会自动建立一个项目。");
      return;
    }
    if (isUploading) {
      setNotice("文件仍在上传，请等待上传完成后再新建对话。");
      return;
    }
    const hasCurrentWork = messages.length > 0 || files.length > 0 || Boolean(draft.trim()) || Boolean(pendingClarification);
    if (
      hasCurrentWork &&
      !window.confirm("将在当前项目中新建空白对话；当前对话仍会保留。是否继续？")
    ) return;
    if (
      (activeRequestRef.current || pendingCancellationRef.current) &&
      !(await stopActiveResponse())
    ) return;
    if (!(await discardPendingClarification())) return;

    setIsContextChanging(true);
    setNotice(null);
    try {
      const context = await createConversation(currentProjectId);
      activateConversation(context.projectId, context.conversationId);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "无法在当前项目中新建对话。");
    } finally {
      setIsContextChanging(false);
    }
  }, [activateConversation, discardPendingClarification, draft, files.length, isContextChanging, isHydrating, isPreparingIntake, isStopping, isUploading, messages.length, pendingClarification, stopActiveResponse]);

  const connectionLabel =
    serviceState === "connected"
      ? "服务已连接"
      : serviceState === "unavailable"
        ? "等待后端连接"
        : "正在检查服务";

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-lockup">
          <button
            className="brand-mark"
            type="button"
            onClick={(event) => openReleaseInfo(event.currentTarget)}
            aria-label="查看版本与开源信息"
            aria-controls="release-dialog"
            aria-expanded={releaseOpen}
            title="版本与开源信息"
          >
            <Buildings size={22} weight="regular" aria-hidden="true" />
            <span className="brand-mark-version" aria-hidden="true">
              V{APP_VERSION}
            </span>
          </button>
          <span className="brand-copy">
            <strong>{APP_TITLE}</strong>
            <small className="brand-meta">
              <span className="brand-context">项目对话</span>
              <button
                className="version-chip"
                type="button"
                onClick={(event) => openReleaseInfo(event.currentTarget)}
                aria-controls="release-dialog"
                aria-expanded={releaseOpen}
              >
                V{APP_VERSION}
              </button>
              <a
                className="brand-github-link"
                href={GITHUB_REPOSITORY_URL}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="在 GitHub 打开项目源码"
                title="GitHub 源码"
              >
                <GithubLogo size={13} weight="regular" aria-hidden="true" />
                <span>GitHub</span>
              </a>
            </small>
          </span>
        </div>

        <div className={`service-state ${serviceState}`} aria-label={connectionLabel}>
          {serviceState === "connected" ? (
            <CloudCheck size={18} weight="regular" aria-hidden="true" />
          ) : serviceState === "unavailable" ? (
            <CloudSlash size={18} weight="regular" aria-hidden="true" />
          ) : (
            <Cloud size={18} weight="regular" aria-hidden="true" />
          )}
          <span>{connectionLabel}</span>
        </div>

        <div className="header-actions">
          <button
            ref={panelTriggerRef}
            className="header-button mobile-panel-button"
            type="button"
            onClick={() => setPanelOpen(true)}
            aria-label="打开本次工作"
            aria-controls="workspace-panel"
            aria-expanded={panelOpen}
            title="本次工作"
          >
            <Files size={18} weight="regular" aria-hidden="true" />
            <span>本次工作</span>
          </button>
          <a
            className="header-button return-home-button"
            href={HOOSLAND_HOME_URL}
            aria-label="返回 Hoosland 首页"
            title="返回 Hoosland"
          >
            <ArrowLeft size={18} weight="regular" aria-hidden="true" />
            <span>返回 Hoosland</span>
          </a>
          <button
            ref={historyTriggerRef}
            className="header-button"
            type="button"
            onClick={() => setHistoryOpen(true)}
            aria-label="打开历史对话"
            aria-controls="history-dialog"
            aria-expanded={historyOpen}
            aria-haspopup="dialog"
            title="历史对话"
          >
            <ClockCounterClockwise size={18} weight="regular" aria-hidden="true" />
            <span>历史对话</span>
          </button>
          <button
            ref={settingsTriggerRef}
            className="header-button"
            type="button"
            onClick={() => setSettingsOpen(true)}
            aria-label="打开 API 与输出配置"
            aria-controls="settings-dialog"
            aria-expanded={settingsOpen}
            aria-haspopup="dialog"
            title="配置后台"
          >
            <GearSix size={18} weight="regular" aria-hidden="true" />
            <span>配置</span>
          </button>
          <button
            className="header-button new-project-button"
            type="button"
            onClick={() => void handleNewProject()}
            aria-label="新建独立项目"
            title="新建项目"
            disabled={isContextChanging || isHydrating || isPreparingIntake || isStopping || terminationPending || isUploading}
          >
            <FolderPlus size={18} weight="regular" aria-hidden="true" />
            <span>{isContextChanging ? "正在新建" : "新建项目"}</span>
          </button>
          <button
            className="header-button new-conversation-button"
            type="button"
            onClick={() => void handleNewConversation()}
            aria-label="在当前项目中新建对话"
            title={projectId ? "在当前项目中新建对话" : "请先新建项目"}
            disabled={!projectId || isContextChanging || isHydrating || isPreparingIntake || isStopping || terminationPending || isUploading}
          >
            <Plus size={18} weight="regular" aria-hidden="true" />
            <span>新建对话</span>
          </button>
        </div>
      </header>

      <div className="workspace-layout">
        <main className="conversation-area">
          {notice ? (
            <div className="notice-banner" role="alert">
              <WarningCircle size={18} weight="regular" aria-hidden="true" />
              <span>{notice}</span>
              <button type="button" onClick={() => setNotice(null)} aria-label="关闭提示">
                <X size={17} weight="regular" aria-hidden="true" />
              </button>
            </div>
          ) : null}

          <MessageList
            conversationId={conversationId}
            files={files}
            messages={messages}
            isHydrating={isHydrating}
            scrollRef={scrollRef}
            onPromptSelect={setDraft}
            onRetry={handleRetry}
            pendingClarification={pendingClarification}
            onClarificationSubmit={handleClarificationSubmit}
            onClarificationSkip={handleClarificationSkip}
            onClarificationCancel={handleClarificationCancel}
          />
          <Composer
            value={draft}
            tokenUsage={tokenUsage}
            attachedFileCount={readyFiles.length}
            isSending={isSending}
            isStopping={isStopping}
            terminationPending={terminationPending}
            isUploading={isUploading}
            disabled={
              isHydrating ||
              isContextChanging ||
              isPreparingIntake ||
              Boolean(pendingClarification)
            }
            onChange={setDraft}
            onSend={handleSend}
            onStop={() => void stopActiveResponse()}
            onFilesSelected={(selected) => void handleFilesSelected(selected)}
          />
        </main>

        <WorkspacePanel
          open={panelOpen}
          conversationId={conversationId}
          capabilities={capabilities}
          files={files}
          isUploading={isUploading}
          onClose={closePanel}
          onFilesSelected={(selected) => void handleFilesSelected(selected)}
          getDownloadUrl={(file) =>
            conversationId ? fileDownloadUrl(conversationId, file) : "#"
          }
          getOpenUrl={(file) =>
            conversationId ? fileOpenUrl(conversationId, file) : "#"
          }
        />
      </div>

      {panelOpen ? (
        <button
          className="panel-overlay"
          type="button"
          aria-label="关闭工作资料"
          onClick={closePanel}
        />
      ) : null}

      {settingsOpen ? (
        <SettingsPanel
          onClose={closeSettings}
          onSaved={() => void refreshCapabilities()}
        />
      ) : null}

      {releaseOpen ? (
        <ReleaseInfoDialog identity={releaseIdentity} onClose={closeReleaseInfo} />
      ) : null}

      {historyOpen ? (
        <HistoryPanel
          currentProjectId={projectId}
          currentConversationId={conversationId}
          onClose={closeHistory}
          onSelect={handleSelectConversation}
        />
      ) : null}
    </div>
  );
}
