import type { AssistantProgress, ChatMessage, WorkspaceFile } from "./types";
import { createClientId } from "./clientId";
import { API_BASE_URL } from "./deployment";

interface ApiConversation {
  id?: string;
  conversation_id?: string;
  project_id?: string;
  conversation?: { id?: string; project_id?: string };
  data?: { id?: string; project_id?: string };
}

interface ApiConversationSummary {
  id?: string;
  conversation_id?: string;
  project_id?: string;
  title?: string;
  preview?: string;
  created_at?: string;
  updated_at?: string;
  message_count?: number;
}

export interface ConversationSummary {
  id: string;
  projectId: string;
  title: string;
  preview?: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
}

interface ApiProjectSummary {
  id?: string;
  project_id?: string;
  title?: string;
  preview?: string;
  created_at?: string;
  updated_at?: string;
  conversation_count?: number;
  message_count?: number;
  conversations?: ApiConversationSummary[];
}

export interface ProjectSummary {
  id: string;
  title: string;
  preview?: string;
  createdAt: string;
  updatedAt: string;
  conversationCount: number;
  messageCount: number;
  conversations: ConversationSummary[];
}

export interface ConversationContext {
  projectId: string;
  conversationId: string;
}

interface ApiMessage {
  id?: string;
  role?: string;
  content?: string;
  created_at?: string;
  createdAt?: string;
  status?: string;
  attachment_ids?: string[];
  reply_to?: string;
  error_message?: string;
  retryable?: boolean;
}

export interface ConversationRunState {
  status: "idle" | "running" | "termination_requested" | "succeeded" | "failed" | "cancelled" | "interrupted";
  active: boolean;
  retryable: boolean;
  clientRequestId?: string;
  userMessageId?: string;
  startedAt?: string;
  updatedAt?: string;
  completedAt?: string;
}

interface ApiFile {
  id?: string;
  file_id?: string;
  name?: string;
  filename?: string;
  size?: number;
  content_type?: string;
  type?: string;
  created_at?: string;
  download_url?: string;
  open_url?: string;
  url?: string;
  kind?: string;
}

export interface ProviderApiConfig {
  base_url: string;
  model: string;
  api_key_set: boolean;
}

export interface CapabilityApiConfig extends ProviderApiConfig {
  endpoint: string;
  auth_header: string;
  auth_prefix: string;
}

export interface AdminConfig {
  main_agent: ProviderApiConfig;
  native_search: ProviderApiConfig;
  capabilities: Record<string, CapabilityApiConfig>;
  output: {
    directory_name: string;
    policy: string;
    default_formats: string[];
  };
}

export interface ApiCapability {
  id?: string;
  key?: string;
  name?: string;
  label?: string;
  description?: string;
  status?: string;
  state?: string;
  available?: boolean;
  enabled?: boolean;
  configured?: boolean;
}

export interface CapabilityResponse {
  items?: ApiCapability[];
  capabilities?: ApiCapability[] | Record<string, boolean | string>;
  mcp?: Record<string, unknown>;
}

export interface StreamCallbacks {
  onReplace: (content: string) => void;
  onProgress: (progress: AssistantProgress) => void;
}

const PUBLIC_PROGRESS_STAGES: Record<string, AssistantProgress> = {
  brief: {
    stage: "brief",
    label: "正在确认研究目标与交付要求",
    currentStep: 1,
    totalSteps: 4,
    remainingSteps: 4,
    etaLabel: "复杂任务通常还需 5–12 分钟",
  },
  evidence: {
    stage: "evidence",
    label: "正在研读与核查项目资料",
    currentStep: 2,
    totalSteps: 4,
    remainingSteps: 3,
    etaLabel: "复杂任务通常还需 3–10 分钟",
  },
  analysis: {
    stage: "analysis",
    label: "正在归纳结论与关键判断",
    currentStep: 3,
    totalSteps: 4,
    remainingSteps: 2,
    etaLabel: "复杂任务通常还需 2–6 分钟",
  },
  delivery: {
    stage: "delivery",
    label: "正在整理可交付成果",
    currentStep: 4,
    totalSteps: 4,
    remainingSteps: 1,
    etaLabel: "通常还需 1–5 分钟",
  },
};

