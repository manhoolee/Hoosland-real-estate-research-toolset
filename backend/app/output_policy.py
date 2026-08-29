"""Deterministic egress guard for assistant text.

The ingress policy keeps obvious probes away from the model, but a model can
still be misled by an attachment, a retrieved page, or a future prompt
regression.  This small second gate looks only for high-signal internal
material in the final text.  It never attempts to rewrite a partial leak: a
hit is replaced with the same short local refusal and the original text is
kept out of storage, SSE, and audit fields.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from dataclasses import dataclass
from pathlib import Path
from itertools import islice
from urllib.parse import unquote

from .policy import POLICY_REFUSAL, is_prompt_probe, normalize_text


OUTPUT_POLICY_VERSION = "egress-gate-v1"


@dataclass(frozen=True, slots=True)
class OutputDecision:
    """Sanitized assistant projection and private audit classification."""

    content: str
    blocked: bool
    reason_code: str | None = None
    policy_version: str = OUTPUT_POLICY_VERSION


# These expressions intentionally require an internal marker or a secret-like
# value.  Ordinary project language such as “销售模型参数” or “工具返回的
# 市场数据” must remain deliverable.
_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ROLE_MARKER",
        re.compile(
            r"(?:\[\s*(?:system|developer|assistant)\s*\]|"
            r"<\s*(?:system|developer|assistant)\s*>|"
            r"(?:begin|end)[\s_-]+(?:system|developer|assistant)|"
            r"(?:[\"']?role[\"']?\s*[:=]\s*[\"']?(?:system|developer|assistant)|"
            r"<\s*role\s*>\s*(?:system|developer|assistant)\s*<\s*/\s*role\s*>)"
            r")",
            re.IGNORECASE,
        ),
    ),
    (
        "PROTECTED_EXTRACTION",
        re.compile(
            r"(?:show|print|dump|reveal|display|list|provide|give\s+me|tell\s+me|"
            r"output|share|paste|return|read|open|view|translate|decode|describe|"
            r"explain|输出|打印|显示|展示|列出|提供|给我|告诉我|导出|读取|查看|打开|"
            r"翻译|解码|说明|描述|解释).{0,96}"
            r"(?:system[\s_-]*(?:prompt|message|instructions?|rules?|configuration)|"
            r"developer[\s_-]*(?:prompt|message|instructions?|rules?)|hidden[\s_-]*(?:prompt|"
            r"context|policy|rules?)|internal[\s_-]*(?:prompt|context|reasoning|rules?|config)|"
            r"(?:skill|tool|plugin)[\s_-]*(?:list|content|source|file|schema|manifest|definition)|"
            r"(?:reasoning|chain[\s_-]*of[\s_-]*thought)[\s_-]*(?:trace|process)?|"
            r"(?:runtime|environment)[\s_-]*(?:environment|config(?:uration)?|variables?)|"
            r"backend[\s_-]*version|instruction[\s_-]*(?:hierarchy|set)|prompt[\s_-]*template|"
            r"meta[\s_-]*prompt|guardrail[\s_-]*rules?|capabilit(?:y|ies)[\s_-]*(?:manifest|list)|"
            r"function[\s_-]*(?:definitions?|schema)|mcp[\s_-]*(?:server|service)|"
            r"(?:模型|大模型|语言模型)(?:名称|版本|参数|配置)|(?:服务商|供应商)(?:名称|版本|配置)|"
            r"(?:model|llm|provider|vendor)(?:\s+|[_-])(?:name|version|config(?:uration)?|parameters?)|"
            r"(?:系统|内部|隐藏|开发者)(?:提示|指令|消息|规则|配置|环境变量)|"
            r"(?:推理)(?:过程|轨迹)|(?:运行时)(?:环境|配置)|后端版本|私钥|密钥文件|"
            r"(?:密钥|令牌|环境变量)|API[\s_-]*密钥|"
            r"(?:api[\s_-]*key|access[\s_-]*token|client[\s_-]*secret|private[\s_-]*key|"
            r"environment[\s_-]*(?:variables?|vars?)|\.env|/etc/|/passwd|secret[\s_-]*(?:file|config)))"
            r"|(?:system[\s_-]*(?:prompt|message|instructions?|rules?)|developer[\s_-]*"
            r"(?:prompt|message|instructions?|rules?)|hidden[\s_-]*(?:prompt|context|policy|rules?)|"
            r"internal[\s_-]*(?:prompt|context|reasoning|rules?|config)|(?:skill|tool|plugin)[\s_-]*"
            r"(?:list|content|source|file|schema|manifest|definition)|reasoning[\s_-]*(?:trace|process)|"
            r"runtime[\s_-]*(?:environment|config(?:uration)?|variables?)|backend[\s_-]*version|"
            r"instruction[\s_-]*(?:hierarchy|set)|prompt[\s_-]*template|meta[\s_-]*prompt|"
            r"guardrail[\s_-]*rules?|capabilit(?:y|ies)[\s_-]*(?:manifest|list)|function[\s_-]*"
            r"(?:definitions?|schema)|mcp[\s_-]*(?:server|service)|(?:api[\s_-]*key|access[\s_-]*token|"
            r"client[\s_-]*secret|private[\s_-]*key|environment[\s_-]*(?:variables?|vars?)|\.env|"
            r"/etc/|/passwd|secret[\s_-]*(?:file|config))).{0,96}"
            r"(?:show|print|dump|reveal|display|list|provide|give\s+me|tell\s+me|output|share|"
            r"paste|return|read|open|view|translate|decode|describe|explain|输出|打印|显示|展示|列出|"
            r"提供|给我|告诉我|导出|读取|查看|打开|翻译|解码|说明|描述|解释)",
            re.IGNORECASE,
        ),
    ),
    (
        "RUNTIME_PROBE",
        re.compile(
            # Asking about the assistant's runtime/skill inventory is not the
            # same as asking which forecasting model a project should use.
            r"(?:what|which|who|tell\s+me|show\s+me|give\s+me|name|list|print|"
            r"reveal|describe|what\s+is|what's|请问|显示|列出|告诉我|输出|打印).{0,64}"
            r"(?:your|you\s+(?:are|use|using)|this\s+assistant|the\s+assistant|"
            r"current|underlying|active|deployed|configured|loaded|available|"
            r"你的|本助手|当前(?:使用|运行|部署)?的?|正在使用的|运行中的|部署的).{0,48}"
            r"(?:model|llm|provider|vendor|runtime|harness|skill(?:s)?|tool(?:s)?|"
            r"plugin(?:s)?|capabilit(?:y|ies)|function(?:s)?|version|config(?:uration)?|"
            r"environment|checkpoint|deployment|模型|大模型|服务商|供应商|运行时|"
            r"技能|工具|插件|能力|函数|版本|配置|环境|检查点|部署)"
            r"|(?:what|which)\s*(?:model|llm|provider|runtime|harness)\s*"
            r"(?:are|is|do|did)\s*(?:you|this\s+assistant)\s*"
            r"(?:using|running|configured|based|use|run)"
            r"|(?:your|this\s+assistant's|current|underlying|active|deployed|"
            r"configured|loaded|assistant|this\s+assistant|本助手的?|当前(?:使用|运行|部署)?的?|正在使用的|运行中的|部署的)"
            r"\s*(?:model|llm|provider|vendor|runtime|harness|skill(?:s)?|tool(?:s)?|"
            r"plugin(?:s)?|capabilit(?:y|ies)|function(?:s)?|模型|大模型|服务商|供应商|"
            r"运行时|技能|工具|插件|能力|函数)\s*(?:name|version|config(?:uration)?|"
            r"parameters?|is|are|为|是|叫|名称|版本|配置)?\s*[:=：]?"
            r"|(?:the\s+)?(?:model|llm|provider|runtime|skill(?:s)?|tool(?:s)?|"
            r"capabilit(?:y|ies))\s+(?:used\s+by|from)\s+(?:the\s+)?"
            r"(?:assistant|this\s+assistant|you|本助手)\s*(?:is|are|为|是|叫|[:=])"
            r"|(?:model|llm|provider|runtime|skill|tool|能力|模型|服务商)\s+"
            r"(?:name|version|名称|版本)\s*[:=：]"
        ),
    ),
    (
        "RUNTIME_INVENTORY",
        re.compile(
            r"(?:show|print|dump|reveal|list|display|enumerate|provide|give\s+me|"
            r"输出|打印|显示|展示|列出|枚举|告诉我|提供|给我).{0,48}"
            r"(?:instruction\s+hierarchy|hidden\s+policy|latent\s+context|"
            r"reasoning\s+trace|prompt\s+template|meta\s+prompt|"
            r"guardrail\s+rules?|available\s+functions?|capabilit(?:y|ies)\s+"
            r"(?:manifest|list)|function\s+definitions?|mcp\s+server|"
            r"runtime\s+environment|backend\s+version|"
            r"(?:all|your|available|active|installed|loaded)?\s*(?:skills?|tools?|plugins?|"
            r"capabilities?|functions?|能力|技能|工具|插件)(?:\s*(?:list|清单|列表|manifest))?|"
            r"指令(?:层级|体系)|隐藏策略|潜在上下文|推理(?:轨迹|过程)|提示模板|元提示|"
            r"护栏规则|可用函数|(?:技能|工具|插件)(?:清单|列表|内容|定义|参数|源码|文件|路径)?|"
            r"能力(?:清单|列表)|函数定义|MCP(?:服务器|服务)|"
            r"运行时环境|后端版本)"
        ),
    ),
    (
        "SYSTEM_INSTRUCTION",
        re.compile(
            r"(?:system[\s_-]*(?:prompt|message|instructions?)|"
            r"system[\s_-]*(?:setup|directives?)\s*(?:is|=|:)|"
            r"developer[\s_-]*(?:message|prompt|instructions?)|"
            r"hidden[\s_-]*(?:context|instructions?|prompt)|"
            r"chain[- ]of[- ]thought|\bcot\b|"
            # A generic phrase such as “which model should we use?” is a
            # legitimate research question.  Treat model/provider wording as
            # runtime leakage only when it is explicitly presented as a
            # current, assistant-owned value.
            r"(?:\b(?:current|underlying|deployed|active|configured|loaded)\s+"
            r"(?:model|llm|provider|runtime|harness)\b\s*(?:is|=|:)|"
            r"(?:当前(?:使用|运行|部署)?的?|本助手的?)"
            r"(?:模型|大模型|服务商|运行时)\s*(?:是|为|：|:|=))|"
            r"(?:print|show|dump|reveal|output|list).{0,40}(?:internal|hidden)\s*"
            r"(?:reasoning|rules?|instructions?|context)|"
            r"系统提示词|开发者(?:提示词|指令)|隐藏(?:上下文|提示)|"
            r"内部(?:提示词|指令|上下文|推理)|思维链)"
        ),
    ),
    (
        "RUNTIME_MARKER",
        re.compile(
            r"(?:<\|(?:system|developer|assistant)\|>|"
            r"/comprehensive-real-estate-expert|"
            r"(?:backend/)?cordis\.ya?ml|"
            r"(?:DEEPSEEK|DSH|CAPABILITY_MCP)_[A-Z0-9_]+|"
            r"\bdeepseek[-_][a-z0-9][a-z0-9._-]*\b|"
            r"\bSKILL\.md\b|\bskill\s+(?:source|file|content)\b|"
            r"agent[_ -]?session(?:[_ -]?id)?|"
            r"(?:主控\s*Skill|已加载\s*Skill|总控激活))",
            re.IGNORECASE,
        ),
    ),
    (
        "RAW_TOOL_CALL",
        re.compile(
            r"(?:\"?tool[_ -]?calls?\"?\s*[:：]|\"?function[_ -]?call\"?\s*[:：]|"
            r"\"?(?:arguments|parameters)\"?\s*[:：]\s*\{[^\n]{0,400}\}|"
            r"(?:工具调用|工具参数|调用参数|tool\s+call)\s*[:：]\s*[^\n]{0,400})",
            re.IGNORECASE,
        ),
    ),
    (
        "SECRET_VALUE",
        re.compile(
            r"[\"'`]?(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|"
            r"private[_ -]?key|session[_ -]?token|auth[_ -]?token|refresh[_ -]?token|"
            r"secret|password|token|密钥|令牌|密码)\b[\"'`]?"
            r"\s*(?:[:=：]|\bis\b|为)\s*[\"'`]?[^\"'`\r\n\s]{8,}[\"'`]?|"
            r"\bbearer\s+[A-Za-z0-9_./+\-=]{8,}|"
            r"\bapi[_ -]?key\s+[A-Za-z0-9_./+\-=@:$]{16,}|"
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
            r"\b(?:eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "INTERNAL_PATH",
        re.compile(
            r"(?:[A-Z]:[\\/][^\s]{1,220}|"
            r"(?:\\\\|//)[^\s]{1,220}|"
            r"/(?:etc|var|home|workspace|app|tmp|opt|mnt|run|proc)[\\/][^\s]{1,220}|"
            r"~/(?:[^\s]{0,120})(?:\.env|secret|token|private)[^\s]*|"
            r"file://[^\s]{1,220}|"
            r"https?://[^\s]{0,180}(?:\.env|cordis\.ya?ml|SKILL\.md|\.codex|secret|token)[^\s]*)|"
            r"(?:^|[\s\"'`=/])(?:\.env|SKILL\.md|cordis\.ya?ml|secret(?:s)?\.?(?:txt|json|ya?ml)?|token\.?(?:txt|json)?)\b",
            re.IGNORECASE,
        ),
    ),
)

_LEAK_NAME_PATTERN = re.compile(
    r"(?:^|[._-])(?:\.env|prompt|system|developer|skill|cordis|secret|token|api[_-]?key|"
    r"deepseek|comprehensive-real-estate-expert|mcp)"
    r"(?:$|[._-])",
    re.IGNORECASE,
)
_TEXT_SUFFIXES = frozenset(
    {
        ".c",
        ".cfg",
        ".conf",
        ".csv",
        ".htm",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".log",
        ".md",
        ".properties",
        ".py",
        ".svg",
        ".text",
        ".txt",
        ".ts",
        ".tsv",
        ".xml",
        ".yaml",
        ".yml",
    }
)
_MAX_FILE_SCAN_BYTES = 2 * 1024 * 1024

# A deliberately small homoglyph map is enough for the common “system/prompt”
# and secret-key evasions.  It is kept local to the egress scanner so output
# checks do not inherit the higher-recall business-intent vocabulary.
_CONFUSABLES = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "ѕ": "s",
        "х": "x", "у": "y", "і": "i", "ј": "j", "ӏ": "l", "ԁ": "d",
        "м": "m", "н": "h", "т": "t", "к": "k", "в": "b", "г": "r",
        "Α": "a", "Β": "b", "Ε": "e", "Ι": "i", "Κ": "k", "Μ": "m",
        "Ν": "n", "Ο": "o", "Ρ": "p", "Τ": "t", "Χ": "x",
        "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "μ": "m",
        "ν": "n", "ο": "o", "ρ": "p", "τ": "t", "χ": "x",
    }
)
_UNICODE_ESCAPE = re.compile(
    r"\\u([0-9a-f]{4})|\\U([0-9a-f]{8})|\\x([0-9a-f]{2})", re.IGNORECASE
)
_ENCODED_PAYLOAD = re.compile(
    r"(?:base64|b64|encoded|decode|解码|编码|hex)\s*[:=：]?\s*"
    r"([A-Za-z0-9+/]{12,}={0,2}|(?:[0-9a-f]{2}){6,})",
    re.IGNORECASE,
)


def _decode_unicode_escapes(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = next((group for group in match.groups() if group), "")
        try:
            codepoint = int(raw, 16)
        except ValueError:
            return match.group(0)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            return match.group(0)
        return chr(codepoint)

    return _UNICODE_ESCAPE.sub(replace, value)


def _printable_payload(value: bytes) -> str | None:
    if not value or len(value) > 4096:
        return None
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not decoded or len(decoded) > 2048:
        return None
    printable = sum(char.isprintable() or char.isspace() for char in decoded)
    return decoded if printable / len(decoded) >= 0.78 else None


def _explicit_decoded_payloads(value: str):
    """Decode only payloads carrying an explicit encoding marker.

    Scanning every token in a multi-megabyte report as base64 is both slow and
    prone to false positives.  Egress only needs to recognize a user/model
    response that labels its encoded payload, so keep this path bounded.
    """

    for match in islice(_ENCODED_PAYLOAD.finditer(value), 8):
        token = match.group(1)
        payload: bytes | None = None
        if re.fullmatch(r"(?:[0-9a-f]{2}){6,}", token, re.IGNORECASE):
            try:
                payload = bytes.fromhex(token)
            except ValueError:
                payload = None
        else:
            padded = token + "=" * ((4 - len(token) % 4) % 4)
            try:
                payload = base64.b64decode(padded, validate=True)
            except (binascii.Error, ValueError, UnicodeEncodeError):
                payload = None
        if payload is not None:
            decoded = _printable_payload(payload)
            if decoded:
                yield decoded


def _output_variants(value: str, *, include_encoded: bool = True):
    """Yield a bounded set of cheap egress detection views.

    Unlike the ingress classifier this never performs recursive 64-variant
    expansion.  That keeps file-list/download endpoints predictable even for
    large generated artifacts, while still handling URL/HTML/JSON escapes,
    zero-width punctuation and common homoglyphs.
    """

    source = value[: _MAX_FILE_SCAN_BYTES]
    candidates = (
        source,
        normalize_text(source),
        unquote(source),
        html.unescape(source),
        _decode_unicode_escapes(source),
        source.translate(_CONFUSABLES),
        re.sub(r"<[^>]{0,512}>", " ", source),
        re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", source),
    )
    if include_encoded:
        candidates = (*candidates, *_explicit_decoded_payloads(source))
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_text(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            yield normalized


def scrub_output(
    value: str,
    *,
    internal_markers: tuple[str, ...] = (),
    probe_variants: bool = True,
) -> OutputDecision:
    """Return a safe final response without exposing the matched text.

    Matching is performed before any public text transformation.  The caller
    should persist/stream only ``decision.content`` and use the reason code
    solely in a private, content-free audit event.
    """

    if not isinstance(value, str) or not value.strip():
        return OutputDecision(POLICY_REFUSAL, True, "EMPTY_OUTPUT")

    # Use a bounded, egress-specific view set.  The ingress classifier also
    # recognizes business-intent wording (for example “tell me about model
    # assumptions”), which must not turn an otherwise safe research result
    # into a refusal.
    variants = tuple(_output_variants(value, include_encoded=probe_variants))
    if probe_variants and is_prompt_probe(value):
        # Keep ingress as a defense-in-depth check for short final responses,
        # but only after the egress-specific patterns have had a chance to
        # classify ordinary business language.
        ingress_only_markers = (
            "system prompt",
            "developer prompt",
            "hidden context",
            "chain of thought",
            "系统提示词",
            "开发者指令",
            "隐藏上下文",
            "思维链",
        )
        if any(marker in variant for variant in variants for marker in ingress_only_markers):
            return OutputDecision(POLICY_REFUSAL, True, "SYSTEM_INSTRUCTION")
    for normalized in variants:
        for reason_code, pattern in _LEAK_PATTERNS:
            if pattern.search(normalized):
                return OutputDecision(POLICY_REFUSAL, True, reason_code)
        for marker in internal_markers:
            normalized_marker = normalize_text(marker)
            if len(normalized_marker) >= 4 and normalized_marker in normalized:
                return OutputDecision(POLICY_REFUSAL, True, "DEPLOYMENT_MARKER")
    return OutputDecision(value, False, None)


def scan_output_file(
    path: Path,
    *,
    display_name: str | None = None,
    internal_markers: tuple[str, ...] = (),
) -> str | None:
    """Return a private reason code when an output file must stay hidden.

    Text-like artifacts are scanned in bounded chunks, including HTML comments
    and hidden elements because the raw source is inspected.  Binary formats
    are not parsed here; their names are still checked and their contents remain
    behind the existing file sandbox.  A read/stat failure is fail-closed for
    a newly generated output rather than exposing an unverified artifact.
    """

    name = display_name or path.name
    if _LEAK_NAME_PATTERN.search(name):
        return "OUTPUT_NAME_INTERNAL_MARKER"
    # A caller may present a friendly display label while the registered
    # workspace path still contains a runtime/model marker.  Check both
    # views; this is metadata-only and does not expose the path to the client.
    for marker in internal_markers:
        normalized_marker = normalize_text(marker)
        if len(normalized_marker) < 4:
            continue
        if normalized_marker in normalize_text(name) or normalized_marker in normalize_text(str(path)):
            return "OUTPUT_NAME_INTERNAL_MARKER"
    suffix = path.suffix.lower()
    if suffix not in _TEXT_SUFFIXES:
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size <= _MAX_FILE_SCAN_BYTES:
                raw = handle.read(_MAX_FILE_SCAN_BYTES + 1)
            else:
                head = handle.read(_MAX_FILE_SCAN_BYTES // 2)
                handle.seek(max(0, size - _MAX_FILE_SCAN_BYTES // 2))
                raw = head + b"\n" + handle.read(_MAX_FILE_SCAN_BYTES // 2)
    except (OSError, ValueError):
        return "OUTPUT_SCAN_FAILED"
    text = raw.decode("utf-8", errors="replace")
    # File endpoints may inspect multi-megabyte reports.  The bounded egress
    # views still catch URL/HTML/escape/homoglyph forms, while avoiding the
    # recursive ingress decoder on the event loop.
    decision = scrub_output(
        text,
        internal_markers=internal_markers,
        probe_variants=False,
    )
    return decision.reason_code if decision.blocked else None


__all__ = [
    "OUTPUT_POLICY_VERSION",
    "OutputDecision",
    "scan_output_file",
    "scrub_output",
]
