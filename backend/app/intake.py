"""Deterministic guided-intake helpers for the web conversation API.

The intake layer deliberately contains no model/provider calls.  It classifies
the user's request with bounded lexical rules, presents a small allow-listed
set of questions, validates the selected values, and produces a user-data
prompt section which is appended to (rather than replacing) the original
request.  Keeping this contract local makes the first turn cheap, predictable,
and safe to retry.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Mapping


INTAKE_VERSION = 1
INTAKE_ID_RE = re.compile(r"^intake_[0-9a-f]{32}$")
MAX_CUSTOM_ANSWER_CHARACTERS = 500
MAX_ANSWER_COUNT = 32
MAX_OPTION_SELECTIONS = 8
INTAKE_ACTION_ALIASES = {
    "submit": "confirm",
    "continue": "confirm",
    "start": "run",
}


class IntakeError(ValueError):
    """A client-correctable intake validation error.

    ``code`` is stable enough for a UI to show a targeted message while the
    human-readable text remains Chinese-first for the current web client.
    """

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class IntakeOption:
    id: str
    label: str
    description: str = ""
    recommended: bool = False

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
        }
        if self.description:
            value["description"] = self.description
            # ``impact`` is the UI-facing name used by the current web card;
            # retain ``description`` for older clients and API consumers.
            value["impact"] = self.description
        if self.recommended:
            value["recommended"] = True
        return value


@dataclass(frozen=True, slots=True)
class IntakeQuestion:
    id: str
    prompt: str
    options: tuple[IntakeOption, ...]
    required: bool = True
    allow_custom: bool = True
    custom_placeholder: str = "也可以直接告诉我你的偏好"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "field": self.id,
            "kind": "single",
            "prompt": self.prompt,
            "help": "可选择最接近的一项；没有完全匹配时可以补充具体条件。",
            "required": self.required,
            "allow_custom": self.allow_custom,
            "custom_placeholder": self.custom_placeholder,
            "options": [option.as_dict() for option in self.options],
        }


# Stable task type names are intentionally independent from specialist skill
# ids.  A client can safely persist them while the controller evolves.
TASK_TYPE_LABELS: dict[str, str] = {
    "research": "研究分析",
    "product_strategy": "产品与定位",
    "marketing_strategy": "营销与传播",
    "community_operations": "社群与运营",
    "wechat_archive": "微信资料整理",
    "report_editorial": "报告撰写与润色",
    "report_design": "报告排版与设计",
    "social_promotion": "社交平台内容",
    "pdf_output": "PDF 成果输出",
    "delivery_qa": "成果验收与质检",
    "general": "项目协作",
}


def _option(
    option_id: str,
    label: str,
    description: str = "",
    *,
    recommended: bool = False,
) -> IntakeOption:
    return IntakeOption(option_id, label, description, recommended)


def _question(
    question_id: str,
    prompt: str,
    options: Iterable[IntakeOption],
    *,
    required: bool = True,
    allow_custom: bool = True,
) -> IntakeQuestion:
    return IntakeQuestion(
        question_id,
        prompt,
        tuple(options),
        required=required,
        allow_custom=allow_custom,
    )


# The bank is the only source of selectable values.  Do not derive option text
# from user input; custom answers are carried in a separate bounded field.
QUESTION_BANK: dict[str, tuple[IntakeQuestion, ...]] = {
    "research": (
        _question(
            "goal",
            "这次研究最想支持哪一个决策？",
            (
                _option("decision", "支持决策", "给出可执行的取舍建议", recommended=True),
                _option("landscape", "摸清市场", "建立区域、竞品或政策全景"),
                _option("validation", "验证假设", "检验已有判断和风险"),
            ),
        ),
        _question(
            "scope",
            "优先聚焦哪些范围？",
            (
                _option("market", "市场与政策", "区域、供需、政策和竞品"),
                _option("product", "产品与客户", "客群、定位、户型和价格"),
                _option("full", "两者都要", "市场与产品联动分析", recommended=True),
            ),
        ),
        _question(
            "depth",
            "希望采用哪种分析节奏？",
            (
                _option("brief", "快速判断", "先给结论和关键依据"),
                _option("standard", "标准研究", "结论、证据与行动建议", recommended=True),
                _option("audit", "深度审计", "尽量穷尽证据并标注不确定性"),
            ),
        ),
    ),
    "product_strategy": (
        _question(
            "decision",
            "产品策略更看重哪项结果？",
            (
                _option("sell_through", "去化速度", "优先提高成交和去化效率", recommended=True),
                _option("margin", "利润空间", "优先保护价格和利润"),
                _option("balance", "均衡方案", "在速度与利润间做取舍"),
            ),
        ),
        _question(
            "audience",
            "先锁定哪类核心客群？",
            (
                _option("first_home", "刚需首置", "首次置业或基础改善"),
                _option("upgrade", "改善置换", "面积、品质或功能升级", recommended=True),
                _option("investment", "投资客户", "收益、流动性与资产配置"),
            ),
        ),
        _question(
            "output",
            "希望最终拿到什么形式？",
            (
                _option("recommendation", "策略建议", "关键结论与优先级"),
                _option("product_matrix", "产品矩阵", "面积段、户型和价格组合", recommended=True),
                _option("action_plan", "落地计划", "分阶段动作、指标和负责人"),
            ),
        ),
    ),
    "marketing_strategy": (
        _question(
            "audience",
            "这轮营销首先要影响谁？",
            (
                _option("buyer", "购房客户", "提升认知、到访或成交", recommended=True),
                _option("channel", "渠道伙伴", "让渠道更易理解和转述"),
                _option("internal", "内部团队", "统一销售和传播口径"),
            ),
        ),
        _question(
            "tone",
            "更偏好哪种表达气质？",
            (
                _option("rational", "理性可信", "证据、数据和专业感", recommended=True),
                _option("emotional", "情绪共鸣", "场景、故事和记忆点"),
                _option("premium", "高端克制", "稀缺、品质和品牌感"),
            ),
        ),
        _question(
            "channel",
            "优先落地到哪个触点？",
            (
                _option("sales", "销售现场", "案场、话术和物料"),
                _option("social", "社交平台", "小红书、抖音、朋友圈等"),
                _option("campaign", "整合活动", "线上线下联动", recommended=True),
            ),
        ),
    ),
    "community_operations": (
        _question(
            "stage",
            "社群目前处于哪个阶段？",
            (
                _option("build", "搭建期", "明确人群、规则和内容"),
                _option("operate", "运营期", "提升活跃、留存和转化", recommended=True),
                _option("revive", "盘活期", "找出流失原因并重启互动"),
            ),
        ),
        _question(
            "metric",
            "最想优先改善哪个指标？",
            (
                _option("engagement", "活跃互动", "发言、参与和内容反馈", recommended=True),
                _option("conversion", "线索转化", "到访、成交或复购"),
                _option("referral", "口碑转介绍", "老带新和用户推荐"),
            ),
        ),
        _question(
            "cadence",
            "希望建议细化到什么程度？",
            (
                _option("principles", "原则框架", "给出方法和边界"),
                _option("calendar", "内容日历", "按周或按月排期", recommended=True),
                _option("scripts", "执行脚本", "直接可用的话术和动作"),
            ),
        ),
    ),
    "wechat_archive": (
        _question(
            "purpose",
            "整理微信资料主要为了什么？",
            (
                _option("archive", "归档留存", "结构化保存原文和附件", recommended=True),
                _option("brief", "提炼摘要", "快速掌握重点和结论"),
                _option("research", "纳入研究", "作为项目分析证据"),
            ),
        ),
        _question(
            "fidelity",
            "对原文还原度有什么要求？",
            (
                _option("verbatim", "尽量原样", "保留标题、段落和链接", recommended=True),
                _option("clean", "清理排版", "去除冗余元素后阅读"),
                _option("structured", "结构化整理", "按主题重组内容"),
            ),
        ),
    ),
    "report_editorial": (
        _question(
            "reader",
            "报告主要给谁阅读？",
            (
                _option("management", "管理层", "结论先行、便于决策", recommended=True),
                _option("team", "项目团队", "强调方法、分工和执行"),
                _option("client", "外部客户", "兼顾可信度与易读性"),
            ),
        ),
        _question(
            "edit_mode",
            "更希望我怎样处理现有内容？",
            (
                _option("polish", "润色优化", "保留观点，改善表达", recommended=True),
                _option("rewrite", "重写结构", "重排逻辑和叙事"),
                _option("fact_check", "校核补缺", "标出证据缺口和待确认项"),
            ),
        ),
    ),
    "report_design": (
        _question(
            "style",
            "希望报告呈现什么视觉气质？",
            (
                _option("executive", "管理汇报", "清晰、克制、结论突出", recommended=True),
                _option("editorial", "杂志叙事", "层次、留白和阅读感"),
                _option("sales", "营销展示", "重点鲜明、便于传播"),
            ),
        ),
        _question(
            "format",
            "优先交付哪种载体？",
            (
                _option("html", "网页 HTML", "适合在线浏览和分享"),
                _option("markdown", "Markdown", "便于协作和继续编辑"),
                _option("both", "两者都要", "网页与源稿同时交付", recommended=True),
            ),
        ),
    ),
    "social_promotion": (
        _question(
            "platform",
            "这次内容优先发布到哪里？",
            (
                _option("xiaohongshu", "小红书", "种草、搜索和收藏"),
                _option("douyin", "抖音", "短视频或口播传播"),
                _option("moments", "朋友圈", "熟人传播和转发", recommended=True),
            ),
        ),
        _question(
            "conversion",
            "希望用户看完后做什么？",
            (
                _option("learn", "记住观点", "优先建立认知"),
                _option("contact", "咨询了解", "引导私信、留言或到访", recommended=True),
                _option("share", "转发扩散", "优先提升分享率"),
            ),
        ),
    ),
    "pdf_output": (
        _question(
            "use_case",
            "PDF 主要用于哪种场景？",
            (
                _option("meeting", "会议汇报", "屏幕阅读和快速翻页", recommended=True),
                _option("print", "打印分发", "关注纸面可读性"),
                _option("archive", "正式归档", "关注完整性和可追溯性"),
            ),
        ),
        _question(
            "density",
            "内容密度更偏向哪一侧？",
            (
                _option("concise", "结论精简", "少字、强重点"),
                _option("balanced", "信息均衡", "结论与证据兼顾", recommended=True),
                _option("detailed", "证据详尽", "保留方法、表格和附录"),
            ),
        ),
    ),
    "delivery_qa": (
        _question(
            "focus",
            "验收时最不能出什么问题？",
            (
                _option("facts", "事实与数据", "来源、口径和计算准确"),
                _option("files", "文件可交付", "格式、路径和打开正常", recommended=True),
                _option("logic", "逻辑与表达", "结论完整、易读且可执行"),
            ),
        ),
        _question(
            "strictness",
            "希望验收结果如何呈现？",
            (
                _option("blockers", "只报阻断项", "聚焦必须修复的问题"),
                _option("scorecard", "评分清单", "按维度给出等级和证据", recommended=True),
                _option("full_review", "完整复核", "问题、建议和复验步骤"),
            ),
        ),
    ),
    "general": (
        _question(
            "outcome",
            "你希望本轮优先得到什么？",
            (
                _option("answer", "明确结论", "先回答当前关键问题", recommended=True),
                _option("plan", "行动方案", "拆成可以执行的步骤"),
                _option("draft", "可编辑初稿", "先产出结构化草稿"),
            ),
        ),
        _question(
            "detail",
            "需要多深的展开？",
            (
                _option("brief", "简明版", "重点和下一步"),
                _option("standard", "标准版", "结论、依据和建议", recommended=True),
                _option("deep", "深度版", "完整分析与风险边界"),
            ),
        ),
    ),
}


# Ordered from explicit output/delivery intent to broad research terms.  The
# first matching rule wins: a request that mentions PDF/HTML as the requested
# output is routed to the corresponding delivery card, while “分析网页数据”
# remains a research task because “网页” alone is not a design instruction.
_CLASSIFICATION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Format tokens are handled by the context-aware hints below.  Keep the
    # broad rules free of a bare ``pdf 文件`` match so “分析 PDF 文件” stays
    # a research task rather than being mistaken for a delivery request.
    (
        "pdf_output",
        (
            "导出成pdf",
            "生成pdf",
            "转换为pdf",
            "转为pdf",
            "转成pdf",
            "另存为pdf",
            "导出为pdf",
            "输出pdf",
            "输出为pdf",
            "pdf版",
            "export pdf",
            "generate pdf",
            "convert to pdf",
            "pdf output",
            "pdf version",
        ),
    ),
    (
        "wechat_archive",
        ("微信文章", "公众号文章", "微信", "公众号", "归档", "wechat"),
    ),
    (
        "social_promotion",
        (
            "小红书",
            "抖音",
            "朋友圈",
            "社交平台",
            "社交媒体",
            "社交平台运营",
            "短视频",
            "平台文案",
            "平台内容",
            "种草",
            "xiaohongshu",
            "douyin",
            "tiktok",
            "social media",
        ),
    ),
    (
        "community_operations",
        (
            "社群",
            "社群运营",
            "私域",
            "用户运营",
            "老带新",
            "nps",
            "community",
            "private domain",
            "user operations",
            "referral",
        ),
    ),
    (
        "delivery_qa",
        (
            "验收",
            "质检",
            "质量检查",
            "交付检查",
            "检查交付",
            "交付物检查",
            "复核成果",
            "复核报告",
            "成果检查",
            "核查成果",
            "成果验收",
            "质量验收",
            "交付物",
            "检查文件",
            "格式检查",
            "文件校验",
            "校验文件",
            "quality check",
            "quality assurance",
            "acceptance",
            "delivery check",
            "delivery files",
            "review delivery",
            "file check",
            "check files",
        ),
    ),
    (
        "report_design",
        (
            "排版",
            "版式",
            "视觉设计",
            "网页设计",
            "网页排版",
            "生成网页",
            "演示文稿",
            "汇报ppt",
            "报告设计",
            "html report",
            "web report",
            "slide deck",
            "report layout",
            "visual design",
        ),
    ),
    (
        "report_editorial",
        (
            "撰写报告",
            "报告撰写",
            "报告润色",
            "润色报告",
            "改写报告",
            "报告初稿",
            "写报告",
            "写一份报告",
            "写一篇报告",
            "写一篇文章",
            "生成汇报材料",
            "写汇报材料",
            "汇报材料",
            "汇报稿",
            "文稿",
            "write report",
            "report writing",
            "polish report",
            "rewrite report",
            "edit report",
            "draft report",
            "write a report",
            "briefing",
        ),
    ),
    (
        "marketing_strategy",
        (
            "营销",
            "营销方案",
            "传播策略",
            "传播方案",
            "品牌传播",
            "推广",
            "推广方案",
            "推广策略",
            "营销策划",
            "营销策略",
            "市场推广",
            "销售话术",
            "品牌故事",
            "广告文案",
            "营销文案",
            "marketing",
            "marketing plan",
            "marketing strategy",
            "campaign",
            "promotion",
            "brand story",
            "sales pitch",
        ),
    ),
    (
        "product_strategy",
        (
            "产品定位",
            "产品策略",
            "产品规划",
            "产品组合",
            "产品定位策略",
            "客群定位",
            "户型优化",
            "定价",
            "户型",
            "面积段",
            "价格策略",
            "货值",
            "去化",
            "product positioning",
            "product strategy",
            "product plan",
            "positioning strategy",
            "pricing strategy",
            "pricing",
            "sell-through",
        ),
    ),
    (
        "research",
        (
            "研究",
            "分析",
            "阅读",
            "解读",
            "提取",
            "核查",
            "总结",
            "对比",
            "评估",
            "市场",
            "政策",
            "竞品",
            "数据",
            "调研",
            "趋势",
            "结论",
            "洞察",
            "research",
            "analysis",
            "analyze",
            "analyse",
            "read",
            "review",
            "extract",
            "summarize",
            "summarise",
            "market",
            "policy",
            "competitor",
            "data",
            "survey",
            "trend",
            "summarize",
            "evaluate",
        ),
    ),
)


def normalize_text(value: str) -> str:
    """Normalize Unicode and whitespace for deterministic classification."""

    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def classify_task(content: str, *, attachment_ids: Iterable[str] = ()) -> str:
    """Return a stable task type using an allow-listed lexical classifier."""

    if not isinstance(content, str):
        raise IntakeError("INVALID_CONTENT", "任务内容必须是文本。")
    normalized = normalize_text(content)
    if not normalized:
        raise IntakeError("INVALID_CONTENT", "任务内容不能为空。")

    # A format name can describe either the source ("分析 PDF 报告") or the
    # requested deliverable ("把报告导出成 PDF").  Require a production verb
    # to be close to the token, and only accept a reverse ``PDF 导出`` /
    # ``HTML 报告`` phrase when it is not surrounded by source-analysis verbs.
    # This keeps common short requests useful without turning “分析网页报告”
    # into a design task.
    output_verbs = (
        "导出|生成|转换|转为|转成|另存为|导出为|输出|制作|排版|打印|做成|归档成|"
        "export|generate|convert|create|make|render|print|output|design"
    )
    source_verbs = re.compile(
        r"分析|阅读|解读|提取|核查|总结|研究|对比|审阅|查看|读取|评估|"
        r"analy[sz]e|read|review|extract|summari[sz]e|research|compare|evaluate"
    )

    def has_source_context(start: int, token_length: int) -> bool:
        prefix = normalized[max(0, start - 10) : start]
        suffix_start = start + token_length
        suffix = normalized[suffix_start : suffix_start + 10]
        return bool(source_verbs.search(prefix) or source_verbs.search(suffix))

    # Keep the connector window generous enough for natural phrasing such as
    # “阅读 PDF 并导出” / “PDF 后生成报告”, while checking the object after a
    # reverse verb so “分析 PDF 后生成网页报告” is routed to the web/report
    # card rather than incorrectly treated as PDF delivery.
    # English requests often place a short object between the verb and format
    # ("convert this report into a PDF"). Keep the window bounded but wide
    # enough for that natural phrasing.
    pdf_forward = re.search(rf"(?:{output_verbs}).{{0,32}}pdf", normalized)
    if pdf_forward:
        return "pdf_output"
    pdf_reverse = re.search(rf"pdf.{{0,32}}(?:{output_verbs})", normalized)
    if pdf_reverse:
        reverse_text = pdf_reverse.group()
        verb_match = re.search(rf"(?:{output_verbs})", reverse_text)
        # The regex intentionally stops at the verb; inspect the following
        # object in the normalized request to distinguish “PDF 后生成报告”
        # from “PDF 并导出”.
        suffix = normalized[pdf_reverse.end() : pdf_reverse.end() + 40]
        # A reverse verb followed by another explicit deliverable belongs to
        # that deliverable (for example “PDF 后生成网页报告”).
        if not any(
            token in suffix
            for token in (
                "html",
                "网页",
                "ppt",
                "演示文稿",
                "报告",
                "方案",
                "结论",
                "摘要",
                "结果",
                "数据",
                "文本",
                "markdown",
                "report",
                "conclusion",
                "summary",
                "result",
                "data",
                "text",
            )
        ):
            return "pdf_output"
    pdf_bare = re.search(
        r"pdf\s*(?:版|格式|成果|页面|导出|输出|生成|制作|排版|归档|"
        r"output|export|version|file|report)",
        normalized,
    )
    if pdf_bare and not has_source_context(pdf_bare.start(), 3):
        return "pdf_output"

    design_forward = re.search(
        rf"(?:{output_verbs}|设计).{{0,32}}(?:html|网页|ppt|演示文稿|web|slide)",
        normalized,
    )
    if design_forward:
        return "report_design"
    design_reverse = re.search(
        r"(?:html|网页|ppt|演示文稿|web|slide).{0,32}"
        r"(?:报告|页面|版式|模板|导出|输出|生成|制作|排版|report|page|layout|template|"
        r"export|output|generate|create|design)",
        normalized,
    )
    if design_reverse:
        token_match = re.search(r"html|网页|ppt|演示文稿", design_reverse.group())
        if token_match:
            token_start = design_reverse.start() + token_match.start()
            token_length = len(token_match.group())
            if not has_source_context(token_start, token_length):
                return "report_design"

    # Domain-specific deliverables should keep their specialist card even
    # when the request also contains a generic “write/generate a report” verb.
    # For example, “make a marketing plan” is a marketing decision rather
    # than an editorial rewrite, while “分析营销数据” remains research because
    # it has no strategy/campaign deliverable hint.
    def near_tokens(left: tuple[str, ...], right: tuple[str, ...], window: int = 40) -> bool:
        left_pattern = "|".join(re.escape(token) for token in left)
        right_pattern = "|".join(re.escape(token) for token in right)
        return bool(
            re.search(rf"(?:{left_pattern}).{{0,{window}}}(?:{right_pattern})", normalized)
            or re.search(rf"(?:{right_pattern}).{{0,{window}}}(?:{left_pattern})", normalized)
        )

    # Quality/acceptance language takes precedence over a generic “review” or
    # “report” token.  This catches natural variants such as “检查成果文件”
    # and “审阅报告” without turning ordinary “分析报告” into a QA task.
    if near_tokens(
        ("成果", "交付", "文件", "报告", "输出", "artifact", "delivery", "file", "report", "quality"),
        ("验收", "质检", "检查", "核查", "复核", "审阅", "审核", "review", "check", "verify", "qa"),
        24,
    ):
        return "delivery_qa"

    if near_tokens(
        ("营销", "传播", "推广", "品牌", "marketing", "campaign", "promotion", "brand", "sales"),
        ("方案", "策略", "计划", "文案", "campaign", "strategy", "plan", "copy"),
    ):
        return "marketing_strategy"
    if near_tokens(
        ("产品", "户型", "定价", "货值", "去化", "product", "pricing", "positioning"),
        ("方案", "策略", "计划", "矩阵", "组合", "strategy", "plan", "matrix", "mix"),
    ):
        return "product_strategy"
    if near_tokens(
        ("小红书", "抖音", "朋友圈", "社交平台", "社交媒体", "短视频", "xiaohongshu", "douyin", "tiktok", "social media"),
        ("方案", "策略", "计划", "文案", "脚本", "内容", "post", "copy", "script", "plan", "strategy"),
    ):
        return "social_promotion"

    if near_tokens(
        ("报告", "文稿", "汇报", "材料", "文章", "report", "briefing", "document"),
        (
            "润色", "改写", "改成", "改好", "优化", "编辑", "校对", "审校", "写", "撰写",
            "起草", "draft", "edit", "polish", "rewrite", "write",
        ),
        28,
    ) or re.search(r"(?:报告|文稿|汇报|材料).{0,20}改(?:得|好|写)?", normalized):
        return "report_editorial"

    # A plain report/briefing deliverable still benefits from the editorial
    # card, even when the request first names a source (“阅读 PDF 后生成报告”).
    report_output_hint = re.search(
        r"(?:生成|撰写|编写|制作|输出|形成|写|起草|整理|generate|write|create|make|produce|draft).{0,32}"
        r"(?:报告|方案|汇报稿|文稿|report|brief|plan|briefing)",
        normalized,
    )
    if report_output_hint:
        return "report_editorial"
    for task_type, keywords in _CLASSIFICATION_RULES:
        if any(keyword.casefold() in normalized for keyword in keywords):
            return task_type
    # Attachments without a useful title are most often source material for a
    # research turn; this still gives the user a chance to steer the scope.
    if attachment_ids is not None and any(str(item).strip() for item in attachment_ids):
        return "research"
    return "general"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def intake_expired(record: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Return whether an intake has passed its expiry timestamp.

    New records always include a 24-hour TTL.  Missing or malformed values are
    treated as expired so an incomplete sidecar can never become a permanent
    conversation lock while older records roll forward.
    """

    expires_at = record.get("expires_at")
    if not isinstance(expires_at, str) or not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        # Storage validation normally catches this; treating malformed expiry
        # as expired is safer for callers operating on an in-memory record.
        return True
    if expiry.tzinfo is None:
        return True
    comparison_now = now or datetime.now(UTC)
    if comparison_now.tzinfo is None:
        comparison_now = comparison_now.replace(tzinfo=UTC)
    return expiry <= comparison_now


