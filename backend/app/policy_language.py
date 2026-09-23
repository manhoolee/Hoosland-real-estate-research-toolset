"""Narrow business-object disambiguation shared by ingress and egress.

Only the named object is replaced in a detection view. The rest of the turn
is still checked, so a legitimate project clause cannot authorize an appended
request for the assistant's configuration, secrets, or hidden instructions.
"""
import re


_BUSINESS_OBJECT = re.compile(
    r"(?:销售|去化|定价|估值|预测|测算|现金流|财务|投资回报|敏感性)(?:分析)?模型"
    r"(?:的?(?:名称|版本|参数|配置|假设))?|"
    r"(?:项目|工程|物业|施工|建材|营销)(?:的)?(?:供应商|服务商)(?:的?(?:名称|版本|配置|能力))?|"
    r"(?:项目|营销|销售|调研|测算|分析)(?:的)?(?:营销|销售|研究)?工具(?:清单|列表|用途)?|"
    r"(?:物业公司|项目公司|开发商|项目|销售团队)(?:的)?内部(?:管理)?规则|"
    r"(?:sales|forecasting|valuation|pricing|financial|cash[ -]?flow)\s+model(?:\s+(?:name|parameters?|assumptions?))?|"
    r"project[\s_-]*suppliers?(?:[\s_-]*and[\s_-]*their[\s_-]*capabilities)?",
    re.IGNORECASE,
)


def business_detection_view(value: str) -> str:
    return _BUSINESS_OBJECT.sub("业务对象", value)
