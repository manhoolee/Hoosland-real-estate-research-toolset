#!/bin/bash
set -euo pipefail

PDF_TOOL_ROOT="${1:-/opt/hoosland-agent-tools/pdf-tool}"
case "$PDF_TOOL_ROOT" in
  /*) ;;
  *)
    echo "PDF tool root must be an absolute path" >&2
    exit 2
    ;;
esac

if [[ ! -f "$PDF_TOOL_ROOT/package.json" ]]; then
  echo "PDF tool package not found at $PDF_TOOL_ROOT" >&2
  exit 2
fi

cd "$PDF_TOOL_ROOT"
NPM_BIN="${HOOSLAND_PDF_NPM_BIN:-$(command -v npm)}"
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 "$NPM_BIN" ci --omit=dev --ignore-scripts
PLAYWRIGHT_BROWSERS_PATH="$PDF_TOOL_ROOT/browsers" \
  "$PDF_TOOL_ROOT/node_modules/.bin/playwright" install --only-shell chromium

chown -R root:root "$PDF_TOOL_ROOT"
chmod -R go-w "$PDF_TOOL_ROOT"
chmod 0755 "$PDF_TOOL_ROOT/render-html-to-pdf.mjs" "$PDF_TOOL_ROOT/inspect-pdf.py" "$PDF_TOOL_ROOT/validate_pdf.py"
install -m 0755 "$PDF_TOOL_ROOT/bin/hoosland-pdf-render" /usr/local/bin/hoosland-pdf-render
install -m 0755 "$PDF_TOOL_ROOT/bin/hoosland-pdf-inspect" /usr/local/bin/hoosland-pdf-inspect