def _new_intake_id() -> str:
    return f"intake_{uuid.uuid4().hex}"


def questions_for(task_type: str) -> tuple[IntakeQuestion, ...]:
    if task_type not in QUESTION_BANK:
        raise IntakeError("UNKNOWN_TASK_TYPE", "暂不支持该任务类型。")
    return QUESTION_BANK[task_type]


def build_intake(
    content: str,
    *,
    attachment_ids: Iterable[str] = (),
    intake_id: str | None = None,
    client_request_id: str | None = None,
) -> dict[str, Any]:
    """Create a durable, JSON-safe pending intake record."""

    if not isinstance(content, str):
        raise IntakeError("INVALID_CONTENT", "任务内容必须是文本。")
    original_content = content.strip()
    if not original_content:
        raise IntakeError("INVALID_CONTENT", "任务内容不能为空。")
    if len(original_content) > 200_000:
        raise IntakeError("CONTENT_TOO_LONG", "任务内容过长。")
    ids: list[str] = []
    for item in attachment_ids or ():
        if not isinstance(item, str) or not item.strip():
            raise IntakeError("INVALID_ATTACHMENT", "附件标识无效。")
        if item not in ids:
            ids.append(item)
    if len(ids) > 20:
        raise IntakeError("TOO_MANY_ATTACHMENTS", "一次最多附加 20 个文件。")
    effective_id = intake_id or _new_intake_id()
    if not isinstance(effective_id, str) or not INTAKE_ID_RE.fullmatch(effective_id):
        raise IntakeError("INVALID_INTAKE_ID", "intake_id 格式无效。")
    task_type = classify_task(original_content, attachment_ids=ids)
    created = _now()
    # Keep a card recoverable across normal work sessions and browser
    # refreshes.  Expiry is a safety bound, not a user-facing countdown.
    expires_at = (
        datetime.now(UTC) + timedelta(hours=24)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {
        "version": INTAKE_VERSION,
        "intake_id": effective_id,
        "status": "awaiting_input",
        "task_type": task_type,
        "task_type_label": TASK_TYPE_LABELS[task_type],
        "original_content": original_content,
        "content_sha256": content_digest(original_content),
        "attachment_ids": ids,
        "questions": [question.as_dict() for question in questions_for(task_type)],
        "title": "先对齐关键取舍",
        "description": "这些选择会影响本轮分析的侧重点和交付方式。",
        "created_at": created,
        "updated_at": created,
        "expires_at": expires_at,
        **({"client_request_id": client_request_id} if client_request_id else {}),
    }


def public_intake(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable response projection (without internal sidecar fields)."""

    allowed = (
        "version",
        "intake_id",
        "status",
        "task_type",
        "task_type_label",
        "original_content",
        "attachment_ids",
        "questions",
        "title",
        "description",
        "created_at",
        "updated_at",
        "expires_at",
        "client_request_id",
    )
    return {key: record[key] for key in allowed if key in record}


def _question_map(record_or_questions: Mapping[str, Any] | Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    if isinstance(record_or_questions, Mapping):
        raw_questions = record_or_questions.get("questions", [])
    else:
        raw_questions = record_or_questions
    if not isinstance(raw_questions, Iterable) or isinstance(raw_questions, (str, bytes, Mapping)):
        raise IntakeError("INVALID_QUESTIONS", "任务问题清单无效。")
    result: dict[str, Mapping[str, Any]] = {}
    for question in raw_questions:
        if not isinstance(question, Mapping):
            raise IntakeError("INVALID_QUESTIONS", "任务问题清单无效。")
        question_id = question.get("id")
        options = question.get("options")
        if not isinstance(question_id, str) or not question_id or question_id in result:
            raise IntakeError("INVALID_QUESTIONS", "任务问题标识无效。")
        if not isinstance(options, list):
            raise IntakeError("INVALID_QUESTIONS", "任务选项清单无效。")
        result[question_id] = question
    return result


def _option_map(question: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    options = question.get("options")
    if not isinstance(options, list):
        raise IntakeError("INVALID_QUESTIONS", "任务选项清单无效。")
    result: dict[str, Mapping[str, Any]] = {}
    for option in options:
        if not isinstance(option, Mapping):
            raise IntakeError("INVALID_QUESTIONS", "任务选项无效。")
        option_id = option.get("id")
        if not isinstance(option_id, str) or not option_id or option_id in result:
            raise IntakeError("INVALID_QUESTIONS", "任务选项标识无效。")
        result[option_id] = option
    return result


def _raw_answer_parts(value: Any) -> tuple[list[str], str | None]:
    """Convert accepted client shapes to ``(option_ids, custom_text)``.

    The web client always sends ``option_ids`` (an array) so the protocol can
    support future multi-select questions.  Older callers may still send a
    scalar ``option_id``/``option``/``value``; both forms are accepted.
    """

    if isinstance(value, str):
        item = value.strip()
        return ([item] if item else []), None
    if isinstance(value, list):
        # Mapping-style callers often use ``{"goal": ["decision"]}`` for
        # both single- and multi-select questions.  Accept that compact shape
        # while keeping the same string/type checks as the object form.
        option_ids: list[str] = []
        for option_value in value:
            if not isinstance(option_value, str):
                raise IntakeError("INVALID_ANSWER", "选项标识必须是文本。")
            normalized = option_value.strip()
            if normalized and normalized not in option_ids:
                option_ids.append(normalized)
        if len(option_ids) > MAX_OPTION_SELECTIONS:
            raise IntakeError("TOO_MANY_OPTIONS", "单个问题的选项过多。")
        return option_ids, None
    if not isinstance(value, Mapping):
        raise IntakeError("INVALID_ANSWER", "答案格式无效。")
    option_values = value.get("option_ids")
    if option_values is None:
        option_value = value.get("option_id", value.get("option", value.get("value")))
        option_values = [option_value] if option_value is not None else []
    if not isinstance(option_values, list):
        option_values = [option_values]
    option_ids: list[str] = []
    for option_value in option_values:
        if not isinstance(option_value, str):
            raise IntakeError("INVALID_ANSWER", "选项标识必须是文本。")
        normalized = option_value.strip()
        if normalized and normalized not in option_ids:
            option_ids.append(normalized)
    custom_value = value.get("custom_text", value.get("custom"))
    custom_text = custom_value.strip() if isinstance(custom_value, str) else None
    if custom_value is not None and custom_text is None:
        raise IntakeError("INVALID_ANSWER", "自定义答案必须是文本。")
    if len(option_ids) > MAX_OPTION_SELECTIONS:
        raise IntakeError("TOO_MANY_OPTIONS", "单个问题的选项过多。")
    return option_ids, custom_text or None


def _iter_answer_items(raw_answers: Any) -> list[tuple[str, Any]]:
    if raw_answers is None:
        return []
    if isinstance(raw_answers, Mapping):
        result: list[tuple[str, Any]] = []
        for index, (question_id, value) in enumerate(raw_answers.items()):
            if index >= MAX_ANSWER_COUNT:
                raise IntakeError("TOO_MANY_ANSWERS", "答案项过多。")
            result.append((str(question_id), value))
        return result
    if not isinstance(raw_answers, list):
        raise IntakeError("INVALID_ANSWERS", "intake_answers 必须是对象或数组。")
    result: list[tuple[str, Any]] = []
    for index, item in enumerate(raw_answers):
        if index >= MAX_ANSWER_COUNT:
            raise IntakeError("TOO_MANY_ANSWERS", "答案项过多。")
        if not isinstance(item, Mapping):
            raise IntakeError("INVALID_ANSWER", "答案项格式无效。")
        question_id = item.get("question_id", item.get("id"))
        if not isinstance(question_id, str) or not question_id.strip():
            raise IntakeError("INVALID_ANSWER", "答案缺少问题标识。")
        result.append((question_id.strip(), item))
    return result


def normalize_action(action: str | None) -> str:
    """Normalize public action aliases to the two execution semantics."""

    if action is None:
        return "confirm"
    if not isinstance(action, str):
        raise IntakeError("INVALID_ACTION", "不支持的 intake 操作。")
    normalized = action.strip().casefold()
    return INTAKE_ACTION_ALIASES.get(normalized, normalized)


def validate_answers(
    record_or_questions: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    raw_answers: Any,
    *,
    action: str | None = None,
) -> list[dict[str, Any]]:
    """Validate and normalize answers against the allow-listed questions.

    ``skip``/``run`` are explicit bypass actions.  They produce an empty list
    and let a user run with only the original request; all other actions must
    answer every required question.
    """

    normalized_action = normalize_action(action)
    if normalized_action in {"cancel", "delete"}:
        raise IntakeError("INTAKE_CANCELLED", "该追问已取消。")
    if normalized_action not in {"confirm", "run", "skip"}:
        raise IntakeError("INVALID_ACTION", "不支持的 intake 操作。")
    question_map = _question_map(record_or_questions)
    if normalized_action in {"run", "skip"}:
        # Skip/run deliberately ignores the values, but still parse the outer
        # transport shape and enforce the global item bound.  This prevents a
        # caller from using the bypass action to smuggle an unbounded answer
        # object through the validation boundary.
        items = _iter_answer_items(raw_answers)
        if len(items) > MAX_ANSWER_COUNT:
            raise IntakeError("TOO_MANY_ANSWERS", "答案项过多。")
        return []
    items = _iter_answer_items(raw_answers)
    if len(items) > MAX_ANSWER_COUNT:
        raise IntakeError("TOO_MANY_ANSWERS", "答案项过多。")
    answers_by_question: dict[str, tuple[list[str], str | None]] = {}
    for question_id, raw_value in items:
        if question_id not in question_map:
            raise IntakeError("UNKNOWN_QUESTION", "答案包含未提供的问题。", question_id=question_id)
        if question_id in answers_by_question:
            raise IntakeError("DUPLICATE_ANSWER", "同一个问题只能回答一次。", question_id=question_id)
        option_ids, custom_text = _raw_answer_parts(raw_value)
        question = question_map[question_id]
        options = _option_map(question)
        if str(question.get("kind") or "single").casefold() != "multi" and len(option_ids) > 1:
            raise IntakeError("MULTIPLE_OPTIONS_NOT_ALLOWED", "该问题只能选择一个选项。", question_id=question_id)
        for option_id in option_ids:
            if option_id not in options:
                raise IntakeError("UNKNOWN_OPTION", "答案包含未提供的选项。", question_id=question_id, option_id=option_id)
        allow_custom = bool(question.get("allow_custom", False))
        if custom_text is not None:
            if not allow_custom:
                raise IntakeError("CUSTOM_NOT_ALLOWED", "该问题不接受自定义答案。", question_id=question_id)
            if len(custom_text) > MAX_CUSTOM_ANSWER_CHARACTERS:
                raise IntakeError("CUSTOM_TOO_LONG", "自定义答案过长。", question_id=question_id)
        if not option_ids and custom_text is None:
            raise IntakeError("EMPTY_ANSWER", "答案不能为空。", question_id=question_id)
        answers_by_question[question_id] = (option_ids, custom_text)

    missing = [
        question_id
        for question_id, question in question_map.items()
        if bool(question.get("required", True)) and question_id not in answers_by_question
    ]
    if missing:
        raise IntakeError("MISSING_ANSWER", "请先回答所有必答问题。", missing_questions=missing)

    normalized: list[dict[str, Any]] = []
    for question_id, question in question_map.items():
        if question_id not in answers_by_question:
            continue
        option_ids, custom_text = answers_by_question[question_id]
        options = _option_map(question)
        item: dict[str, Any] = {
            "question_id": question_id,
            "question": str(question.get("prompt") or ""),
        }
        if len(option_ids) == 1:
            option_id = option_ids[0]
            item["option_id"] = option_id
            item["option_ids"] = [option_id]
            item["label"] = str(options[option_id].get("label") or option_id)
        elif option_ids:
            item["option_ids"] = list(option_ids)
            item["labels"] = [str(options[item_id].get("label") or item_id) for item_id in option_ids]
        if custom_text is not None:
            item["custom_text"] = custom_text
        normalized.append(item)
    return normalized


def normalize_saved_answers(raw_answers: Any) -> list[dict[str, Any]]:
    """Normalize already-validated metadata for retry prompt reconstruction."""

    if not isinstance(raw_answers, list):
        raise IntakeError("INVALID_SAVED_ANSWERS", "历史 intake 答案无效。")
    if len(raw_answers) > MAX_ANSWER_COUNT:
        raise IntakeError("INVALID_SAVED_ANSWERS", "历史 intake 答案无效。")
    result: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for item in raw_answers:
        if not isinstance(item, Mapping):
            raise IntakeError("INVALID_SAVED_ANSWERS", "历史 intake 答案无效。")
        question_id = item.get("question_id")
        if (
            not isinstance(question_id, str)
            or not question_id
            or len(question_id) > 80
            or question_id in seen_questions
        ):
            raise IntakeError("INVALID_SAVED_ANSWERS", "历史 intake 答案无效。")
        seen_questions.add(question_id)
        normalized: dict[str, Any] = {"question_id": question_id}
        for key, maximum in (
            ("question", 500),
            ("option_id", 80),
            ("label", 160),
            ("custom_text", MAX_CUSTOM_ANSWER_CHARACTERS),
        ):
            value = item.get(key)
            if value is not None:
                if not isinstance(value, str) or len(value) > maximum:
                    raise IntakeError("INVALID_SAVED_ANSWERS", "历史 intake 答案无效。")
                normalized[key] = value
        option_ids = item.get("option_ids")
        if option_ids is not None:
            if (
                not isinstance(option_ids, list)
                or len(option_ids) > MAX_OPTION_SELECTIONS
                or any(
                    not isinstance(option_id, str)
                    or not option_id
                    or len(option_id) > 80
                    for option_id in option_ids
                )
                or len(set(option_ids)) != len(option_ids)
            ):
                raise IntakeError("INVALID_SAVED_ANSWERS", "历史 intake 答案无效。")
            normalized["option_ids"] = list(option_ids)
        labels = item.get("labels")
        if labels is not None:
            if (
                not isinstance(labels, list)
                or len(labels) > MAX_OPTION_SELECTIONS
                or any(not isinstance(label, str) or len(label) > 160 for label in labels)
            ):
                raise IntakeError("INVALID_SAVED_ANSWERS", "历史 intake 答案无效。")
            normalized["labels"] = list(labels)
        result.append(normalized)
    return result


def canonical_answer_signature(raw_answers: Any) -> list[dict[str, Any]]:
    """Canonicalize an answer payload for immutable retry comparisons.

    Retry requests should not be able to change the choices attached to the
    original turn.  This helper intentionally does not resolve labels or
    question options; it only normalizes the transport shapes and lets the
    caller compare the resulting IDs/text with server-owned metadata.
    """

    signatures: dict[str, dict[str, Any]] = {}
    items = _iter_answer_items(raw_answers)
    if len(items) > MAX_ANSWER_COUNT:
        raise IntakeError("TOO_MANY_ANSWERS", "答案项过多。")
    for question_id, raw_value in items:
        if not question_id or len(question_id) > 80 or question_id in signatures:
            raise IntakeError("INVALID_ANSWER", "答案问题标识无效。")
        option_ids, custom_text = _raw_answer_parts(raw_value)
        if any(not option_id or len(option_id) > 80 for option_id in option_ids):
            raise IntakeError("INVALID_ANSWER", "答案选项标识无效。")
        if custom_text is not None and len(custom_text) > MAX_CUSTOM_ANSWER_CHARACTERS:
            raise IntakeError("CUSTOM_TOO_LONG", "自定义答案过长。", question_id=question_id)
        if not option_ids and custom_text is None:
            raise IntakeError("EMPTY_ANSWER", "答案不能为空。", question_id=question_id)
        signatures[question_id] = {
            "question_id": question_id,
            "option_ids": sorted(option_ids),
            **({"custom_text": custom_text} if custom_text is not None else {}),
        }
    return [signatures[key] for key in sorted(signatures)]


def answers_match_saved(raw_answers: Any, saved_answers: Any) -> bool:
    """Return whether a retry payload preserves server-saved choices."""

    try:
        submitted = canonical_answer_signature(raw_answers)
        saved = canonical_answer_signature(normalize_saved_answers(saved_answers))
    except IntakeError:
        return False
    return submitted == saved


def merge_prompt(
    original_content: str,
    intake: Mapping[str, Any] | None = None,
    answers: Iterable[Mapping[str, Any]] | None = None,
    *,
    action: str | None = None,
    task_type: str | None = None,
) -> str:
    """Append confirmed user preferences while preserving the exact request.

    The generated block is explicitly marked as user-provided context.  It is
    not a system instruction and cannot replace the original request.
    """

    if not isinstance(original_content, str) or not original_content.strip():
        raise IntakeError("INVALID_CONTENT", "任务内容不能为空。")
    record = intake or {}
    effective_task_type = task_type or record.get("task_type") or "general"
    label = TASK_TYPE_LABELS.get(str(effective_task_type), str(effective_task_type))
    normalized_action = normalize_action(action)
    if normalized_action in {"cancel", "delete"}:
        raise IntakeError("INTAKE_CANCELLED", "该追问已取消。")
    if normalized_action not in {"confirm", "skip", "run"}:
        raise IntakeError("INVALID_ACTION", "不支持的 intake 操作。")
    if normalized_action in {"skip", "run"}:
        # “跳过，直接执行” is an explicit request to preserve the legacy
        # prompt verbatim; metadata still records the task type/action for
        # audit and retry reconstruction.  Ignore any accidental answer data
        # supplied with the bypass action rather than turning “skip” into an
        # implicit confirmation.
        return original_content
    normalized_answers = normalize_saved_answers(list(answers or []))
    context = {
        "task_type": str(effective_task_type),
        "task_type_label": label,
        "action": normalized_action,
        "answers": normalized_answers,
    }
    encoded = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    return (
        "[已确认选项]\n"
        "以下内容是用户刚刚确认的任务偏好，仅用于帮助执行当前请求；"
        "若与原始请求冲突，应向用户说明取舍，不得丢弃原始请求。\n"
        + encoded
        + "\n\n[原始用户请求]\n"
        + original_content
    )


# Compatibility aliases make the small module convenient for callers that use
# noun-oriented names while keeping one implementation and one validation path.
classify_task_type = classify_task
create_intake = build_intake
validate_intake_answers = validate_answers
build_merged_prompt = merge_prompt


__all__ = [
    "INTAKE_ID_RE",
    "INTAKE_VERSION",
    "IntakeError",
    "IntakeOption",
    "IntakeQuestion",
    "MAX_OPTION_SELECTIONS",
    "INTAKE_ACTION_ALIASES",
    "QUESTION_BANK",
    "TASK_TYPE_LABELS",
    "build_intake",
    "build_merged_prompt",
    "answers_match_saved",
    "canonical_answer_signature",
    "classify_task",
    "classify_task_type",
    "content_digest",
    "create_intake",
    "intake_expired",
    "merge_prompt",
    "normalize_saved_answers",
    "normalize_action",
    "normalize_text",
    "public_intake",
    "questions_for",
    "validate_answers",
    "validate_intake_answers",
]
