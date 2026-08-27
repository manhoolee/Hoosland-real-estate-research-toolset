import {
  ArrowSquareOut,
  CheckCircle,
  GithubLogo,
  GitBranch,
  X,
} from "@phosphor-icons/react";
import { useEffect, useRef } from "react";
import type { ReleaseIdentity } from "../api";
import { APP_VERSION, CHANGELOG_URL, GITHUB_REPOSITORY_URL } from "../deployment";
import { RELEASE_INFO } from "../releaseInfo";

interface ReleaseInfoDialogProps {
  identity: ReleaseIdentity | null;
  onClose: () => void;
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
].join(",");

export function ReleaseInfoDialog({ identity, onClose }: ReleaseInfoDialogProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const runtimeVersion = identity?.version || "";
  const buildId = identity?.buildId || "尚未读取运行版本";
  const runtimeIdentity = [
    identity?.slot,
    runtimeVersion ? `V${runtimeVersion}` : "",
    buildId,
  ].filter(Boolean).join(" · ");
  const versionMismatch = Boolean(runtimeVersion && runtimeVersion !== APP_VERSION);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
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
  }, [onClose]);

  return (
    <div
      className="release-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        id="release-dialog"
        ref={dialogRef}
        className="release-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="release-title"
        tabIndex={-1}
      >
        <header className="release-header">
          <div>
            <span className="release-eyebrow">RELEASE LEDGER · V{APP_VERSION}</span>
            <h2 id="release-title">{RELEASE_INFO.iteration}</h2>
            <p>{RELEASE_INFO.summary}</p>
          </div>
          <button
            ref={closeButtonRef}
            className="release-close"
            type="button"
            onClick={onClose}
            aria-label="关闭版本信息"
          >
            <X size={20} weight="regular" aria-hidden="true" />
          </button>
        </header>

        <div className="release-identity" aria-label="当前运行版本">
          <div>
            <span>Frontend release</span>
            <strong>V{APP_VERSION}</strong>
          </div>
          <div>
            <span>发布日期</span>
            <strong>{RELEASE_INFO.releasedAt}</strong>
          </div>
          <div>
            <span>兼容性</span>
            <strong>{RELEASE_INFO.compatibility}</strong>
          </div>
        </div>

        <div className="release-build">
          <GitBranch size={17} weight="regular" aria-hidden="true" />
          <span>当前运行后端</span>
          <code title={runtimeIdentity}>{runtimeIdentity}</code>
        </div>

        {versionMismatch ? (
          <p className="release-version-warning" role="status">
            本页记录前端 V{APP_VERSION}；当前连接的后端为 V{runtimeVersion}，两者版本不同。
          </p>
        ) : null}

        <ol className="release-change-list" aria-label="本次修改内容">
          {RELEASE_INFO.changes.map((change, index) => (
            <li key={change.title}>
              <span className="release-change-index">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <h3>{change.title}</h3>
                <p>{change.description}</p>
              </div>
              <CheckCircle size={19} weight="regular" aria-hidden="true" />
            </li>
          ))}
        </ol>

        <footer className="release-footer">
          <a
            className="release-github-button"
            href={GITHUB_REPOSITORY_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            <GithubLogo size={18} weight="regular" aria-hidden="true" />
            查看 GitHub 源码
            <ArrowSquareOut size={15} weight="regular" aria-hidden="true" />
          </a>
          <a
            className="release-changelog-link"
            href={CHANGELOG_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            完整更新记录
            <ArrowSquareOut size={14} weight="regular" aria-hidden="true" />
          </a>
        </footer>
      </section>
    </div>
  );
}
