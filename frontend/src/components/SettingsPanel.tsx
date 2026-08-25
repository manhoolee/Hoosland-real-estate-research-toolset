import {
  Brain,
  CaretDown,
  CheckCircle,
  FileText,
  FloppyDisk,
  FolderSimple,
  Globe,
  ImageSquare,
  Key,
  LockKey,
  SignOut,
  UsersThree,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  adminLogin,
  adminLogout,
  getAdminConfig,
  saveAdminConfig,
  type AdminConfig,
  type CapabilityApiConfig,
  type ProviderApiConfig,
} from "../api";

type SettingsTab = "models" | "capabilities" | "output";

const SETTINGS_FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

interface SettingsPanelProps {
  onClose: () => void;
  onSaved: () => void;
}

interface SecretDraft {
  value: string;
  clear: boolean;
}

const capabilityDefinitions = [
  {
    id: "vision_analyze",
    label: "视觉理解",
    description: "户型图、扫描件与项目截图识别",
    icon: <ImageSquare size={20} weight="regular" />,
  },
  {
    id: "image_generate",
    label: "图像生成",
    description: "报告配图、概念图与图像编辑",
    icon: <ImageSquare size={20} weight="regular" />,
  },
  {
    id: "web_search",
    label: "扩展联网检索",
    description: "接入独立搜索或信息检索服务",
    icon: <Globe size={20} weight="regular" />,
  },
  {
    id: "document_extract",
    label: "文档解析",
    description: "PDF 与办公文档的结构化提取",
    icon: <FileText size={20} weight="regular" />,
  },
  {
    id: "delegate_text",
    label: "专业子助手",
    description: "复杂任务中的专业模型委派调用",
    icon: <UsersThree size={20} weight="regular" />,
  },
] as const;

const emptyProvider: ProviderApiConfig = {
  base_url: "",
  model: "",
  api_key_set: false,
};

const emptyCapability: CapabilityApiConfig = {
  ...emptyProvider,
  endpoint: "",
  auth_header: "Authorization",
  auth_prefix: "Bearer ",
};

function isUnauthorized(error: unknown): boolean {
  return error instanceof Error && (error as Error & { status?: number }).status === 401;
}

