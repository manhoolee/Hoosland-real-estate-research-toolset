export type MessageRole = "user" | "assistant";
export type MessageStatus = "complete" | "streaming" | "error" | "stopped";

export interface ChatAttachment {
  id: string;
  name: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  createdAt: string;
  status: MessageStatus;
  attachments?: ChatAttachment[];
  attachmentIds?: string[];
  replyTo?: string;
  errorMessage?: string;
  retryable?: boolean;
  progress?: AssistantProgress;
  checklist?: RunChecklist;
}

export interface AssistantProgress {
  stage: string;
  label: string;
  currentStep: number;
  totalSteps: number;
  remainingSteps: number;
  etaLabel: string;
}

export type ChecklistPhase =
  | "planning"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

export type ChecklistItemStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "incomplete";

export interface ChecklistItem {
  id: string;
  text: string;
  status: ChecklistItemStatus;
  detail?: string;
}

export interface RunChecklist {
  version: 1;
  revision: number;
  phase: ChecklistPhase;
  updated_at?: string;
  tasks: ChecklistItem[];
  deliverables: ChecklistItem[];
}

export interface TokenUsage {
  conversationId?: string;
  uncachedInputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  reasoningTokens?: number;
  totalTokens: number;
  updatedAt?: string;
}

export type FileStatus = "uploading" | "ready" | "error";

export interface WorkspaceFile {
  id: string;
  name: string;
  size: number;
  contentType: string;
  createdAt?: string;
  downloadUrl?: string;
  openUrl?: string;
  kind?: "input" | "output" | string;
  status: FileStatus;
  errorMessage?: string;
}

export type CapabilityState = "checking" | "available" | "unavailable" | "unknown";

export interface CapabilityView {
  id: string;
  label: string;
  description: string;
  state: CapabilityState;
}
