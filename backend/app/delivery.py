"""Final file delivery checks; filesystem paths alone are never a receipt."""
from __future__ import annotations

import re
from pathlib import Path


def requires_report_pair(request: str, changed_names: set[str]) -> bool:
    if re.search(r"不要(?:生成)?文件|无需(?:生成)?文件|只(?:在聊天|需回复|要文字)|仅(?:在聊天|需回复)", request):
        return False
    if re.search(r"微信|公众号|小红书|抖音|朋友圈|数据表|数据模型", request) and not re.search(r"(?:研究|分析|管理)报告", request):
        return False
    formats = r"(?:markdown|\bmd\b|html|pdf|word|docx?|pptx?|xlsx?|excel|csv|json|网页)"
    requested = re.findall(
        rf"(?:输出|导出|生成|交付|提供|只要|只需|格式|保存).{{0,25}}{formats}|{formats}.{{0,8}}(?:格式|文件|版)",
        request, re.IGNORECASE,
    )
    if requested:
        specification = " ".join(requested).lower()
        return bool(re.search(r"markdown|\bmd\b", specification) and "html" in specification)
    # Once a report artifact has been produced, the default pair is mandatory.
    # Explicit report requests also cannot finish with just a prose claim.
    return any(Path(name).suffix.lower() in {".md", ".html"} for name in changed_names) or bool(
        re.search(r"(?:输出|生成|撰写|编制|交付|整理|形成).{0,20}(?:报告|方案)", request)
    )


def has_report_pair(names: set[str], output_dir: Path) -> bool:
    for name in names:
        if Path(name).suffix.lower() != ".md":
            continue
        html_name = str(Path(name).with_suffix(".html"))
        if html_name not in names:
            continue
        html = (output_dir / html_name).read_text(encoding="utf-8", errors="replace")
        if re.search(r"<html\b", html, re.I) and re.search(r"<body\b", html, re.I) and re.search(r"</body\s*>", html, re.I):
            return True
    return False
