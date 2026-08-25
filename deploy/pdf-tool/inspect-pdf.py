#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from validate_pdf import inspect


def is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def looks_like_workspace(candidate: Path) -> bool:
    return all((candidate / name).is_dir() for name in ("inputs", "work", "outputs"))


def workspace_root() -> Path:
    configured = os.environ.get("DSH_CWD")
    if configured:
        candidate = Path(configured).resolve(strict=True)
        if looks_like_workspace(candidate):
            return candidate
    candidate = Path.cwd().resolve(strict=True)
    for current in (candidate, *candidate.parents):
        if looks_like_workspace(current):
            return current
    raise ValueError("无法定位包含 inputs、work、outputs 的隔离工作区")


def main() -> dict[str, object]:
    if len(sys.argv) not in (2, 3):
        raise ValueError("用法：hoosland-pdf-inspect <outputs/成品.pdf> [work/预览目录]")
    workspace = workspace_root()
    outputs = (workspace / "outputs").resolve(strict=True)
    work = (workspace / "work").resolve(strict=True)
    if not is_within(workspace, outputs) or not is_within(workspace, work):
        raise ValueError("工作区 work 或 outputs 目录越过了隔离边界")
    pdf = (workspace / sys.argv[1]).resolve(strict=True)
    if not is_within(outputs, pdf) or pdf.suffix.lower() != ".pdf" or not pdf.is_file():
        raise ValueError("待检查 PDF 必须位于当前工作区的 outputs 目录")

    preview_argument = sys.argv[2] if len(sys.argv) == 3 else f"work/pdf-preview-{time.time_ns()}"
    preview_relative = Path(preview_argument)
    if (
        preview_relative.is_absolute()
        or len(preview_relative.parts) != 2
        or preview_relative.parts[0] != "work"
        or not re.fullmatch(r"[A-Za-z0-9._\-\u4e00-\u9fff]{1,128}", preview_relative.parts[1])
    ):
        raise ValueError("逐页预览必须是 work 下的单层安全目录")
    preview_candidate = work / preview_relative.parts[1]
    if preview_candidate.is_symlink():
        raise ValueError("逐页预览目录不得是符号链接")
    if not preview_candidate.exists():
        preview_candidate.mkdir(mode=0o750)
    preview = preview_candidate.resolve(strict=True)
    if not is_within(work, preview):
        raise ValueError("逐页预览目录越过了隔离边界")
    if any(preview.iterdir()):
        raise ValueError("逐页预览目录必须为空，请使用新的 work 子目录")

    validation = inspect(pdf)
    prefix = preview / "page"
    subprocess.run(
        ["/usr/bin/pdftoppm", "-png", "-scale-to", "2400", str(pdf), str(prefix)],
        check=True,
        timeout=120,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    pages = sorted(preview.glob("page-*.png"))
    if len(pages) != validation["pages"] or any(path.stat().st_size < 1024 for path in pages):
        raise ValueError("逐页 PNG 渲染结果不完整")
    return {
        "status": "ok",
        "pdf": str(pdf.relative_to(workspace)),
        **validation,
        "preview_directory": str(preview.relative_to(workspace)),
        "page_previews": [str(path.relative_to(workspace)) for path in pages],
    }


if __name__ == "__main__":
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception as exc:
        print(f"PDF_INSPECT_ERROR {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