function cloneConfig(config: AdminConfig): AdminConfig {
  return JSON.parse(JSON.stringify(config)) as AdminConfig;
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function normaliseProvider(value: Partial<ProviderApiConfig> | undefined): ProviderApiConfig {
  return {
    base_url: textValue(value?.base_url),
    model: textValue(value?.model),
    api_key_set: value?.api_key_set === true,
  };
}

function normaliseCapability(
  value: Partial<CapabilityApiConfig> | undefined,
): CapabilityApiConfig {
  return {
    base_url: textValue(value?.base_url),
    endpoint: textValue(value?.endpoint),
    model: textValue(value?.model),
    auth_header: textValue(value?.auth_header) || "Authorization",
    auth_prefix: textValue(value?.auth_prefix),
    api_key_set: value?.api_key_set === true,
  };
}

function normaliseConfig(config: AdminConfig): AdminConfig {
  const capabilities: Record<string, CapabilityApiConfig> = {};
  for (const definition of capabilityDefinitions) {
    capabilities[definition.id] = normaliseCapability(config.capabilities?.[definition.id]);
  }
  for (const [key, value] of Object.entries(config.capabilities || {})) {
    if (!capabilities[key]) capabilities[key] = normaliseCapability(value);
  }
  return {
    main_agent: normaliseProvider(config.main_agent),
    native_search: normaliseProvider(config.native_search),
    capabilities,
    output: {
      directory_name: config.output?.directory_name || "outputs",
      policy: config.output?.policy || "conversation_isolated",
      default_formats: Array.isArray(config.output?.default_formats)
        ? config.output.default_formats
        : ["md", "html"],
    },
  };
}

function Field({
  label,
  value,
  placeholder,
  helper,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  helper?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
      />
      {helper ? <small>{helper}</small> : null}
    </label>
  );
}

function SecretField({
  configured,
  draft,
  onChange,
}: {
  configured: boolean;
  draft: SecretDraft;
  onChange: (draft: SecretDraft) => void;
}) {
  return (
    <div className="settings-field secret-field">
      <div className="secret-label-row">
        <span>API 密钥</span>
        <span className={`secret-state ${configured && !draft.clear ? "configured" : ""}`}>
          {configured && !draft.clear ? (
            <CheckCircle size={15} weight="regular" aria-hidden="true" />
          ) : (
            <Key size={15} weight="regular" aria-hidden="true" />
          )}
          {configured && !draft.clear ? "已配置" : "未配置"}
        </span>
      </div>
      <input
        type="password"
        value={draft.value}
        placeholder={configured && !draft.clear ? "留空将保留当前密钥" : "输入新的 API 密钥"}
        autoComplete="new-password"
        disabled={draft.clear}
        aria-label="API 密钥"
        onChange={(event) => onChange({ value: event.target.value, clear: false })}
      />
      <label className="clear-secret-control">
        <input
          type="checkbox"
          checked={draft.clear}
          onChange={(event) => onChange({ value: "", clear: event.target.checked })}
        />
        清除已保存的密钥
      </label>
    </div>
  );
}

function ProviderSection({
  title,
  description,
  icon,
  provider,
  secret,
  onProviderChange,
  onSecretChange,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  provider: ProviderApiConfig;
  secret: SecretDraft;
  onProviderChange: (provider: ProviderApiConfig) => void;
  onSecretChange: (draft: SecretDraft) => void;
}) {
  return (
    <section className="settings-group">
      <div className="settings-group-heading">
        <span aria-hidden="true">{icon}</span>
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
      </div>
      <div className="settings-fields two-column-fields">
        <Field
          label="API 基础地址"
          value={provider.base_url}
          placeholder="https://api.example.com/v1"
          onChange={(base_url) => onProviderChange({ ...provider, base_url })}
        />
        <Field
          label="模型名称"
          value={provider.model}
          placeholder="填写服务端模型标识"
          onChange={(model) => onProviderChange({ ...provider, model })}
        />
        <SecretField configured={provider.api_key_set} draft={secret} onChange={onSecretChange} />
      </div>
    </section>
  );
}

function capabilityPayload(
  config: CapabilityApiConfig,
  secret: SecretDraft,
): Record<string, unknown> {
  return {
    base_url: config.base_url,
    endpoint: config.endpoint,
    model: config.model,
    auth_header: config.auth_header,
    auth_prefix: config.auth_prefix,
    ...(secret.clear ? { api_key: null } : secret.value ? { api_key: secret.value } : {}),
  };
}

function providerPayload(config: ProviderApiConfig, secret: SecretDraft): Record<string, unknown> {
  return {
    base_url: config.base_url,
    model: config.model,
    ...(secret.clear ? { api_key: null } : secret.value ? { api_key: secret.value } : {}),
  };
}

export function SettingsPanel({ onClose, onSaved }: SettingsPanelProps) {
  const [config, setConfig] = useState<AdminConfig | null>(null);
  const [secrets, setSecrets] = useState<Record<string, SecretDraft>>({});
  const [password, setPassword] = useState("");
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loggingIn, setLoggingIn] = useState(false);
  const [activeTab, setActiveTab] = useState<SettingsTab>("models");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const loginInputRef = useRef<HTMLInputElement>(null);
  const firstTabRef = useRef<HTMLButtonElement>(null);

  const secretFor = (key: string): SecretDraft => secrets[key] || { value: "", clear: false };
  const setSecret = (key: string, draft: SecretDraft) => {
    setSecrets((current) => ({ ...current, [key]: draft }));
    setSuccess(null);
  };
  const updateCapability = (key: string, value: CapabilityApiConfig) => {
    setConfig((current) => current ? {
      ...current,
      capabilities: { ...current.capabilities, [key]: value },
    } : current);
    setSuccess(null);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(SETTINGS_FOCUSABLE_SELECTOR),
      ).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      const activeIsFocusable = active instanceof HTMLElement && focusable.includes(active);
      if (event.shiftKey && (active === first || !activeIsFocusable)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !activeIsFocusable)) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, saving]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (loading) return;
    const frame = window.requestAnimationFrame(() => {
      if (authenticated === false) loginInputRef.current?.focus();
      else if (authenticated === true) firstTabRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [authenticated, loading]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAdminConfig()
      .then((value) => {
        if (cancelled) return;
        setConfig(normaliseConfig(value));
        setAuthenticated(true);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (isUnauthorized(caught)) {
          setAuthenticated(false);
        } else {
          setError(caught instanceof Error ? caught.message : "无法连接配置服务。");
          setAuthenticated(false);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const capabilityItems = useMemo(
    () => capabilityDefinitions.map((definition) => ({ ...definition, config: config?.capabilities[definition.id] })),
    [config],
  );

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault();
    if (!password || loggingIn) return;
    setLoggingIn(true);
    setError(null);
    try {
      await adminLogin(password);
      const value = normaliseConfig(await getAdminConfig());
      setConfig(value);
      setAuthenticated(true);
      setPassword("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "登录失败，请稍后再试。");
    } finally {
      setLoggingIn(false);
    }
  };

  const handleLogout = async () => {
    setError(null);
    try {
      await adminLogout();
      setConfig(null);
      setAuthenticated(false);
      setSecrets({});
      setSuccess(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "退出失败，请稍后再试。");
    }
  };

  const handleSave = async () => {
    if (!config || saving) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    const capabilities = Object.fromEntries(
      Object.entries(config.capabilities).map(([key, value]) => [
        key,
        capabilityPayload(value, secretFor(`capabilities.${key}`)),
      ]),
    );
    const payload = {
      main_agent: providerPayload(config.main_agent, secretFor("main_agent")),
      native_search: providerPayload(config.native_search, secretFor("native_search")),
      capabilities,
      output: {
        directory_name: config.output.directory_name,
        policy: config.output.policy,
        default_formats: config.output.default_formats,
      },
    };
    try {
      const saved = normaliseConfig(await saveAdminConfig(payload));
      setConfig(cloneConfig(saved));
      setSecrets({});
      setSuccess("配置已保存。新的研究任务会使用最新设置。");
      onSaved();
    } catch (caught) {
      if (isUnauthorized(caught)) {
        setAuthenticated(false);
        setConfig(null);
        setError("管理登录已过期，请重新登录。");
      } else {
        setError(caught instanceof Error ? caught.message : "保存失败，请稍后再试。");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !saving) onClose();
    }}>
      <section
        id="settings-dialog"
        ref={dialogRef}
        className="settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        tabIndex={-1}
      >
        <header className="settings-header">
          <div>
            <h2 id="settings-title">API 与输出配置</h2>
            <p>密钥仅保存在后端，浏览器不会读取已保存的明文。</p>
          </div>
          <button
            ref={closeButtonRef}
            className="settings-close"
            type="button"
            onClick={onClose}
            aria-label="关闭配置"
            disabled={saving}
          >
            <X size={20} weight="regular" aria-hidden="true" />
          </button>
        </header>

        {loading ? (
          <div className="settings-loading" role="status" aria-label="正在读取配置">
            <span />
            <span />
            <span />
          </div>
        ) : authenticated === false ? (
          <div className="settings-login-wrap">
            <form className="settings-login" onSubmit={(event) => void handleLogin(event)}>
              <span className="settings-login-icon" aria-hidden="true">
                <LockKey size={24} weight="regular" />
              </span>
              <h3>管理员登录</h3>
              <p>登录后可配置主模型、专业能力接口和统一输出策略。</p>
              <label className="settings-field">
                <span>管理员密码</span>
                <input
                  ref={loginInputRef}
                  type="password"
                  value={password}
                  autoComplete="current-password"
                  placeholder="输入管理员密码"
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>
              {error ? (
                <div className="settings-feedback error" role="alert">
                  <WarningCircle size={17} weight="regular" aria-hidden="true" />
                  <span>{error}</span>
                </div>
              ) : null}
              <button className="settings-primary-button" type="submit" disabled={!password || loggingIn}>
                <LockKey size={17} weight="regular" aria-hidden="true" />
                {loggingIn ? "正在验证" : "登录配置后台"}
              </button>
            </form>
          </div>
        ) : config ? (
          <>
            <div className="settings-workspace">
              <nav className="settings-tabs" aria-label="配置分类">
                <button ref={firstTabRef} type="button" className={activeTab === "models" ? "active" : ""} onClick={() => setActiveTab("models")}>
                  <Brain size={18} weight="regular" aria-hidden="true" />
                  模型与检索
                </button>
                <button type="button" className={activeTab === "capabilities" ? "active" : ""} onClick={() => setActiveTab("capabilities")}>
                  <UsersThree size={18} weight="regular" aria-hidden="true" />
                  专业能力
                </button>
                <button type="button" className={activeTab === "output" ? "active" : ""} onClick={() => setActiveTab("output")}>
                  <FolderSimple size={18} weight="regular" aria-hidden="true" />
                  输出管理
                </button>
              </nav>

              <div className="settings-content">
                {activeTab === "models" ? (
                  <div className="settings-pane">
                    <div className="settings-pane-heading">
                      <h3>模型与联网检索</h3>
                      <p>设置研究对话使用的主模型，以及内置联网检索模型。</p>
                    </div>
                    <ProviderSection
                      title="研究助手主模型"
                      description="负责对话编排、资料分析和专业模块协调。"
                      icon={<Brain size={20} weight="regular" />}
                      provider={config.main_agent}
                      secret={secretFor("main_agent")}
                      onSecretChange={(value) => setSecret("main_agent", value)}
                      onProviderChange={(main_agent) => {
                        setConfig({ ...config, main_agent });
                        setSuccess(null);
                      }}
                    />
                    <ProviderSection
                      title="内置联网检索"
                      description="用于公开信息查找、交叉核验和来源追踪。"
                      icon={<Globe size={20} weight="regular" />}
                      provider={config.native_search}
                      secret={secretFor("native_search")}
                      onSecretChange={(value) => setSecret("native_search", value)}
                      onProviderChange={(native_search) => {
                        setConfig({ ...config, native_search });
                        setSuccess(null);
                      }}
                    />
                  </div>
                ) : null}

                {activeTab === "capabilities" ? (
                  <div className="settings-pane">
                    <div className="settings-pane-heading">
                      <h3>专业能力接口</h3>
                      <p>各能力可接入独立的兼容 API。未配置的能力不会被对话调用。</p>
                    </div>
                    <div className="capability-config-list">
                      {capabilityItems.map((item) => {
                        const provider = item.config || { ...emptyCapability };
                        const secretKey = `capabilities.${item.id}`;
                        return (
                          <details className="capability-config" key={item.id}>
                            <summary>
                              <span className="capability-config-icon" aria-hidden="true">{item.icon}</span>
                              <span>
                                <strong>{item.label}</strong>
                                <small>{item.description}</small>
                              </span>
                              <span className={`secret-state ${provider.api_key_set ? "configured" : ""}`}>
                                {provider.api_key_set ? "密钥已配置" : "密钥未配置"}
                              </span>
                              <CaretDown className="summary-caret" size={17} weight="regular" aria-hidden="true" />
                            </summary>
                            <div className="capability-config-fields">
                              <Field
                                label="API 基础地址"
                                value={provider.base_url}
                                placeholder="https://api.example.com"
                                onChange={(base_url) => updateCapability(item.id, { ...provider, base_url })}
                              />
                              <Field
                                label="接口路径"
                                value={provider.endpoint}
                                placeholder="/v1/messages"
                                onChange={(endpoint) => updateCapability(item.id, { ...provider, endpoint })}
                              />
                              <Field
                                label="模型名称"
                                value={provider.model}
                                placeholder="填写服务端模型标识"
                                onChange={(model) => updateCapability(item.id, { ...provider, model })}
                              />
                              <Field
                                label="认证请求头"
                                value={provider.auth_header}
                                placeholder="Authorization"
                                onChange={(auth_header) => updateCapability(item.id, { ...provider, auth_header })}
                              />
                              <Field
                                label="认证前缀"
                                value={provider.auth_prefix}
                                placeholder="Bearer "
                                helper="无需手动添加末尾空格。"
                                onChange={(auth_prefix) => updateCapability(item.id, { ...provider, auth_prefix })}
                              />
                              <SecretField
                                configured={provider.api_key_set}
                                draft={secretFor(secretKey)}
                                onChange={(value) => setSecret(secretKey, value)}
                              />
                            </div>
                          </details>
                        );
                      })}
                    </div>
                  </div>
                ) : null}

                {activeTab === "output" ? (
                  <div className="settings-pane output-pane">
                    <div className="settings-pane-heading">
                      <h3>统一输出目录</h3>
                      <p>所有交付文件都限制在各自项目的输出目录内。</p>
                    </div>
                    <section className="output-policy">
                      <span className="output-policy-icon" aria-hidden="true">
                        <FolderSimple size={22} weight="regular" />
                      </span>
                      <div>
                        <h4>{config.output.directory_name}</h4>
                        <p>每个对话拥有独立目录，文件不能跨项目读取或写入。</p>
                      </div>
                    </section>
                    <div className="settings-fields">
                      <label className="settings-field">
                        <span>目录名称</span>
                        <input type="text" value={config.output.directory_name} readOnly />
                        <small>安全策略固定使用 outputs，不接受绝对路径或上级目录。</small>
                      </label>
                      <label className="settings-field">
                        <span>隔离策略</span>
                        <input
                          type="text"
                          value={config.output.policy === "conversation_isolated" ? "按对话严格隔离" : config.output.policy}
                          readOnly
                        />
                      </label>
                    </div>
                    <div className="output-formats" aria-label="默认与可选输出格式">
                      <span>Markdown · 默认</span>
                      <span>HTML · 默认</span>
                      <span>PDF · 可直接生成</span>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

            <footer className="settings-footer">
              <div className="settings-feedback-wrap" aria-live="polite">
                {error ? (
                  <div className="settings-feedback error" role="alert">
                    <WarningCircle size={17} weight="regular" aria-hidden="true" />
                    <span>{error}</span>
                  </div>
                ) : success ? (
                  <div className="settings-feedback success" role="status">
                    <CheckCircle size={17} weight="regular" aria-hidden="true" />
                    <span>{success}</span>
                  </div>
                ) : null}
              </div>
              <button className="settings-secondary-button" type="button" onClick={() => void handleLogout()} disabled={saving}>
                <SignOut size={17} weight="regular" aria-hidden="true" />
                退出管理
              </button>
              <button className="settings-primary-button" type="button" onClick={() => void handleSave()} disabled={saving}>
                <FloppyDisk size={17} weight="regular" aria-hidden="true" />
                {saving ? "正在保存" : "保存配置"}
              </button>
            </footer>
          </>
        ) : null}
      </section>
    </div>
  );
}