function publicProgress(stage: string): AssistantProgress {
  return PUBLIC_PROGRESS_STAGES[stage] || PUBLIC_PROGRESS_STAGES.brief;
}

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export function presentResearchAssistantCopy(value: string): string {
  const cleaned = value.trim();
  if (/run is already active for this conversation/i.test(cleaned)) {
    return "上一轮研究仍在运行，请先停止后再继续。";
  }
  const legacyRuntimeName = ["har", "ness"].join("");
  return value
    .replace(new RegExp(`deepseek[\\s_-]*${legacyRuntimeName}`, "gi"), "研究助手")
    .replace(new RegExp(`\\b${legacyRuntimeName}\\b`, "gi"), "研究助手");
}

function createRequestError(response: Response, fallback: string, code?: string): Error {
  const error = new Error(fallback);
  Object.assign(error, {
    status: response.status,
    code,
    requestId: response.headers.get("x-request-id") || undefined,
  });
  return error;
}

async function parseError(response: Response, fallback: string): Promise<Error> {
  try {
    const payload = (await response.json()) as {
      message?: string;
      detail?: string | { code?: string; message?: string };
      error?: string | { code?: string; message?: string };
    };
    const detail = typeof payload.detail === "object" ? payload.detail : undefined;
    const structuredError = typeof payload.error === "object" ? payload.error : undefined;
    const message =
      payload.message ||
      (typeof payload.detail === "string" ? payload.detail : detail?.message) ||
      (typeof payload.error === "string" ? payload.error : structuredError?.message);
    return createRequestError(
      response,
      presentResearchAssistantCopy(message || fallback),
      structuredError?.code || detail?.code,
    );
  } catch {
    return createRequestError(response, fallback);
  }
}

function isStatus(error: unknown, status: number): boolean {
  return error instanceof Error && (error as Error & { status?: number }).status === status;
}

function normaliseFile(file: ApiFile, fallback?: File): WorkspaceFile {
  return {
    id: file.id || file.file_id || createClientId(),
    name: file.name || file.filename || fallback?.name || "未命名文件",
    size: file.size ?? fallback?.size ?? 0,
    contentType: file.content_type || file.type || fallback?.type || "application/octet-stream",
    createdAt: file.created_at,
    downloadUrl: file.download_url || file.url,
    openUrl: file.open_url,
    kind: file.kind,
    status: "ready",
  };
}

function readFileItems(payload: unknown, fallback?: File): WorkspaceFile[] {
  if (!payload || typeof payload !== "object") return [];
  const source = payload as {
    items?: ApiFile[];
    files?: ApiFile[];
    file?: ApiFile;
    data?: ApiFile | ApiFile[];
  };
  const items = source.items || source.files;
  if (Array.isArray(items)) return items.map((item) => normaliseFile(item, fallback));
  if (source.file) return [normaliseFile(source.file, fallback)];
  if (Array.isArray(source.data)) return source.data.map((item) => normaliseFile(item, fallback));
  if (source.data && typeof source.data === "object") return [normaliseFile(source.data, fallback)];
  return [normaliseFile(source as ApiFile, fallback)];
}

export function resolveApiAssetUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/")) return apiUrl(`/${path}`);
  return apiUrl(path);
}

function readConversationContext(payload: ApiConversation, fallbackProjectId?: string): ConversationContext {
  const conversationId =
    payload.conversation?.id || payload.id || payload.conversation_id || payload.data?.id;
  const projectId =
    payload.conversation?.project_id || payload.project_id || payload.data?.project_id || fallbackProjectId;
  if (!conversationId) throw new Error("后端未返回对话编号。");
  if (!projectId) throw new Error("后端未返回项目编号。");
  return { projectId, conversationId };
}

