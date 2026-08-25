#!/usr/bin/env python3
"""Render practical Markdown reports to a standalone, print-ready HTML file."""

import argparse
import html
import re
from pathlib import Path


def slug(text: str, used: set[str]) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff]+", "-", re.sub(r"[*_`]", "", text)).strip("-").lower() or "section"
    value = base
    index = 2
    while value in used:
        value = f"{base}-{index}"
        index += 1
    used.add(value)
    return value


def inline(value: str) -> str:
    value = html.escape(value, quote=False)
    value = re.sub(r'!\[([^\]]+)\]\(([^)]+)\)', r'<figure class="report-figure"><img src="\2" alt="\1" loading="lazy"><figcaption>\1</figcaption></figure>', value)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", value)
    value = re.sub(r"\b(FACT-[ABC]|DERIVED|INFERENCE|HYPOTHESIS|RECOMMENDATION)\b", r'<span class="tag">\1</span>', value)
    return value


def split_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator(line: str) -> bool:
    cells = split_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def render(markdown: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = markdown.replace("\r\n", "\n").split("\n")
    output: list[str] = []
    toc: list[tuple[int, str, str]] = []
    used: set[str] = set()
    index = 0
    paragraph: list[str] = []
    list_type: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            rendered = inline(" ".join(item.strip() for item in paragraph)).replace("[[[BR]]]", "<br>")
            output.append(f"<p>{rendered}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            output.append(f"</{list_type}>")
            list_type = None

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph(); close_list()
            lang = stripped[3:].strip()
            index += 1
            code: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index]); index += 1
            output.append(f'<pre><code class="language-{html.escape(lang)}">{html.escape(chr(10).join(code))}</code></pre>')
        elif not stripped:
            flush_paragraph(); close_list()
        elif re.match(r"^#{1,4}\s+", stripped):
            flush_paragraph(); close_list()
            marks, title = stripped.split(" ", 1)
            level = len(marks)
            anchor = slug(title, used)
            if level <= 3:
                toc.append((level, re.sub(r"[*_`]", "", title), anchor))
            output.append(f'<h{level} id="{anchor}">{inline(title)}</h{level}>')
        elif index + 1 < len(lines) and "|" in stripped and is_separator(lines[index + 1]):
            flush_paragraph(); close_list()
            headers = split_cells(stripped)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(split_cells(lines[index])); index += 1
            index -= 1
            output.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in headers) + "</tr></thead><tbody>")
            for row in rows:
                padded = row + [""] * (len(headers) - len(row))
                output.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in padded[:len(headers)]) + "</tr>")
            output.append("</tbody></table>")
        elif stripped.startswith(">"):
            flush_paragraph(); close_list()
            output.append(f"<blockquote>{inline(stripped.lstrip('> ').strip())}</blockquote>")
        elif re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+[.)]\s+", stripped):
            flush_paragraph()
            ordered = bool(re.match(r"^\d+[.)]\s+", stripped))
            target = "ol" if ordered else "ul"
            if list_type != target:
                close_list(); output.append(f"<{target}>"); list_type = target
            item = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", stripped)
            output.append(f"<li>{inline(item)}</li>")
        elif re.fullmatch(r"[-*_]{3,}", stripped):
            flush_paragraph(); close_list(); output.append("<hr>")
        else:
            paragraph.append(stripped + (" [[[BR]]]" if line.endswith("  ") else ""))
        index += 1
    flush_paragraph(); close_list()
    return "\n".join(output), toc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_markdown")
    parser.add_argument("output_html")
    parser.add_argument("--title")
    parser.add_argument("--subtitle", default="HOOSLAND · 地产研判与策划")
    parser.add_argument("--css")
    args = parser.parse_args()
    source = Path(args.input_markdown)
    markdown = source.read_text(encoding="utf-8")
    title = args.title or next((re.sub(r"^#\s+", "", line) for line in markdown.splitlines() if line.startswith("# ")), source.stem)
    body_markdown = re.sub(r"\A#\s+[^\n]+\n+", "", markdown, count=1)
    body, toc = render(body_markdown)
    css_path = Path(args.css) if args.css else Path(__file__).resolve().parent.parent / "assets" / "report-style.css"
    css = css_path.read_text(encoding="utf-8")
    nav = "\n".join(f'<a href="#{anchor}" class="l{level}">{html.escape(text)}</a>' for level, text, anchor in toc if level >= 2)
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">
<title>{html.escape(title)}</title><style>{css}</style></head>
<body><article class="page"><header><div class="kicker">REAL ESTATE STRATEGY · v2.3</div><h1>{html.escape(title)}</h1><p>{html.escape(args.subtitle)}</p></header>
<div class="layout"><nav><strong>目录</strong>{nav}</nav><main>{body}</main></div></article></body></html>\n"""
    Path(args.output_html).write_text(document, encoding="utf-8")
    print(Path(args.output_html).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
