#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from pypdf import PdfReader


MAX_PDF_BYTES = 100 * 1024 * 1024


def inspect(path: Path) -> dict[str, int | bool]:
    size = path.stat().st_size
    if size > MAX_PDF_BYTES:
        raise ValueError("PDF 超过 100MB 限制")
    data = path.read_bytes()
    if len(data) < 1024 or not data.startswith(b"%PDF-"):
        raise ValueError("文件不是有效 PDF")
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise ValueError("PDF 不得加密")
    pages = len(reader.pages)
    if pages < 1 or pages > 200:
        raise ValueError(f"PDF 页数异常：{pages}")
    text_characters = 0
    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if min(width, height) < 36 or max(width, height) > 3000:
            raise ValueError(f"PDF 页面尺寸异常：{width:.1f} x {height:.1f} pt")
        text_characters += len("".join((page.extract_text() or "").split()))
    return {
        "pages": pages,
        "bytes": len(data),
        "text_characters": text_characters,
        "encrypted": False,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：validate_pdf.py <文件.pdf>")
    try:
        print(json.dumps(inspect(Path(sys.argv[1])), ensure_ascii=False))
    except Exception as exc:
        print(f"PDF_VALIDATE_ERROR {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
