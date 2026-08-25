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
  listFiles,
  listMessages,
  presentResearchAssistantCopy,
  sendMessage,
  uploadFile,
  type ApiCapability,
  type CapabilityResponse,
  type ConversationRunState,
} from "./api";
import { Composer } from "./components/Composer";
import { HistoryPanel } from "./components/HistoryPanel";
import { MessageList } from "./components/MessageList";
import { SettingsPanel } from "./components/SettingsPanel";
import { WorkspacePanel } from "./components/WorkspacePanel";
import { createClientId } from "./clientId";
import { APP_TITLE, STORAGE_NAMESPACE } from "./deployment";
import type {
  AssistantProgress,
  CapabilityState,
  CapabilityView,
  ChatMessage,
  WorkspaceFile,
} from "./types";

const SESSION_CONVERSATION_KEY = `${STORAGE_NAMESPACE}:conversation`;
const SESSION_PROJECT_KEY = `${STORAGE_NAMESPACE}:project`;
const HOOSLAND_HOME_URL = "http://hoosland.com/";
const RECOVERY_RECONNECT_NOTICE = "后台任务仍在运行，页面正在重新连接；无需重复发送。";

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

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
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
    left.completedAt === right.completedAt
  );
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
  const successfulReplies = new Set(
    history
      .filter((message) => message.role === "assistant" && message.status === "complete")
      .map((message) => message.replyTo)
      .filter((value): value is string => Boolean(value)),
  );
  const activeUserId = run.active ? run.userMessageId : undefined;
  const latestTerminalReplies = new Map<string, string>();
  for (const message of history) {
    if (
      message.role === "assistant" &&
      (message.status === "error" || message.status === "stopped") &&
      message.replyTo
    ) latestTerminalReplies.set(message.replyTo, message.id);
  }
  const cleaned = history.filter((message) => !(
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
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilityView[]>(createInitialCapabilities);
  const [serviceState, setServiceState] = useState<ServiceState>("checking");
  const [draft, setDraft] = useState("");
  const [isHydrating, setIsHydrating] = useState(Boolean(initialIdRef.current));
  const [isSending, setIsSending] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [terminationPending, setTerminationPending] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isContextChanging, setIsContextChanging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const panelTriggerRef = useRef<HTMLButtonElement>(null);
  const historyTriggerRef = useRef<HTMLButtonElement>(null);
  const settingsTriggerRef = useRef<HTMLButtonElement>(null);
  const activeRequestRef = useRef<AbortController | null>(null);
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
    options: { preserveDraft?: boolean; terminationPending?: boolean } = {},
  ) => {
    commitContextIds(nextProjectId, nextConversationId);
    setMessages(nextMessages);
    setFiles(nextFiles);
    if (!options.preserveDraft) setDraft("");
    failedRequestsRef.current = recoverFailedRequests(nextMessages);
    pendingCancellationRef.current = null;
    setTerminationPending(options.terminationPending === true);
  }, [commitContextIds]);

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
    const [context, initialRun] = await Promise.all([
      getConversation(id),
      getConversationRun(id),
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
  }, [messages, isHydrating]);

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
      const clientRequestId = createClientId();
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
      try {
        id = await ensureConversation();
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
          },
          controller.signal,
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
        const stopped = cancellation
          ? wasCancelled
          : error instanceof DOMException && error.name === "AbortError";
        const status = errorStatus(error);
        const code = errorCode(error);
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
        } else if (!stopped && !cancellation && id && status === undefined) {
          let accepted = false;
          try {
            await reconcileConversation(id, (run, history) => {
              accepted = requestWasPersisted(
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
        if (!stopped && !cancellation && status !== undefined && !request.retryOf) {
          setDraft(request.content);
        }
        updateAssistantMessage(assistantId, (message) => ({
          ...message,
          status: stopped ? "stopped" : "error",
          progress: undefined,
          errorMessage: cancellation && !wasCancelled
            ? "终止请求仍在处理中，请稍后再次确认。"
            : publicResearchError(error),
        }));
        if (!stopped && !cancellation) {
          setServiceState(status === undefined ? "unavailable" : "connected");
        }
      } finally {
        cancellationRequestsRef.current.delete(controller);
        if (activeRequestRef.current === controller) {
          activeRequestRef.current = null;
          setIsSending(false);
        }
      }
    },
    [ensureConversation, reconcileConversation, updateAssistantMessage],
  );

  const handleSend = useCallback(() => {
    const content = draft.trim();
    if (!content || isSending || isStopping || isContextChanging || terminationPending) return;
    const now = new Date().toISOString();
    const userId = createClientId();
    const assistantId = createClientId();
    const attachments = readyFiles.map((file) => ({ id: file.id, name: file.name }));
    const request = { content, attachmentIds: readyFiles.map((file) => file.id) };

    setMessages((current) => [
      ...current,
      {
        id: userId,
        role: "user",
        content,
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
    setDraft("");
    void streamResponse(assistantId, request);
  }, [draft, isContextChanging, isSending, isStopping, readyFiles, streamResponse, terminationPending]);

  const handleRetry = useCallback(
    (messageId: string) => {
      if (isSending || isStopping || terminationPending) return;
      const request = failedRequestsRef.current.get(messageId);
      if (request) void streamResponse(messageId, request);
    },
    [isSending, isStopping, streamResponse, terminationPending],
  );

  const handleFilesSelected = useCallback(
    async (selectedFiles: File[]) => {
      if (!selectedFiles.length || isContextChanging) return;
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
    [ensureConversation, isContextChanging],
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
    const hasPendingWork = Boolean(
      activeRequestRef.current || pendingCancellationRef.current || draft.trim(),
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
  }, [draft, isUploading, reconcileConversation, stopActiveResponse]);

  const handleNewProject = useCallback(async () => {
    if (isContextChanging || isHydrating || isStopping) return;
    if (isUploading) {
      setNotice("文件仍在上传，请等待上传完成后再新建项目。");
      return;
    }
    const hasCurrentWork = messages.length > 0 || files.length > 0 || Boolean(draft.trim());
    if (
      hasCurrentWork &&
      !window.confirm("新建项目会离开当前项目；原项目及其中的对话仍会保留在历史中。是否继续？")
    ) return;
    if (
      (activeRequestRef.current || pendingCancellationRef.current) &&
      !(await stopActiveResponse())
    ) return;

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
  }, [activateConversation, draft, files.length, isContextChanging, isHydrating, isStopping, isUploading, messages.length, stopActiveResponse]);

  const handleNewConversation = useCallback(async () => {
    if (isContextChanging || isHydrating || isStopping) return;
    const currentProjectId = projectIdRef.current;
    if (!currentProjectId) {
      setNotice("请先新建项目；第一条消息也会自动建立一个项目。");
      return;
    }
    if (isUploading) {
      setNotice("文件仍在上传，请等待上传完成后再新建对话。");
      return;
    }
    const hasCurrentWork = messages.length > 0 || files.length > 0 || Boolean(draft.trim());
    if (
      hasCurrentWork &&
      !window.confirm("将在当前项目中新建空白对话；当前对话仍会保留。是否继续？")
    ) return;
    if (
      (activeRequestRef.current || pendingCancellationRef.current) &&
      !(await stopActiveResponse())
    ) return;

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
  }, [activateConversation, draft, files.length, isContextChanging, isHydrating, isStopping, isUploading, messages.length, stopActiveResponse]);

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
          <span className="brand-mark" aria-hidden="true">
            <Buildings size={22} weight="regular" />
          </span>
          <span className="brand-copy">
            <strong>{APP_TITLE}</strong>
            <small>项目对话</small>
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
            disabled={isContextChanging || isHydrating || isStopping || terminationPending || isUploading}
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
            disabled={!projectId || isContextChanging || isHydrating || isStopping || terminationPending || isUploading}
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
            messages={messages}
            isHydrating={isHydrating}
            scrollRef={scrollRef}
            onPromptSelect={setDraft}
            onRetry={handleRetry}
          />
          <Composer
            value={draft}
            attachedFileCount={readyFiles.length}
            isSending={isSending}
            isStopping={isStopping}
            terminationPending={terminationPending}
            isUploading={isUploading}
            disabled={isHydrating || isContextChanging}
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
