#!/usr/bin/env node

import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { access, readFile, realpath, rename, rm, stat } from "node:fs/promises";
import { dirname, extname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

const MAX_HTML_BYTES = 25 * 1024 * 1024;
const MAX_PDF_BYTES = 100 * 1024 * 1024;
const toolRoot = dirname(fileURLToPath(import.meta.url));
const pythonBin =
  process.env.HOOSLAND_PDF_PYTHON_BIN ||
  "/opt/hoosland-agent-tools/venv/bin/python";
process.env.PLAYWRIGHT_BROWSERS_PATH ||= join(toolRoot, "browsers");

const { chromium } = await import("playwright");
const execFileAsync = promisify(execFile);

let terminating = false;
function terminate(error) {
  if (terminating) return;
  terminating = true;
  const message = error instanceof Error ? error.message : String(error);
  console.error(`PDF_RENDER_ERROR ${message}`);
  process.exitCode = 1;
}
process.on("uncaughtException", terminate);
process.on("unhandledRejection", terminate);

function fail(message) {
  throw new Error(message);
}

function isWithin(root, candidate) {
  const path = relative(root, candidate);
  return path === "" || (!path.startsWith("..") && !isAbsolute(path));
}

async function looksLikeWorkspace(candidate) {
  try {
    await Promise.all(
      ["inputs", "work", "outputs"].map((name) => access(join(candidate, name))),
    );
    return true;
  } catch {
    return false;
  }
}

async function findWorkspaceRoot() {
  if (process.env.DSH_CWD) {
    const configured = await realpath(process.env.DSH_CWD);
    if (await looksLikeWorkspace(configured)) return configured;
  }
  let candidate = await realpath(process.cwd());
  while (true) {
    if (await looksLikeWorkspace(candidate)) return candidate;
    const parent = dirname(candidate);
    if (parent === candidate) break;
    candidate = parent;
  }
  fail("无法定位包含 inputs、work、outputs 的隔离工作区");
}

async function requestIsAllowed(workspace, requestUrl) {
  try {
    const url = new URL(requestUrl);
    if (["about:", "blob:", "data:"].includes(url.protocol)) return true;
    if (url.protocol !== "file:") return false;
    const requested = await realpath(fileURLToPath(url));
    return isWithin(workspace, requested);
  } catch {
    return false;
  }
}

const [inputArgument, outputArgument] = process.argv.slice(2);
if (!inputArgument || !outputArgument) {
  fail("用法：hoosland-pdf-render <输入.html> <outputs/成品.pdf>");
}

const workspace = await findWorkspaceRoot();
const workRoot = await realpath(join(workspace, "work"));
const outputsRoot = await realpath(join(workspace, "outputs"));
if (!isWithin(workspace, workRoot) || !isWithin(workspace, outputsRoot)) {
  fail("工作区 work 或 outputs 目录越过了隔离边界");
}
const input = await realpath(resolve(workspace, inputArgument));
if (!isWithin(workspace, input)) fail("输入 HTML 必须位于当前隔离工作区");
if (![".html", ".htm"].includes(extname(input).toLowerCase())) {
  fail("输入文件必须是 .html 或 .htm");
}
const inputStat = await stat(input);
if (!inputStat.isFile()) fail("输入路径不是文件");
if (inputStat.size > MAX_HTML_BYTES) fail("输入 HTML 超过 25MB 限制");

const output = resolve(workspace, outputArgument);
if (!isWithin(outputsRoot, output)) fail("最终 PDF 必须位于当前工作区的 outputs 目录");
if (extname(output).toLowerCase() !== ".pdf") fail("输出文件必须使用 .pdf 扩展名");
const outputParent = await realpath(dirname(output));
if (!isWithin(outputsRoot, outputParent)) fail("PDF 输出目录越过了隔离边界");

const temporary = join(workRoot, `.pdf-render-${randomUUID()}.tmp.pdf`);
let browser;
let blockedRequests = 0;
try {
  try {
    browser = await chromium.launch({
      headless: true,
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--font-render-hinting=none",
      ],
    });
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      serviceWorkers: "block",
    });
    await context.setOffline(true);
    const page = await context.newPage();
    page.setDefaultTimeout(30_000);
    await page.route("**/*", async (route) => {
      if (await requestIsAllowed(workspace, route.request().url())) {
        await route.continue();
      } else {
        blockedRequests += 1;
        await route.abort("blockedbyclient");
      }
    });
    if (typeof page.routeWebSocket === "function") {
      await page.routeWebSocket(/.*/, (socket) => socket.close());
    }
    await page.goto(pathToFileURL(input).href, { waitUntil: "load", timeout: 30_000 });
    await page.emulateMedia({ media: "print" });
    await page.evaluate(async () => {
      if (document.fonts?.ready) await document.fonts.ready;
      await Promise.all(
        Array.from(document.images).map(
          (image) =>
            image.complete ||
            new Promise((resolveImage) => {
              image.addEventListener("load", resolveImage, { once: true });
              image.addEventListener("error", resolveImage, { once: true });
            }),
        ),
      );
    });
    await page.pdf({
      path: temporary,
      format: "A4",
      printBackground: true,
      preferCSSPageSize: true,
      margin: { top: "12mm", right: "11mm", bottom: "12mm", left: "11mm" },
      displayHeaderFooter: false,
      tagged: true,
      outline: true,
    });
  } finally {
    if (browser) await browser.close();
  }

  const bytes = await readFile(temporary);
  if (
    bytes.length < 1024 ||
    bytes.length > MAX_PDF_BYTES ||
    bytes.subarray(0, 5).toString("ascii") !== "%PDF-"
  ) {
    fail("渲染结果不是有效 PDF，或超过 100MB 限制");
  }
  const validationProcess = await execFileAsync(
    pythonBin,
    [join(toolRoot, "validate_pdf.py"), temporary],
    { encoding: "utf8", maxBuffer: 1024 * 1024, timeout: 30_000 },
  );
  const validation = JSON.parse(validationProcess.stdout);
  await rename(temporary, output);
  console.log(
    JSON.stringify({
      status: "ok",
      output: relative(workspace, output),
      pages: validation.pages,
      bytes: bytes.length,
      text_characters: validation.text_characters,
      network_policy: "offline-workspace-only",
      blocked_requests: blockedRequests,
    }),
  );
} catch (error) {
  await rm(temporary, { force: true });
  throw error;
}
