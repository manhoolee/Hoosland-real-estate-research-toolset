# Hoosland PDF runtime

Persistent, root-owned HTML-to-PDF and PDF-inspection commands for
Hoosland-real-estate-research-toolset. The commands discover the current isolated
workspace, only accept HTML from that workspace, only write final PDFs to its
`outputs` directory, and only write rendered QA pages to its `work` directory.

Runtime commands:

```bash
hoosland-pdf-render work/report.html outputs/report.pdf
hoosland-pdf-inspect outputs/report.pdf work/report-pdf-preview
```

Install the Playwright runtime once as root with `install-runtime.sh`. PDF
validation uses the BSD-licensed `pypdf` package from
`backend/requirements.txt`; page rendering uses the OS `poppler-utils`
package. The service account must have read/execute access to
`/opt/hoosland-real-estate-research-toolset/pdf-tool` but must not own or modify it. Override
the root or Python path with `HOOSLAND_PDF_TOOL_ROOT` and
`HOOSLAND_PDF_PYTHON_BIN` when using a different immutable installation path.
The default Python path is
`/opt/hoosland-real-estate-research-toolset/current/.venv/bin/python`, so each immutable
application release carries the matching Python dependencies.
