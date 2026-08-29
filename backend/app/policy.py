"""Small, deterministic ingress policy for the public research chat.

The Harness prompt is deliberately not the first line of defence.  Requests
which are obviously outside the product scope (or ask for runtime secrets)
are answered locally so they do not spend model tokens and never become part
of the model's conversation history.

This module intentionally has no network/LLM dependencies.  It is a bounded
heuristic gate, not a claim that arbitrary natural-language intent can be
classified perfectly.  The allow-list is deliberately conservative for a
new conversation, while short continuation turns are allowed only when the
conversation already has a successful project turn.
"""

from __future__ import annotations

import base64
import binascii
import html
from itertools import islice
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote


POLICY_VERSION = "scope-gate-v1.1"

# Keep this response short and stable.  In particular, do not mention which
# detector fired, the model/provider name, or any internal policy threshold.
POLICY_REFUSAL = (
    "我的技能树目前只点亮了地产项目研究：资料分析、市场/政策/产品研究、"
    "报告编写和成果整理。其他技能还在努力学习中，暂时还不会哦。"
    "请告诉我项目、区域、时间和目标，我马上开工！"
)

# The product is Chinese-first, but a copied prompt may use Traditional
# Chinese.  A small security-focused map is preferable to pulling a large
# language dependency into the request hot path; it covers the protected
# vocabulary and the common project nouns used by the web client.
_TRADITIONAL_SECURITY_MAP = str.maketrans(
    {
        "請": "请", "輸": "输", "顯": "显", "示": "示", "並": "并",
        "項": "项", "目": "目", "告": "告", "訴": "诉", "當": "当",
        "前": "前", "模": "模", "型": "型", "系": "系", "統": "统",
        "提": "提", "詞": "词", "開": "开", "發": "发", "者": "者",
        "指": "指", "令": "令", "隱": "隐", "藏": "藏", "內": "内",
        "部": "部", "規": "规", "則": "则", "訊": "讯", "息": "息",
        "技": "技", "能": "能", "工": "工", "具": "具", "列": "列",
        "出": "出", "所": "所", "有": "有", "現": "现", "使": "使",
        "用": "用", "麼": "么", "哪": "哪", "個": "个", "嗎": "吗",
        "這": "这", "份": "份", "資": "资", "料": "料", "檔": "档",
        "轉": "转", "譯": "译", "總": "总", "結": "结", "論": "论",
        "與": "与", "區": "区", "域": "域", "號": "号", "產": "产",
        "業": "业", "場": "场", "價": "价", "錢": "钱", "銷": "销",
        "售": "售", "風": "风", "險": "险", "報": "报", "告": "告",
        "驗": "验", "查": "查", "據": "据", "關": "关", "鍵": "键",
        "數": "数", "據": "据", "譜": "谱", "體": "体", "內": "内",
        "鑰": "钥", "運": "运", "環": "环", "後": "后", "應": "应",
        "軌": "轨", "跡": "迹", "洩": "泄", "祕": "秘", "碼": "码",
        "憑": "凭", "證": "证", "覽": "览", "載": "载", "錄": "录",
    }
)

