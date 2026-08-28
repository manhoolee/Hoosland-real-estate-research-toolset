function clean(value: string | undefined): string {
  return value?.trim() || "";
}

function inferPublicBaseUrl(pathname: string): string {
  if (/^\/tools\/real-estate-2(?:\/|$)/.test(pathname)) {
    return "/tools/real-estate-2";
  }
  if (/^\/tools\/real-estate(?:\/|$)/.test(pathname)) {
    return "/tools/real-estate";
  }
  return "";
}

function inferSlot(publicBaseUrl: string): string {
  if (publicBaseUrl === "/tools/real-estate-2") return "slot-b";
  if (publicBaseUrl === "/tools/real-estate") return "slot-a";
  return "local";
}

const configuredBaseUrl = clean(import.meta.env.VITE_API_BASE_URL).replace(/\/$/, "");
const inferredBaseUrl = inferPublicBaseUrl(window.location.pathname);

export const API_BASE_URL = configuredBaseUrl || inferredBaseUrl;
export const DEPLOYMENT_SLOT = clean(import.meta.env.VITE_DEPLOYMENT_SLOT) || inferSlot(API_BASE_URL);
export const APP_VERSION = (clean(import.meta.env.VITE_APP_VERSION) || "0.2.3").replace(/^v/i, "");
export const APP_TITLE = "Hoosland 地产研究工作台";
export const GITHUB_REPOSITORY_URL =
  "https://github.com/manhoolee/Hoosland-real-estate-research-toolset";
export const CHANGELOG_URL = GITHUB_REPOSITORY_URL + "/blob/main/CHANGELOG.md";
export const STORAGE_NAMESPACE = `real-estate-workbench:${DEPLOYMENT_SLOT}`;