export async function createProject(signal?: AbortSignal): Promise<ConversationContext> {
  const response = await fetch(apiUrl("/api/projects"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) throw await parseError(response, "无法创建项目，请检查后端服务。");
  const payload = (await response.json()) as ApiConversation;
  return readConversationContext(payload, payload.id || payload.project_id);
}

export async function createConversation(
  projectId: string,
  signal?: AbortSignal,
): Promise<ConversationContext> {
  const response = await fetch(apiUrl(`/api/projects/${projectId}/conversations`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) throw await parseError(response, "无法在当前项目中新建对话。");
  return readConversationContext((await response.json()) as ApiConversation, projectId);
}

export async function getConversation(
  conversationId: string,
  signal?: AbortSignal,
): Promise<ConversationContext> {
  const response = await fetch(apiUrl(`/api/conversations/${conversationId}`), {
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) throw await parseError(response, "无法读取对话所属项目。");
  return readConversationContext((await response.json()) as ApiConversation, conversationId);
}

function normaliseConversationSummary(
  item: ApiConversationSummary,
  fallbackProjectId?: string,
): ConversationSummary | null {
  const id = item.id || item.conversation_id;
  if (!id) return null;
  const createdAt = item.created_at || item.updated_at || new Date(0).toISOString();
  const updatedAt = item.updated_at || createdAt;
  return {
    id,
    projectId: item.project_id || fallbackProjectId || id,
    title: item.title?.trim() || "未命名对话",
    preview: item.preview?.trim() || undefined,
    createdAt,
    updatedAt,
    messageCount: Number.isFinite(item.message_count) ? Number(item.message_count) : 0,
  };
}

export async function listConversations(signal?: AbortSignal): Promise<ConversationSummary[]> {
  const response = await fetch(apiUrl("/api/admin/conversations"), {
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) throw await parseError(response, "无法读取历史对话。");
  const payload = (await response.json()) as {
    items?: ApiConversationSummary[];
    conversations?: ApiConversationSummary[];
  };
  const items = payload.items || payload.conversations || [];
  return items.flatMap((item) => {
    const summary = normaliseConversationSummary(item);
    return summary ? [summary] : [];
  });
}

export async function listProjects(signal?: AbortSignal): Promise<ProjectSummary[]> {
  const response = await fetch(apiUrl("/api/admin/projects"), {
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) throw await parseError(response, "无法读取历史项目。");
  const payload = (await response.json()) as {
    items?: ApiProjectSummary[];
    projects?: ApiProjectSummary[];
  };
  const items = payload.items || payload.projects || [];
  return items.flatMap((item) => {
    const id = item.id || item.project_id;
    if (!id) return [];
    const conversations = (item.conversations || []).flatMap((conversation) => {
      const summary = normaliseConversationSummary(conversation, id);
      return summary ? [summary] : [];
    });
    const createdAt = item.created_at || conversations.at(-1)?.createdAt || new Date(0).toISOString();
    const updatedAt = item.updated_at || conversations[0]?.updatedAt || createdAt;
    return [{
      id,
      title: item.title?.trim() || "未命名项目",
      preview: item.preview?.trim() || undefined,
      createdAt,
      updatedAt,
      conversationCount: Number.isFinite(item.conversation_count)
        ? Number(item.conversation_count)
        : conversations.length,
      messageCount: Number.isFinite(item.message_count)
        ? Number(item.message_count)
        : conversations.reduce((total, conversation) => total + conversation.messageCount, 0),
      conversations,
    }];
  });
}

export async function listMessages(
  conversationId: string,
  signal?: AbortSignal,
): Promise<ChatMessage[]> {
  const response = await fetch(apiUrl(`/api/conversations/${conversationId}/messages`), {
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) throw await parseError(response, "无法读取历史消息。");
  const payload = (await response.json()) as { items?: ApiMessage[]; messages?: ApiMessage[] };
  const items = payload.items || payload.messages || [];
  return items
    .filter((item) => item.role === "user" || item.role === "assistant")
    .map((item) => {
      const role = item.role as "user" | "assistant";
      const storedStatus = String(item.status || "complete").toLowerCase();
      const status = role === "user"
        ? "complete"
        : storedStatus === "error" || storedStatus === "failed"
          ? "error"
          : storedStatus === "stopped" || storedStatus === "cancelled"
            ? "stopped"
            : storedStatus === "streaming" || storedStatus === "running"
              ? "streaming"
              : "complete";
      return {
        id: item.id || createClientId(),
        role,
        content: item.content || "",
        createdAt: item.created_at || item.createdAt || new Date().toISOString(),
        status,
        attachmentIds: Array.isArray(item.attachment_ids) ? item.attachment_ids : [],
        replyTo: item.reply_to,
        errorMessage: item.error_message,
        retryable: item.retryable,
      } satisfies ChatMessage;
    });
}

export async function getConversationRun(
  conversationId: string,
  signal?: AbortSignal,
): Promise<ConversationRunState> {
  const response = await fetch(apiUrl(`/api/conversations/${conversationId}/run`), {
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw await parseError(response, "无法读取后台任务状态。");
  const payload = (await response.json()) as {
    status?: ConversationRunState["status"];
    active?: boolean;
    retryable?: boolean;
    client_request_id?: string;
    user_message_id?: string;
    started_at?: string;
    updated_at?: string;
    completed_at?: string;
  };
  return {
    status: payload.status || "idle",
    active: payload.active === true,
    retryable: payload.retryable === true,
    clientRequestId: payload.client_request_id,
    userMessageId: payload.user_message_id,
    startedAt: payload.started_at,
    updatedAt: payload.updated_at,
    completedAt: payload.completed_at,
  };
}

function extractStreamValue(payload: unknown): {
  kind: "delta" | "replace" | "progress" | "error" | "none";
  value: string;
  progress?: AssistantProgress;
} {
  if (typeof payload === "string") return { kind: "delta", value: payload };
  if (!payload || typeof payload !== "object") return { kind: "none", value: "" };

  const data = payload as Record<string, unknown>;
  const type = String(data.type || data.event || "").toLowerCase();
  if (type === "error") {
    return {
      kind: "error",
      value: presentResearchAssistantCopy(String(data.message || data.error || "生成失败。")),
    };
  }
  if (type === "progress") {
    const progress = publicProgress(String(data.stage || "brief"));
    return {
      kind: "progress",
      value: "",
      progress,
    };
  }
  // Collapse events from an older backend into a single project-facing
  // milestone. Never expose tool, skill, command or runtime names here.
  if (type === "status" || type === "skill" || type === "activity") {
    const progress = publicProgress(type === "status" ? "brief" : "evidence");
    return {
      kind: "progress",
      value: "",
      progress,
    };
  }
  if (typeof data.delta === "string") return { kind: "delta", value: data.delta };
  if (data.delta && typeof data.delta === "object") {
    const delta = data.delta as Record<string, unknown>;
    const value = delta.content || delta.text;
    if (typeof value === "string") return { kind: "delta", value };
  }

  const choices = data.choices;
  if (Array.isArray(choices) && choices[0] && typeof choices[0] === "object") {
    const choice = choices[0] as Record<string, unknown>;
    const delta = choice.delta as Record<string, unknown> | undefined;
    if (typeof delta?.content === "string") return { kind: "delta", value: delta.content };
  }

  if (data.message && typeof data.message === "object") {
    const message = data.message as Record<string, unknown>;
    if (typeof message.content === "string") return { kind: "replace", value: message.content };
  }
  if (typeof data.content === "string") return { kind: "replace", value: data.content };
  if (typeof data.text === "string") return { kind: "replace", value: data.text };
  return { kind: "none", value: "" };
}

function applyStreamPayload(
  payload: unknown,
  callbacks: StreamCallbacks,
  state: { content: string },
): void {
  const event = extractStreamValue(payload);
  if (event.kind === "error") {
    const data = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
    const error = new Error(event.value);
    Object.assign(error, {
      code: typeof data.code === "string" ? data.code : undefined,
      replyTo: typeof data.reply_to === "string" ? data.reply_to : undefined,
    });
    throw error;
  }
  if (event.kind === "progress" && event.progress) {
    callbacks.onProgress(event.progress);
    return;
  }
  if (event.kind === "delta") {
    state.content += event.value;
    return;
  }
  if (event.kind === "replace") {
    state.content = event.value;
    callbacks.onReplace(event.value);
  }
}

async function readEventStream(response: Response, callbacks: StreamCallbacks): Promise<string> {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const state = { content: "" };
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";

    for (const frame of frames) {
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (!data || data === "[DONE]" || data.toLowerCase() === "done") continue;
      try {
        applyStreamPayload(JSON.parse(data), callbacks, state);
      } catch (error) {
        if (error instanceof SyntaxError) {
          applyStreamPayload(data, callbacks, state);
        } else {
          throw error;
        }
      }
    }
    if (done) break;
  }

  const trailingData = buffer
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (
    trailingData &&
    trailingData !== "[DONE]" &&
    trailingData.toLowerCase() !== "done"
  ) {
    try {
      applyStreamPayload(JSON.parse(trailingData), callbacks, state);
    } catch (error) {
      if (error instanceof SyntaxError) applyStreamPayload(trailingData, callbacks, state);
      else throw error;
    }
  }
  return state.content;
}

async function readNdjsonStream(response: Response, callbacks: StreamCallbacks): Promise<string> {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const state = { content: "" };
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed === "[DONE]" || trimmed.toLowerCase() === "done") continue;
      applyStreamPayload(JSON.parse(trimmed), callbacks, state);
    }
    if (done) break;
  }
  if (
    buffer.trim() &&
    buffer.trim() !== "[DONE]" &&
    buffer.trim().toLowerCase() !== "done"
  ) {
    applyStreamPayload(JSON.parse(buffer), callbacks, state);
  }
  return state.content;
}

export async function sendMessage(
  conversationId: string,
  content: string,
  attachmentIds: string[],
  retryOf: string | undefined,
  clientRequestId: string,
  callbacks: StreamCallbacks,
  signal: AbortSignal,
): Promise<string> {
  const response = await fetch(apiUrl(`/api/conversations/${conversationId}/messages`), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream, application/x-ndjson, application/json, text/plain",
    },
    body: JSON.stringify({
      content,
      ...(attachmentIds.length ? { attachment_ids: attachmentIds } : {}),
      ...(retryOf ? { retry_of: retryOf } : {}),
      client_request_id: clientRequestId,
    }),
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) throw await parseError(response, "消息发送失败，请稍后重试。");

  const contentType = response.headers.get("content-type")?.toLowerCase() || "";
  if (contentType.includes("text/event-stream")) return readEventStream(response, callbacks);
  if (contentType.includes("ndjson")) return readNdjsonStream(response, callbacks);
  if (contentType.includes("application/json")) {
    const state = { content: "" };
    applyStreamPayload(await response.json(), callbacks, state);
    return state.content;
  }

  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let result = "";
  while (true) {
    const { done, value } = await reader.read();
    const chunk = decoder.decode(value || new Uint8Array(), { stream: !done });
    if (chunk) {
      result += chunk;
    }
    if (done) break;
  }
  return result;
}

export interface CancelConversationResult {
  cancelled: boolean;
  requested?: boolean;
  status: string;
  message?: string;
}

export async function cancelConversation(conversationId: string): Promise<CancelConversationResult> {
  const response = await fetch(apiUrl(`/api/conversations/${conversationId}/cancel`), {
    method: "POST",
    credentials: "same-origin",
  });
  if (response.status === 404) return { cancelled: false, status: "idle" };
  if (!response.ok) {
    throw await parseError(response, "暂时无法停止本轮研究。请稍后再试。");
  }
  return (await response.json()) as CancelConversationResult;
}

async function postFile(path: string, file: File, conversationId?: string): Promise<WorkspaceFile> {
  const formData = new FormData();
  formData.append("files", file);
  if (conversationId) formData.append("conversation_id", conversationId);
  const response = await fetch(apiUrl(path), {
    method: "POST",
    body: formData,
    credentials: "same-origin",
  });
  if (!response.ok) throw await parseError(response, `无法上传 ${file.name}。`);
  const items = readFileItems(await response.json(), file);
  if (!items[0]) throw new Error(`后端未返回 ${file.name} 的文件信息。`);
  return items[0];
}

export async function uploadFile(conversationId: string, file: File): Promise<WorkspaceFile> {
  try {
    return await postFile(`/api/conversations/${conversationId}/files`, file, conversationId);
  } catch (error) {
    if (!isStatus(error, 404)) throw error;
    return postFile("/api/files", file, conversationId);
  }
}

export async function listFiles(
  conversationId: string,
  signal?: AbortSignal,
): Promise<WorkspaceFile[]> {
  try {
    const response = await fetch(apiUrl(`/api/conversations/${conversationId}/files`), {
      credentials: "same-origin",
      signal,
    });
    if (!response.ok) throw await parseError(response, "无法读取文件列表。");
    return readFileItems(await response.json());
  } catch (error) {
    if (!isStatus(error, 404)) throw error;
    const response = await fetch(apiUrl(`/api/files?conversation_id=${encodeURIComponent(conversationId)}`), {
      credentials: "same-origin",
      signal,
    });
    if (!response.ok) throw await parseError(response, "无法读取文件列表。");
    return readFileItems(await response.json());
  }
}

export async function getCapabilities(): Promise<CapabilityResponse> {
  const response = await fetch(apiUrl("/api/capabilities"), { credentials: "same-origin" });
  if (!response.ok) throw await parseError(response, "无法读取能力状态。");
  return (await response.json()) as CapabilityResponse;
}

export function fileDownloadUrl(conversationId: string, file: WorkspaceFile): string {
  if (file.downloadUrl) return resolveApiAssetUrl(file.downloadUrl);
  return apiUrl(`/api/conversations/${conversationId}/files/${file.id}`);
}

export function fileOpenUrl(conversationId: string, file: WorkspaceFile): string {
  if (file.openUrl) return resolveApiAssetUrl(file.openUrl);
  return apiUrl(`/api/conversations/${conversationId}/files/${file.id}/open`);
}

export async function adminLogin(password: string): Promise<void> {
  const response = await fetch(apiUrl("/api/admin/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
    credentials: "same-origin",
  });
  if (!response.ok) throw await parseError(response, "管理员密码不正确。");
}

export async function adminLogout(): Promise<void> {
  const response = await fetch(apiUrl("/api/admin/logout"), {
    method: "POST",
    credentials: "same-origin",
  });
  if (!response.ok) throw await parseError(response, "退出管理后台失败。");
}

export async function getAdminConfig(): Promise<AdminConfig> {
  const response = await fetch(apiUrl("/api/admin/config"), {
    credentials: "same-origin",
  });
  if (!response.ok) throw await parseError(response, "无法读取 API 配置。");
  const payload = (await response.json()) as AdminConfig | { config?: AdminConfig };
  const config = (payload as { config?: AdminConfig }).config || (payload as AdminConfig);
  if (!config) throw new Error("后端未返回 API 配置。");
  return config;
}

export async function saveAdminConfig(config: Record<string, unknown>): Promise<AdminConfig> {
  const response = await fetch(apiUrl("/api/admin/config"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
    credentials: "same-origin",
  });
  if (!response.ok) throw await parseError(response, "无法保存 API 配置。");
  const payload = (await response.json()) as AdminConfig | { config?: AdminConfig };
  const saved = (payload as { config?: AdminConfig }).config || (payload as AdminConfig);
  if (!saved) throw new Error("后端未返回已保存的配置。");
  return saved;
}
