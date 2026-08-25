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
}

export interface AssistantProgress {
  stage: string;
  label: string;
  currentStep: number;
  totalSteps: number;
  remainingSteps: number;
  etaLabel: string;
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