PolicyAction = Literal["allow", "deny"]


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The only policy result needed by the HTTP layer.

    ``reason_code`` is for private audit logs.  It must not be copied into a
    customer-facing response because it would make the detector easier to
    probe.
    """

    action: PolicyAction
    intent: str
    reason_code: str
    policy_version: str = POLICY_VERSION

    @property
    def allowed(self) -> bool:
        return self.action == "allow"


def normalize_text(value: str) -> str:
    """Normalize common Unicode obfuscation without decoding user content."""

    normalized = unicodedata.normalize("NFKC", value).translate(
        _TRADITIONAL_SECURITY_MAP
    )
    # Common wording variant for “current” in model/runtime questions.
    normalized = normalized.replace("目前", "当前")
    # Format characters include zero-width spaces, bidi overrides and similar
    # controls commonly used to evade simple phrase matching.  Preserve line
    # breaks/tabs as ordinary whitespace so the detector remains bounded.
    # Treat format controls as a separator instead of silently joining the
    # surrounding words.  This catches ``what\u200bmodel`` as well as
    # ``sys\u200btem`` (the compact variant iterator still checks the latter
    # when a control was inserted inside a protected token).
    normalized = "".join(
        " " if unicodedata.category(character) == "Cf" else character
        for character in normalized
    )
    return re.sub(r"\s+", " ", normalized).strip().casefold()


# Probe patterns are phrase families rather than a list of single words.  A
# real-estate task can legitimately mention a "销售模型" or "规划系统"; those
# should not be rejected unless the surrounding language asks for internals.
_PROBE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Role-looking wrappers are untrusted user text, not a permission grant.
    # Reject them before project terms can make the turn look actionable.
    re.compile(
        r"(?:\[\s*(?:system|developer|assistant)\s*\]|"
        r"<\s*(?:system|developer|assistant)\s*>|"
        r"(?:begin|end)[\s_-]+(?:system|developer|assistant)|"
        r"(?:[\"']?role[\"']?\s*[:=]\s*[\"']?(?:system|developer|assistant)|"
        r"<\s*role\s*>\s*(?:system|developer|assistant)\s*<\s*/\s*role\s*>)|"
        r"(?:you\s+are|你现在是|现在切换为).{0,20}"
        r"(?:system|developer|系统|开发者)|"
        r"(?:system|developer)\s*[:：].{0,48}"
        r"(?:reveal|show|print|ignore|输出|显示|列出|告诉|提示|指令|规则))",
        re.IGNORECASE,
    ),
    # Direct protected-object mentions are high signal even without a verb.
    re.compile(
        r"(?:system[\s_-]*(?:prompt|message|instructions?|rules?|setup|directive)|"
        r"developer[\s_-]*(?:prompt|message|instructions?|rules?)|"
        r"hidden[\s_-]*(?:prompt|instructions?|context|rules?|config)|"
        r"internal[\s_-]*(?:prompt|instructions?|context|reasoning|rules?)|"
        r"private[\s_-]*(?:prompt|instructions?|context)|"
        r"chain[\s_-]*of[\s_-]*thought|\bcot\b|"
        # Generic “system rules/config” can be business material (sales
        # system, internal-control rules).  Keep only explicit assistant
        # prompt/context/reasoning nouns in the unconditional family; the
        # exfiltration combinations below still catch “显示系统规则”.
        r"系统(?:提示词|隐藏提示词)|开发者(?:提示词|指令|提示)|"
        r"隐藏(?:提示|上下文|规则|配置)|内部(?:提示词|上下文|推理)|思维链)"
    ),
    # Chinese action + an owned/internal object.  “总结这份文件” and
    # “请列出项目供应商” intentionally do not match this family.
    re.compile(
        r"(?:输出|列出|显示|展示|告诉我|打印|复述|原样|逐字|完整|泄露|透露|"
        r"导出|翻译|总结|解码|编码).{0,36}"
        r"(?:你的|本助手|当前(?:使用)?|开发者|隐藏|内部|后台|运行时).{0,20}"
        r"(?:提示|指令|规则|上下文|消息|推理|技能|工具|能力|模型|密钥|令牌)"
    ),
    re.compile(
        r"(?:你的|本助手|当前(?:使用)?|开发者|隐藏|内部|后台|运行时).{0,20}"
        r"(?:提示|指令|规则|上下文|消息|推理|技能|工具|能力|模型|密钥|令牌).{0,36}"
        r"(?:输出|列出|显示|展示|告诉我|打印|复述|原样|逐字|完整|泄露|透露|导出|翻译|总结|解码|编码)"
    ),
    # Inventory questions require ownership/availability, not a bare mention
    # of a business “tool”, “skill”, or “supplier”.
    re.compile(
        r"(?:列出|显示|展示|告诉我|有哪些|有什么|枚举).{0,24}"
        r"(?:你的|本助手|所有|可用|已加载|当前|内部)?\s*"
        r"(?:技能|工具|插件|能力)(?:清单|列表|内容|定义|参数|源码|文件|路径)?"
    ),
    re.compile(
        r"(?:技能|工具|插件|能力)(?:清单|列表|内容|定义|参数|源码|文件|路径).{0,24}"
        r"(?:你的|本助手|所有|可用|已加载|当前|输出|列出|显示|展示)"
    ),
    # Cross-language inventory phrases must win over a legitimate project noun
    # later in the same sentence (“显示全部 tools 并分析项目”).
    re.compile(
        r"(?:列出|显示|展示|告诉我|枚举|list|show|display|enumerate|name|describe|"
        r"tell me|provide|give me).{0,48}"
        r"(?:所有|全部|你的|当前|可用|已加载|内部|all|your|current|available|"
        r"active|installed|loaded).{0,16}"
        r"(?:技能|工具|插件|能力|skill|skills|tool|tools|plugin|plugins|"
        r"capabilit(?:y|ies)|provider|providers|model|llm)"
    ),
    re.compile(
        r"(?:所有|全部|你的|当前|可用|已加载|内部|all|your|current|available|"
        r"active|installed|loaded).{0,16}"
        r"(?:技能|工具|插件|能力|skill|skills|tool|tools|plugin|plugins|"
        r"capabilit(?:y|ies)|provider|providers|model|llm).{0,48}"
        r"(?:列出|显示|展示|告诉我|枚举|list|show|display|enumerate|name|describe|"
        r"tell me|provide|give me|输出|打印|复述|原样|逐字|完整)"
    ),
    # A protected object with a current/owned qualifier is still protected
    # when a valid real-estate task is appended afterward.
    re.compile(
        r"(?:你的|本助手|当前(?:使用)?|正在使用的|运行中的|部署的|所有|全部|"
        r"your|current|active|deployed|underlying|all).{0,20}"
        r"(?:模型|大模型|语言模型|provider|模型服务商|模型供应商|model|llm).{0,24}"
        r"(?:名称|版本|参数|配置|是什么|哪家|which|what|show|tell|显示|告诉|列出|输出)"
    ),
    # Runtime/model questions require a relationship to the assistant.  A
    # project task asking which sales model to use remains outside these forms.
    re.compile(
        r"(?:你|本助手|当前系统|当前).{0,24}(?:使用|运行|部署|配置|加载).{0,20}"
        r"(?:什么|哪|哪个|哪家)?(?:模型|大模型|语言模型|llm|provider|供应商|运行时|版本|配置|环境变量|接口|端点)"
    ),
    re.compile(
        r"(?:你的|本助手当前的?|正在使用的|运行中的|部署的|当前使用的?).{0,16}"
        r"(?:模型|大模型|语言模型|llm|provider|供应商|运行时|版本).{0,20}"
        r"(?:名称|版本|参数|配置|是哪家|是什么|哪一个|叫什么)?"
    ),
    # English action/object families, with separators tolerated by the
    # variant iterator below.
    re.compile(
        r"(?:show|print|dump|reveal|quote|repeat|translate|encode|decode|"
        r"summari[sz]e|list|provide|give me|tell me|display|share|paste|"
        r"return|output).{0,64}"
        r"(?:system[\s_-]*(?:prompt|message|instructions?|rules?)|"
        r"developer[\s_-]*(?:prompt|message|instructions?|rules?)|"
        r"hidden[\s_-]*(?:prompt|instruction|context|rule)|"
        r"internal[\s_-]*(?:prompt|context|reasoning|rules?)|"
        r"private[\s_-]*(?:prompt|instruction|context)|"
        r"chain[\s_-]*of[\s_-]*thought|"
        r"skill[\s_-]*(?:file|source|content|instruction|manifest|path|list)|"
        r"tool[\s_-]*(?:list|schema|definitions?|manifest)|"
        r"(?:your|the|current|underlying|deployed|active)[\s_-]+(?:model|llm)"
        r"(?:[\s_-]*(?:name|version|config(?:uration)?|parameters?))?|"
        r"(?:api[\s_-]*key|secret|token|cookie|environment[\s_-]*variable|env[\s_-]*var))"
    ),
    re.compile(
        r"(?:system[\s_-]*(?:prompt|message|instructions?|rules?)|"
        r"developer[\s_-]*(?:prompt|message|instructions?|rules?)|"
        r"hidden[\s_-]*(?:prompt|instruction|context|rule)|"
        r"internal[\s_-]*(?:prompt|context|reasoning|rules?)|"
        r"private[\s_-]*(?:prompt|instruction|context)|"
        r"chain[\s_-]*of[\s_-]*thought|"
        r"skill[\s_-]*(?:file|source|content|instruction|manifest|path|list)|"
        r"tool[\s_-]*(?:list|schema|definitions?|manifest)|"
        r"(?:your|the|current|underlying|deployed|active)[\s_-]+(?:model|llm)"
        r"(?:[\s_-]*(?:name|version|config(?:uration)?|parameters?))?|"
        r"(?:api[\s_-]*key|secret|token|cookie|environment[\s_-]*variable|env[\s_-]*var)).{0,64}"
        r"(?:show|print|dump|reveal|quote|repeat|translate|encode|decode|"
        r"summari[sz]e|list|provide|give me|tell me|display|share|paste|return|output)"
    ),
    re.compile(
        r"\b(?:list|show|display|enumerate|name|describe|tell me about|what are|"
        r"which are|what do you have)\b.{0,28}\b(?:your|all|available|active|"
        r"installed|loaded|current)?[\s_-]*(?:skills?|tools?|plugins?|"
        r"capabilities?|providers?|harness(?:es)?)\b"
    ),
    re.compile(
        r"\b(?:what|which)\b.{0,24}\b(?:tools?|skills?|plugins?|capabilities?)\b"
        r".{0,24}\b(?:do|does|can)\b.{0,12}\b(?:you|this assistant)\b"
    ),
    re.compile(
        r"\b(?:what|which|tell me|do you know)\b.{0,48}\b"
        r"(?:your|current|underlying|active|deployed|configured|loaded|available)\b.{0,24}\b"
        r"(?:model|llm|provider|runtime|harness|version|configuration|config)\b"
    ),
    re.compile(
        r"(?<![a-z])(?:what|which)[\s_-]*(?:model|llm|provider)[\s_-]*"
        r"(?:are|is)[\s_-]*(?:you|this)[\s_-]*(?:using|running|configured|based)"
        r"(?![a-z])"
    ),
    re.compile(
        r"(?<![a-z])(?:what|which)[\s_-]*(?:model|llm|provider)[\s_-]*"
        r"(?:do|did)[\s_-]*you[\s_-]*(?:use|run)(?![a-z])"
    ),
    re.compile(
        r"\b(?:what|where|show|give|tell|print|reveal|list|dump|cat|read)\b.{0,56}"
        r"(?:api[\s_-]*key|secret|token|cookie|environment[\s_-]*variables?|env[\s_-]*vars?|"
        r"\.env|/etc/|/passwd|private[\s_-]*key|configuration|config)"
    ),
    re.compile(
        r"\b(?:ignore|bypass|disregard|override|forget|jailbreak|skip|remove)\b"
        r".{0,72}(?:\b(?:previous|prior|above|system|developer|hidden|internal|safety|"
        r"instructions?|rules?|policy|prompt|guardrails?)\b|之前|上面|先前|系统|开发者|规则|提示|指令)"
    ),
    re.compile(
        r"\b(?:how\s+(?:are|were)\s+you|what\s+were\s+you|which\s+rules?)\b"
        r".{0,48}\b(?:instructed|programmed|configured|told|given|following|using|trained)\b"
    ),
    # Second-person policy/capability questions are probes even when a
    # project task is appended later in the same turn.
    re.compile(
        r"(?:what|which|tell\s+me|provide|can\s+you|please\s+tell\s+me|"
        r"什么|哪些|告诉我|能否).{0,72}"
        r"(?:rules?|policies?|instructions?|guardrails?|functions?|capabilities?|"
        r"configuration|system\s+info|model\s+powers|vendor\s+runs|backend\s+version|"
        r"runtime\s+environment|instruction\s+hierarchy|latent\s+context|"
        r"规则|政策|指令|护栏|函数|能力|配置|系统信息|模型|服务商|后端版本|运行时环境|"
        r"指令层级|潜在上下文).{0,48}"
        r"(?:you|your|this\s+assistant|do\s+you|govern\s+you|guide\s+you|"
        r"powers\s+this\s+assistant|runs\s+you|follow|使用|运行|配置|本助手|你)"
    ),
    re.compile(
        r"(?:leak|disclose|reveal|export|show|print|share|透露|泄露|显示|输出|导出|"
        r"do\s+not\s+follow|don't\s+follow|not\s+follow|不要遵循|别遵循).{0,96}"
        r"(?:prompt|system\s+info|rules?|policies?|instructions?|guardrails?|"
        r"private\s+key|api\s+key|提示词|系统信息|规则|政策|指令|护栏|私钥|密钥)",
        re.IGNORECASE,
    ),
    # Assistant-owned runtime questions are protected even when the wording
    # is reversed (“your guardrails”, “provide your configuration”) or a
    # project task is appended afterward.
    re.compile(
        r"(?:your|you\s+(?:use|follow|run|are)|this\s+assistant(?:'s)?|"
        r"the\s+assistant(?:'s)?|current|underlying|active|deployed|configured|loaded|"
        r"你的|本助手(?:的)?|当前(?:使用|运行|部署)?的?|正在使用的|运行中的|部署的)\s*"
        r"(?:rules?|policies?|instructions?|guardrails?|functions?|capabilities?|"
        r"configuration|system\s+info|model|llm|provider|vendor|runtime|harness|"
        r"version|skills?|tools?|plugins?|rules|规则|政策|指令|护栏|函数|能力|配置|"
        r"系统信息|模型|大模型|服务商|供应商|运行时|版本|技能|工具|插件)"
    ),
    re.compile(
        r"(?:what|which|tell\s+me|provide|can\s+you|what\s+is|which\s+are|"
        r"请问|告诉我|能否|显示|列出|提供).{0,56}"
        r"(?:instruction\s+hierarchy|latent\s+context|reasoning\s+trace|"
        r"backend\s+version|runtime\s+environment|system\s+info|"
        r"指令层级|潜在上下文|推理(?:过程|轨迹)|后端版本|运行时环境|系统信息)"
        r"(?:.{0,24}(?:you|this\s+assistant|is\s+this|are\s+you|do\s+you|"
        r"本助手|你|当前))?"
    ),
    re.compile(
        r"(?:上面|之前|前面|刚才).{0,20}(?:原样|完整|逐字|复述|重复).{0,20}"
        r"(?:输出|打印|发送|告诉|贴出)?"
    ),
)

# Mixed-language probes need their own family.  A valid project noun later in
# the same turn (for example, “并分析项目”) must not downgrade a request for a
# protected inventory/secret.  These patterns intentionally pair an extraction
# verb with a sensitive object; a normal task such as “请调用搜索工具核验
# 市场数据” has neither an inventory verb nor a protected object and remains
# eligible for the project allow-list.
_HIGH_RISK_COMBINATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Extraction verbs + runtime-owned objects are checked independently of
    # the project allow-list.  This closes the common “显示……并分析地产项目”
    # bypass while leaving a business interpretation such as “分析系统提示的
    # 业务含义” available when no raw-extraction verb is present.
    re.compile(
        r"(?:输出|打印|显示|展示|列出|告诉我|提供|给我|导出|读取|查看|打开|复述|原样|逐字|"
        r"揭示|泄露|发送|贴出|翻译|解码|说明|描述|解释|总结|show|print|display|list|tell\s*me|"
        r"give\s*me|provide|dump|reveal|read|view|open|quote|repeat|translate|decode|"
        r"explain|describe|output|share|paste|return).{0,96}"
        r"(?:系统(?:提示|指令|消息|规则|设定|配置|环境变量)|内部(?:提示|指令|规则|消息|配置)|"
        r"隐藏(?:提示|上下文|规则|策略|配置)|开发者(?:提示|指令|消息|规则)|"
        r"(?:推理(?:过程|轨迹)|运行时(?:环境|配置)|后端版本|私钥)|"
        r"(?:模型|大模型|语言模型)(?:名称|版本|参数|配置)?|服务商(?:名称|版本|配置)?|"
        r"(?:api[\s_-]*(?:key|密钥)|密钥|令牌|环境变量|密钥文件)|"
        r"(?:技能|工具|插件|能力)(?:树|清单|列表|内容|定义|参数|源码|文件|路径)?|"
        r"system[\s_-]*(?:prompt|message|instructions?|rules?|setup|configuration)|"
        r"developer[\s_-]*(?:prompt|message|instructions?|rules?)|"
        r"hidden[\s_-]*(?:prompt|context|instructions?|rules?|policy|config)|"
        r"internal[\s_-]*(?:prompt|context|instructions?|reasoning|rules?|config)|"
        r"(?:your|current|underlying|active|deployed|configured)[\s_-]+"
        r"(?:model|llm|provider|runtime|harness|skill(?:s)?|tool(?:s)?|plugin(?:s)?)|"
        r"(?:api[\s_-]*key|access[\s_-]*token|client[\s_-]*secret|private[\s_-]*key|"
        r"environment[\s_-]*(?:variables?|vars?)|\.env|/etc/|/passwd|secret[\s_-]*(?:file|config)))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:系统(?:提示|指令|消息|规则|设定|配置|环境变量)|内部(?:提示|指令|规则|消息|配置)|"
        r"隐藏(?:提示|上下文|规则|策略|配置)|开发者(?:提示|指令|消息|规则)|"
        r"(?:推理(?:过程|轨迹)|运行时(?:环境|配置)|后端版本|私钥)|"
        r"(?:模型|大模型|语言模型)(?:名称|版本|参数|配置)?|服务商(?:名称|版本|配置)?|"
        r"(?:api[\s_-]*(?:key|密钥)|密钥|令牌|环境变量|密钥文件)|"
        r"(?:技能|工具|插件|能力)(?:树|清单|列表|内容|定义|参数|源码|文件|路径)?|"
        r"system[\s_-]*(?:prompt|message|instructions?|rules?|setup|configuration)|"
        r"developer[\s_-]*(?:prompt|message|instructions?|rules?)|"
        r"hidden[\s_-]*(?:prompt|context|instructions?|rules?|policy|config)|"
        r"internal[\s_-]*(?:prompt|context|instructions?|reasoning|rules?|config)|"
        r"(?:your|current|underlying|active|deployed|configured)[\s_-]+"
        r"(?:model|llm|provider|runtime|harness|skill(?:s)?|tool(?:s)?|plugin(?:s)?)|"
        r"(?:api[\s_-]*key|access[\s_-]*token|client[\s_-]*secret|private[\s_-]*key|"
        r"environment[\s_-]*(?:variables?|vars?)|\.env|/etc/|/passwd|secret[\s_-]*(?:file|config))"
        r").{0,96}(?:输出|打印|显示|展示|列出|告诉我|提供|给我|导出|读取|查看|打开|复述|原样|逐字|"
        r"揭示|泄露|发送|贴出|翻译|解码|说明|描述|解释|总结|show|print|display|list|tell\s*me|"
        r"give\s*me|provide|dump|reveal|read|view|open|quote|repeat|translate|decode|"
        r"explain|describe|output|share|paste|return)",
        re.IGNORECASE,
    ),
    # Broader runtime metadata synonyms (prompt hierarchy, guardrails, MCP,
    # deployment details, etc.) use the same extraction-verb rule.  Keeping
    # this separate from ordinary “model/data” vocabulary avoids blocking
    # legitimate forecasting and supplier analysis.
    re.compile(
        r"(?:输出|打印|显示|展示|列出|告诉我|提供|给我|导出|复述|原样|揭示|泄露|"
        r"发送|贴出|show|print|display|list|tell\s+me|give\s+me|provide|"
        r"dump|reveal|output|share|paste|return).{0,96}"
        r"(?:instruction[\s_-]*(?:hierarchy|system|set)?|hidden[\s_-]*policy|"
        r"latent[\s_-]*context|reasoning[\s_-]*(?:trace|process)|"
        r"prompt[\s_-]*(?:template|format)|meta[\s_-]*prompt|"
        r"guardrail[\s_-]*rules?|available[\s_-]*functions?|"
        r"capabilit(?:y|ies)[\s_-]*(?:manifest|list)|function[\s_-]*definitions?|"
        r"mcp[\s_-]*(?:server|service)|runtime[\s_-]*environment|"
        r"backend[\s_-]*version|checkpoint|deployment[\s_-]*(?:info|details?|config)?|"
        r"指令(?:层级|体系)|隐藏策略|潜在上下文|推理(?:轨迹|过程)|提示模板|元提示|"
        r"护栏规则|可用函数|能力(?:清单|列表)|函数定义|mcp(?:服务器|服务)|"
        r"运行时环境|后端版本|检查点|部署(?:信息|详情|配置)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:instruction[\s_-]*(?:hierarchy|system|set)?|hidden[\s_-]*policy|"
        r"latent[\s_-]*context|reasoning[\s_-]*(?:trace|process)|"
        r"prompt[\s_-]*(?:template|format)|meta[\s_-]*prompt|"
        r"guardrail[\s_-]*rules?|available[\s_-]*functions?|"
        r"capabilit(?:y|ies)[\s_-]*(?:manifest|list)|function[\s_-]*definitions?|"
        r"mcp[\s_-]*(?:server|service)|runtime[\s_-]*environment|"
        r"backend[\s_-]*version|checkpoint|deployment[\s_-]*(?:info|details?|config)?|"
        r"指令(?:层级|体系)|隐藏策略|潜在上下文|推理(?:轨迹|过程)|提示模板|元提示|"
        r"护栏规则|可用函数|能力(?:清单|列表)|函数定义|mcp(?:服务器|服务)|"
        r"运行时环境|后端版本|检查点|部署(?:信息|详情|配置)?).{0,96}"
        r"(?:输出|打印|显示|展示|列出|告诉我|提供|给我|导出|复述|原样|揭示|泄露|"
        r"发送|贴出|show|print|display|list|tell\s+me|give\s+me|provide|"
        r"dump|reveal|output|share|paste|return)",
        re.IGNORECASE,
    ),
    # Generic “system/internal rule/config” is ambiguous in a research
    # document, so only an explicit extraction verb makes it a probe.  This
    # keeps “分析规划系统规则对项目的影响” and “总结系统配置文件” usable
    # while denying “显示系统规则并分析项目”.
    re.compile(
        r"(?:输出|打印|显示|展示|列出|告诉我|提供|给我|导出|复述|原样|"
        r"揭示|泄露|透露|读取|查看|打开|翻译|解码|说明|描述|解释|总结|"
        r"show|print|display|list|tell\s+me|give\s+me|provide|dump|"
        r"reveal|read|view|open|translate|decode|explain|describe|summarize|"
        r"output|share|paste|return).{0,64}"
        r"(?:系统(?:规则|消息|设定|配置)|内部(?:规则|配置|消息)|"
        r"运行时(?:规则|配置|环境)|system[\s_-]*(?:rules?|message|setup|configuration)|"
        r"internal[\s_-]*(?:rules?|config(?:uration)?|message)|runtime[\s_-]*config(?:uration)?|"
        r"后台(?:配置|信息|规则|提示|指令|模型|技能|工具)?|"
        r"服务端(?:配置|信息|规则|版本)?|服务器(?:配置|信息|规则|版本)?|"
        r"系统信息|部署(?:信息|详情|配置)?|接口(?:信息|配置)?|版本信息|助手设定)",
        re.IGNORECASE,
    ),
    # Target-first ordering for ambiguous runtime metadata (for example,
    # “后台配置……输出”) must also win over a project noun later in a turn.
    re.compile(
        r"(?:系统(?:规则|消息|设定|配置)|内部(?:规则|配置|消息)|运行时(?:规则|配置|环境)|"
        r"后台(?:配置|信息|规则|提示|指令|模型|技能|工具)?|"
        r"服务端(?:配置|信息|规则|版本)?|服务器(?:配置|信息|规则|版本)?|"
        r"系统信息|部署(?:信息|详情|配置)?|接口(?:信息|配置)?|版本信息|助手设定|"
        r"system[\s_-]*(?:rules?|message|setup|configuration)|"
        r"backend[\s_-]*(?:config(?:uration)?|info|rules?|version)|"
        r"server[\s_-]*(?:config(?:uration)?|info|rules?|version)|"
        r"deployment[\s_-]*(?:info|details?|config(?:uration)?)|"
        r"interface[\s_-]*(?:info|config(?:uration)?)|version[\s_-]*info).{0,96}"
        r"(?:输出|打印|显示|展示|列出|告诉我|提供|给我|导出|复述|原样|"
        r"揭示|泄露|透露|读取|查看|打开|翻译|解码|说明|描述|解释|总结|"
        r"show|print|display|list|tell\s+me|give\s+me|provide|dump|"
        r"reveal|read|view|open|translate|decode|explain|describe|summarize|"
        r"output|share|paste|return)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:输出|打印|显示|展示|列出|告诉我|提供|给我|导出|读取|查看|打开|复述|原样|"
        r"揭示|泄露|发送|贴出|show|print|display|list|tell\s+me|give\s+me|"
        r"provide|dump|reveal|read|cat|output|share|paste|return).{0,80}"
        r"(?:skill(?:s)?[\s_-]*(?:content|file|source|instruction|manifest|list)?|"
        r"技能(?:树|清单|内容|指令|源码|文件|路径)?|"
        r"plugin(?:s)?[\s_-]*(?:content|file|source|list)?|"
        r"tool(?:s)?[\s_-]*(?:list|schema|definition|manifest|content)?|"
        r"工具(?:清单|列表|内容|定义|参数|源码|文件|路径)?|"
        r"api[\s_-]*key|secret|token|cookie|environment[\s_-]*variables?|"
        r"env[\s_-]*vars?|\.env|/etc/(?:passwd|shadow)|/passwd|"
        r"id[\s_-]?rsa|private[\s_-]*key|"
        r"(?:your|current|underlying|active|deployed|configured|当前|你的|本助手)"
        r".{0,12}(?:model|llm|provider|runtime|harness|模型|供应商|运行时))",
        re.IGNORECASE,
    ),
    # Target-first ordering (“API key ... 输出”, “skill content ... show”) is
    # common in pasted prompt-injection templates, so check the reverse order
    # as well.
    re.compile(
        r"(?:skill(?:s)?[\s_-]*(?:content|file|source|instruction|manifest|list)|"
        r"技能(?:树|清单|内容|指令|源码|文件|路径)?|"
        r"tool(?:s)?[\s_-]*(?:list|schema|definition|manifest|content)?|"
        r"工具(?:清单|列表|内容|定义|参数|源码|文件|路径)?|"
        r"api[\s_-]*key|secret|token|cookie|environment[\s_-]*variables?|"
        r"env[\s_-]*vars?|\.env|/etc/(?:passwd|shadow)|/passwd|"
        r"id[\s_-]?rsa|private[\s_-]*key|"
        r"(?:your|current|underlying|active|deployed|configured|当前|你的|本助手)"
        r".{0,12}(?:model|llm|provider|runtime|harness|模型|供应商|运行时)).{0,80}"
        r"(?:输出|打印|显示|展示|列出|告诉我|提供|给我|导出|读取|查看|打开|复述|原样|"
        r"揭示|泄露|发送|贴出|show|print|display|list|tell\s+me|give\s+me|"
        r"provide|dump|reveal|read|cat|output|share|paste|return)",
        re.IGNORECASE,
    ),
    # Prompt-injection/bypass language is high risk even when embedded next to
    # Chinese project text.  Avoid ``\b`` at the mixed-script boundary so
    # “请研究ignore previous instructions” is not missed.
    re.compile(
        r"(?:ignore|bypass|disregard|override|forget|jailbreak|skip|remove|"
        r"prompt[\s_-]*injection|忽略|绕过|无视|覆盖|跳过|删除).{0,80}"
        r"(?:previous|prior|above|below|system|developer|hidden|internal|"
        r"safety|instructions?|rules?|policy|prompt|guardrails?|之前|上面|"
        r"先前|系统|开发者|隐藏|内部|安全|规则|提示|指令)",
        re.IGNORECASE,
    ),
    # Sensitive filesystem/secret paths are never a project research input,
    # even when wrapped in a seemingly legitimate “研究/分析” request.
    re.compile(
        r"(?:读取|查看|打开|提取|解析|打印|输出|发送|导出|read|open|cat|dump|"
        r"extract|parse|print|show|output).{0,80}"
        r"(?:/etc/(?:passwd|shadow)|/passwd|id[\s_-]?rsa|\.env|"
        r"private[\s_-]*(?:key|config)|secret[\s_-]*(?:file|config))",
        re.IGNORECASE,
    ),
)


# Domain vocabulary is intentionally broad enough to cover the skills shipped
# with this project, but paired with an action/question signal below so a
# casual sentence containing only “地产” does not reach the Harness.
_DOMAIN_TERMS = frozenset(
    {
        "地产",
        "房地产",
        "楼盘",
        "住宅",
        "商业",
        "土地",
        "地块",
        "城市",
        "板块",
        "区域",
        "项目",
        "市场",
        "竞品",
        "客群",
        "客户",
        "产品",
        "户型",
        "面积",
        "价格",
        "单价",
        "货值",
        "成本",
        "去化",
        "销售",
        "首开",
        "推售",
        "定位",
        "营销",
        "品牌",
        "社群",
        "运营",
        "招商",
        "投资",
        "测算",
        "预算",
        "现金流",
        "需求",
        "风险",
        "规划",
        "政策",
        "容积率",
        "建面",
        "报告",
        "方案",
        "模型",
        "材料",
        "关键数据",
        "数据",
        "供应商",
        "资料",
        "文档",
        "文件",
        "表格",
        "图片",
        "pdf",
        "html",
        "markdown",
        "微信",
        "公众号",
        "传播",
        "海报",
        "real estate",
        "property",
        "housing",
        "project",
        "market",
        "competitor",
        "product",
        "pricing",
        "sales",
        "land",
        "planning",
        "report",
        "model",
        "forecast",
        "forecasting",
        "material",
        "materials",
        "key data",
        "data",
        "supplier",
        "suppliers",
        "vendor",
        "vendors",
        "document",
        "file",
        "strategy",
        "marketing",
        "customer",
        "community",
    }
)

_ACTION_TERMS = frozenset(
    {
        "请",
        "帮我",
        "分析",
        "研究",
        "整理",
        "生成",
        "查找",
        "检索",
        "测算",
        "比较",
        "提取",
        "读取",
        "写",
        "制作",
        "规划",
        "定位",
        "设计",
        "评估",
        "影响",
        "预测",
        "判断",
        "建议",
        "制定",
        "优化",
        "推荐",
        "撰写",
        "编制",
        "更新",
        "复盘",
        "核验",
        "核查",
        "审阅",
        "汇报",
        "导出",
        "转换",
        "总结",
        "输出",
        "翻译",
        "怎么",
        "如何",
        "哪些",
        "多少",
        "为何",
        "为什么",
        "请问",
        "help",
        "analyze",
        "analyse",
        "research",
        "整理",
        "create",
        "generate",
        "search",
        "extract",
        "read",
        "write",
        "make",
        "compare",
        "calculate",
        "evaluate",
        "review",
        "impact",
        "forecast",
        "recommend",
        "suggest",
        "identify",
        "update",
        "draft",
        "export",
        "convert",
        "summarize",
        "translate",
        "verify",
        "validate",
        "check",
        "material",
        "materials",
        "data",
        "output",
        "what",
        "how",
        "which",
    }
)

_CONTINUATION_TERMS = frozenset(
    {
        "继续",
        "接着",
        "按上次",
        "基于上次",
        "补充",
        "再算一遍",
        "重算",
        "调整",
        "修改",
        "更新",
        "导出",
        "重做",
        "continue",
        "same project",
        "based on the previous",
        "revise",
        "update",
        "export",
    }
)

_CONTINUATION_PROJECT_TERMS = frozenset(
    {
        "项目",
        "地产",
        "报告",
        "方案",
        "研究",
        "分析",
        "结论",
        "数据",
        "关键数据",
        "材料",
        "市场",
        "竞品",
        "价格",
        "去化",
        "product",
        "project",
        "report",
        "research",
        "analysis",
        "result",
        "plan",
        "data",
        "output",
        "material",
        "materials",
        "verification",
        "check",
    }
)

_CASUAL_EXACT = frozenset(
    {
        "你好",
        "您好",
        "嗨",
        "hello",
        "hi",
        "hey",
        "早上好",
        "晚上好",
        "谢谢",
        "感谢",
        "哈哈",
        "在吗",
        "你好吗",
        "讲个笑话",
        "天气",
        "陪我聊天",
        "聊聊天",
        "随便聊几句",
        "我想聊天",
        "继续闲聊",
        "继续聊天",
        "无聊",
        "随便聊",
        "test",
        "测试一下",
        "who are you",
        "how are you",
        "hey there",
        "can we chat",
        "can we chat?",
        "how is your day",
        "thanks for your help",
        "tell me about yourself",
    }
)

# High-signal leisure/chat phrases.  These are intentionally kept separate
# from the domain vocabulary: a sentence such as “分析项目天气风险” can still
# be a legitimate project question, while “给我讲个笑话” is never useful to
# the research runtime.  Ambiguous text is allowed below so existing project
# workflows that use terse/internal wording are not broken by the gate.
_OFF_TOPIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:讲|说|写|编).{0,12}(?:笑话|故事|段子|诗|歌词)"),
    re.compile(r"(?:陪我|和我|跟我|我想).{0,16}(?:聊天|闲聊|唠嗑)"),
    re.compile(r"(?:继续|接着|continue|keep).{0,16}(?:聊天|闲聊|唠嗑|chat(?:ting)?|talk(?:ing)?)"),
    re.compile(r"(?:revise|export|continue|write|tell).{0,16}(?:joke|poem|song|story|聊天|笑话|故事|诗|歌词)"),
    re.compile(r"(?:你喜欢什么|你的爱好|你会不会爱|谈恋爱|八卦一下)"),
    re.compile(r"(?:天气预报|星座|塔罗|彩票|游戏攻略|电影推荐|音乐推荐|菜谱|食谱)"),
    re.compile(r"^(?:今天|现在)?天气(?:怎么样|如何|咋样|好吗|预报|不错|很好|真好)?$"),
    re.compile(r"^(?:你能做什么|你会什么|有什么功能|支持哪些功能|能帮我做什么|你的能力是什么)[呀啊吗呢？?！!。,. ]*$"),
    re.compile(r"^(?:你好|您好|嗨|hello|hi|hey)[呀啊！!。,. ]*$"),
    re.compile(r"^(?:你好|您好|嗨|hello|hi|hey)[呀啊！!，,。 ]*(?:最近怎么样|你好吗|在吗)?$"),
    re.compile(r"^(?:谢谢|感谢)(你|啦|哦|哈)?[呀啊！!。,. ]*$"),
    re.compile(r"^(?:再见|拜拜|晚安|早安)[呀啊啦哦！!。,. ]*$"),
    re.compile(r"^(?:写代码|帮我写代码|翻译一下|做个翻译|讲个故事|说个段子)[呀啊吗呢？?！!。,. ]*$"),
    re.compile(r"(?:tell me a joke|write a poem|write a song|small talk|chat with me|"
               r"favorite movie|favorite music|weather forecast|recipe|horoscope|"
               r"how is your day|can we chat|hey there|thanks for your help|"
               r"tell me about yourself)"),
)

# These phrases are unambiguously leisure/chat requests.  They stay blocked
# even if an attacker appends a project noun and an action (“讲个笑话，顺便
# 分析项目”), while softer words such as “天气” can still be used in a
# legitimate site-risk analysis when paired with a clear project task.
_HARD_OFF_TOPIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:讲|说|写|编).{0,20}(?:笑话|故事|段子|诗|歌词)"),
    re.compile(r"(?:陪我|和我|跟我|我想).{0,20}(?:聊天|闲聊|唠嗑)"),
    re.compile(
        r"(?:tell\s+me\s+a\s+joke|write\s+(?:a\s+)?(?:poem|song|story)|"
        r"small\s+talk|chat\s+with\s+me|favorite\s+(?:movie|music)|"
        r"recipe|horoscope|tarot|lottery|game\s+guide|movie\s+recommendation|"
        r"music\s+recommendation)"
    ),
    re.compile(r"(?:星座|塔罗|彩票|游戏攻略|电影推荐|音乐推荐|菜谱|食谱)"),
)

# Explicit workflow shorthand is useful for the existing stateless web API:
# callers often send “第一轮问题”, “取消后继续” or “start during reset” after
# the UI has already established the project.  These phrases are not a broad
# allow-list for arbitrary chat; they are only accepted when no casual/probe
# pattern matched and (for attachment turns) are paired with a file action.
_TASK_WORKFLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Ordinal turns are emitted by the existing web client (for example,
    # “第一轮问题” or “第二条”).  Keep this narrow: a bare “继续” is only
    # accepted through the trusted ``has_context`` continuation path below.
    re.compile(r"(?:并发)?第[一二三四五六七八九十百0-9]+(?:轮|条)(?:问题|任务|请求|研究|执行)?"),
    re.compile(
        r"(?:上一轮|这轮|本轮|下一轮).{0,24}"
        r"(?:任务|问题|研究|执行|取消|继续|重试|刷新|重启|恢复)"
    ),
    re.compile(
        r"(?:取消|重试|重启|刷新|恢复|并发).{0,24}"
        r"(?:后|期间|中的?|任务|本轮|下一轮|继续|执行|队列|成功|失败)"
    ),
    re.compile(
        r"(?:任务|队列).{0,24}"
        r"(?:取消|重试|重启|刷新|恢复|继续|执行|状态|失败|完成)"
    ),
    re.compile(r"任务(?:队列|状态|失败|完成|执行)"),
    re.compile(
        r"(?:这一轮|这轮|本轮)?(?:需要|必须|应当).{0,20}"
        r"(?:执行|完成|恢复|重试|进入队列)"
    ),
    re.compile(
        r"(?:刷新|重启|取消|恢复).{0,24}"
        r"(?:期间|之前|之后|后|前).{0,24}(?:继续|执行|任务|队列)"
    ),
    re.compile(
        r"(?:start|restart|resume|cancel|retry|reset|refresh).{0,40}"
        r"(?:run|task|reset|queue|turn|request|execution|after|during|next|previous)"
    ),
    re.compile(
        r"(?:run|task|queue|turn|request|execution).{0,40}"
        r"(?:start|restart|resume|cancel|retry|reset|refresh|continue)"
    ),
)

# Attachment presence alone is not proof that a user wants project work; a
# short explicit verb (for example, “analyze” or “extract”) is sufficient
# because the attachment is the implicit object.
_FILE_OBJECT_TERMS = frozenset(
    {
        "附件",
        "原附件",
        "资料",
        "材料",
        "文档",
        "文件",
        "图片",
        "图像",
        "表格",
        "file",
        "files",
        "document",
        "documents",
        "attachment",
        "attachments",
        "material",
        "materials",
        "spreadsheet",
        "image",
        "images",
        "pdf",
        "input",
        "inputs",
    }
)

_FILE_ACTION_VERBS = frozenset(
    {
        "读取",
        "提取",
        "解析",
        "查看",
        "看看",
        "打开",
        "识别",
        "处理",
        "整理",
        "分析",
        "解读",
        "解释",
        "概括",
        "审阅",
        "核验",
        "转换",
        "总结",
        "翻译",
        "导出",
        "比较",
        "生成",
        "摘要",
        "转成",
        "extract",
        "parse",
        "read",
        "open",
        "inspect",
        "process",
        "review",
        "analyze",
        "analyse",
        "explain",
        "summarize",
        "summarise",
        "convert",
        "export",
        "compare",
        "generate",
        "translate",
        "summary",
        "summaries",
        "look",
        "view",
    }
)

_CONFUSABLES = str.maketrans(
    {
        # Common Cyrillic/Greek look-alikes used in “ѕystem рrompt” style
        # evasion.  This is intentionally a small map, not a transliterator.
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "ѕ": "s",
        "х": "x",
        "у": "y",
        "м": "m",
        "д": "d",
        "н": "h",
        "т": "t",
        "к": "k",
        "в": "b",
        "г": "r",
        "л": "l",
        "і": "i",
        "ј": "j",
        "ӏ": "l",
        "ԁ": "d",
        "ԛ": "q",
        "ԝ": "w",
        "ԍ": "g",
        "ҝ": "k",
        "һ": "h",
        "ү": "y",
        "қ": "k",
        "ң": "n",
        "օ": "o",
        "Α": "a",
        "Β": "b",
        "Ε": "e",
        "Ι": "i",
        "Κ": "k",
        "Μ": "m",
        "Ν": "n",
        "Ο": "o",
        "Ρ": "p",
        "Τ": "t",
        "Χ": "x",
        "α": "a",
        "β": "b",
        "ε": "e",
        "ι": "i",
        "κ": "k",
        "μ": "m",
        "ν": "n",
        "ο": "o",
        "ρ": "p",
        "τ": "t",
        "χ": "x",
        "ϲ": "c",
        "ϳ": "j",
        "ϵ": "e",
        "ϱ": "p",
    }
)

_LEET_MAP = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_BASE64_TOKEN = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{12,}={0,2}(?![A-Za-z0-9+/])")
_HEX_TOKEN = re.compile(r"(?<![0-9a-f])(?:[0-9a-f]{2}){6,}(?![0-9a-f])", re.IGNORECASE)
_UNICODE_ESCAPE = re.compile(
    r"\\u([0-9a-f]{4})|\\U([0-9a-f]{8})|\\x([0-9a-f]{2})", re.IGNORECASE
)


def _contains_any(text: str, terms: frozenset[str]) -> bool:
    return any(term in text for term in terms)


def _is_safe_continuation(normalized: str, *, has_context: bool) -> bool:
    """Allow only project-bound continuation shorthand.

    A substring such as ``export`` or ``continue`` is not sufficient: without
    this check phrases like “export a joke” could inherit a prior project
    conversation and reach the model.  Exact short controls remain compatible
    with the web client; longer turns need an explicit project noun.
    """

    if not has_context:
        return False
    casual_markers = (
        "chat",
        "talk",
        "joke",
        "poem",
        "song",
        "story",
        "闲聊",
        "聊天",
        "笑话",
        "故事",
        "诗",
        "歌词",
    )
    if any(marker in normalized for marker in casual_markers):
        return False
    exact = {
        "继续",
        "接着",
        "补充",
        "再算一遍",
        "重算",
        "调整",
        "修改",
        "导出",
        "重做",
        "continue",
        "same project",
        "based on the previous",
        "revise",
        "export",
    }
    if normalized in exact:
        return True
    has_project_term = _contains_any(normalized, _CONTINUATION_PROJECT_TERMS)
    has_continuation_term = _contains_any(normalized, _CONTINUATION_TERMS)
    return has_project_term and has_continuation_term


def _is_workflow_shorthand(normalized: str) -> bool:
    """Match only a complete lifecycle control, never a prefixed payload."""

    return any(
        pattern.fullmatch(normalized) is not None
        for pattern in _TASK_WORKFLOW_PATTERNS
    )


def _has_file_action(normalized: str) -> bool:
    """Recognize an attachment operation without treating casual peeking as work."""

    if "随便" in normalized or "whatever" in normalized or "random" in normalized:
        return False
    if _contains_any(normalized, _FILE_ACTION_VERBS):
        return True
    if any(
        marker in normalized
        for marker in ("看看", "看一下", "请看", "请查看", "take a look", "look at")
    ):
        return any(
            marker in normalized
            for marker in ("请", "帮我", "please", "help", "附件", "文件", "资料", "this", "file", "document")
        )
    return False


def _decode_unicode_escapes(value: str) -> str:
    """Decode only literal ``\\uXXXX``/``\\xXX`` escapes for detection.

    This is intentionally not exposed to callers and is never persisted.  It
    lets the gate recognise a probe pasted as a JSON/Python escaped string
    while leaving ordinary user content untouched in the request path.
    """

    def replace(match: re.Match[str]) -> str:
        raw_codepoint = next((group for group in match.groups() if group), "")
        try:
            codepoint = int(raw_codepoint, 16)
        except ValueError:
            return match.group(0)
        # Do not manufacture lone UTF-16 surrogates; retaining the source is
        # safer and avoids encoding errors in later normalization steps.
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            return match.group(0)
        return chr(codepoint)

    return _UNICODE_ESCAPE.sub(replace, value)


def _printable_payload(value: bytes) -> str | None:
    """Return a bounded UTF-8 payload when it looks like human text."""

    if not value or len(value) > 4096:
        return None
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not decoded or len(decoded) > 2048:
        return None
    printable = sum(char.isprintable() or char.isspace() for char in decoded)
    if printable / len(decoded) < 0.78 or not any(char.isalpha() for char in decoded):
        return None
    return decoded


def _decoded_payloads(value: str):
    """Yield plausible base64/hex payloads without logging or storing them.

    Probe detection is a hot path.  Cap both token count and token length so a
    pasted document cannot turn the local classifier into an expensive decoder.
    The decoded text is subsequently checked against the same phrase-family
    patterns, so random identifiers do not become denials merely because they
    happen to be base64-looking strings.
    """

    seen_base64: set[str] = set()
    for match in islice(_BASE64_TOKEN.finditer(value), 8):
        token = match.group(0)
        if len(token) > 2048 or token in seen_base64:
            continue
        seen_base64.add(token)
        padded = token + "=" * ((4 - len(token) % 4) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True)
        except (binascii.Error, ValueError, UnicodeEncodeError):
            continue
        payload = _printable_payload(decoded)
        if payload is not None:
            yield payload

    seen_hex: set[str] = set()
    for match in islice(_HEX_TOKEN.finditer(value), 8):
        token = match.group(0)
        if len(token) > 2048 or token in seen_hex:
            continue
        seen_hex.add(token)
        try:
            decoded = bytes.fromhex(token)
        except ValueError:
            continue
        payload = _printable_payload(decoded)
        if payload is not None:
            yield payload


def _iter_probe_variants(value: str):
    """Yield a small set of normalized/obfuscation-resistant variants.

    The function is deliberately bounded and deterministic.  It handles the
    cheap transformations commonly used to evade ingress filters: zero-width
    characters (in :func:`normalize_text`), URL/HTML encoding, escaped Unicode,
    homoglyphs, leetspeak, punctuation/whitespace inserted between letters,
    and short base64/hex payloads.  No network or model call is involved.
    """

    # Keep the raw spelling as the first queue item.  ``normalize_text``
    # case-folds text, which is desirable for phrase matching but would make
    # case-sensitive base64 payloads impossible to decode.  The yielded value
    # is always normalized; raw text is retained only transiently for the
    # bounded decoding pass.
    queue = [value, normalize_text(value)]
    seen: set[str] = set()
    # A hard cap protects the request path even when a string contains many
    # nested encodings or mixed-script variants.
    while queue and len(seen) < 64:
        source = queue.pop(0)
        current = normalize_text(source)
        if not current or current in seen:
            continue
        seen.add(current)
        yield current

        candidates = (
            _decode_unicode_escapes(source),
            unquote(source),
            html.unescape(source),
            source.translate(_CONFUSABLES),
            source.translate(_LEET_MAP) if re.search(r"[0-9@$]", source) else source,
            re.sub(r"[\s_\-./\\:;,|]+", "", source),
            # Strip arbitrary punctuation/tags inserted between Latin letters
            # (e.g. ``system/**/prompt`` or ``system<!--x-->prompt``).
            re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", source),
            re.sub(r"<[^>]{0,256}>", " ", source),
        )
        for candidate in candidates:
            normalized_candidate = normalize_text(candidate)
            if normalized_candidate and normalized_candidate not in seen:
                queue.append(normalized_candidate)

        # Decode payloads only after the cheap variants above.  The payloads
        # are fed back through normalization/confusable handling on the next
        # queue iteration, allowing e.g. base64("ѕystem prompt") to be caught.
        for payload in _decoded_payloads(source):
            normalized_payload = normalize_text(payload)
            if normalized_payload and normalized_payload not in seen:
                queue.append(normalized_payload)


def is_high_risk_combination(value: str) -> bool:
    """Detect extraction verbs paired with protected objects.

    This helper is intentionally public to the policy module (but not exposed
    by the HTTP API) so tests and future policy revisions can exercise the
    mixed-language rule independently from the broader phrase families.
    """

    return any(
        pattern.search(candidate)
        for candidate in _iter_probe_variants(value)
        for pattern in _HIGH_RISK_COMBINATION_PATTERNS
    )


def is_prompt_probe(normalized: str) -> bool:
    """Return true when a turn asks for protected runtime/prompt metadata."""

    for candidate in _iter_probe_variants(normalized):
        if any(pattern.search(candidate) for pattern in _PROBE_PATTERNS):
            return True
        if any(pattern.search(candidate) for pattern in _HIGH_RISK_COMBINATION_PATTERNS):
            return True
    return False


def is_obviously_off_topic(normalized: str) -> bool:
    """Return true only for high-signal casual/leisure requests."""

    casual = normalized.strip(" !！?？。.,，\t")
    return casual in _CASUAL_EXACT or any(
        pattern.search(normalized) for pattern in _OFF_TOPIC_PATTERNS
    )


def _is_hard_off_topic(normalized: str) -> bool:
    return any(pattern.search(normalized) for pattern in _HARD_OFF_TOPIC_PATTERNS)


def evaluate_request(
    content: str,
    *,
    has_attachments: bool = False,
    has_context: bool = False,
) -> PolicyDecision:
    """Evaluate one user turn without making a model/provider call.

    ``has_context`` is supplied only when this conversation already contains
    a successful turn.  It permits natural continuations such as “继续” while
    keeping a brand-new conversation from becoming an unrestricted chatbot.
    """

    normalized = normalize_text(content)
    if not normalized:
        return PolicyDecision("deny", "invalid", "EMPTY_INPUT")

    # Pass the original spelling to the probe detector so case-sensitive
    # encodings (notably base64) can be decoded before normalization.
    if is_prompt_probe(content):
        return PolicyDecision("deny", "meta_probe", "PROMPT_PROBE")

    has_domain = _contains_any(normalized, _DOMAIN_TERMS)
    has_action = _contains_any(normalized, _ACTION_TERMS) or any(
        marker in normalized for marker in ("?", "？")
    )

    # A greeting can be a harmless preface to a real task (“你好，请分析项目”),
    # but an explicit leisure request must not be rescued by appending a
    # project noun (“讲个笑话，顺便分析项目”).
    if _is_hard_off_topic(normalized):
        return PolicyDecision("deny", "chat", "OFF_TOPIC_CHAT")
    if is_obviously_off_topic(normalized) and not (
        has_domain and has_action and normalized not in _CASUAL_EXACT
    ):
        return PolicyDecision("deny", "chat", "OFF_TOPIC_CHAT")

    if _is_safe_continuation(normalized, has_context=has_context):
        return PolicyDecision("allow", "project_continuation", "ALLOW_CONTINUATION")

    if has_attachments:
        # An arbitrary attachment must not turn an off-scope or probe-like
        # sentence into an allowed request.  Permit it only when the user asks
        # for an explicit file operation, supplies a normal project+action
        # task, or uses the trusted-context continuation path above.
        has_file_action = _has_file_action(normalized)
        if has_file_action or (has_domain and has_action):
            return PolicyDecision("allow", "project_file", "ALLOW_ATTACHMENT")
        return PolicyDecision("deny", "out_of_scope", "ATTACHMENT_WITHOUT_TASK")

    # Some existing clients mention an attachment explicitly while the file
    # id is carried in an earlier turn (for example, “请读取原附件并继续”).
    # Treat that as a project-file request even when this payload has no new
    # attachment id; a bare “继续” still requires ``has_context`` above.
    if _has_file_action(normalized) and _contains_any(normalized, _FILE_OBJECT_TERMS):
        return PolicyDecision("allow", "project_file", "ALLOW_FILE_REQUEST")

    if has_domain and has_action:
        return PolicyDecision("allow", "project_task", "ALLOW_PROJECT")

    # Preserve the existing web API's small set of task-control shorthands
    # without restoring a broad “unknown input is allowed” escape hatch.
    if _is_workflow_shorthand(normalized):
        return PolicyDecision("allow", "project_workflow", "ALLOW_WORKFLOW")

    # New conversations are allow-list first.  The HTTP layer returns the same
    # short fixed response for this branch as for chat/probes, so callers cannot
    # use reason-specific copy to reverse-engineer the detector.
    return PolicyDecision("deny", "out_of_scope", "OUT_OF_SCOPE")


__all__ = [
    "POLICY_REFUSAL",
    "POLICY_VERSION",
    "PolicyDecision",
    "evaluate_request",
    "is_high_risk_combination",
    "is_prompt_probe",
    "is_obviously_off_topic",
    "normalize_text",
]
