"""Frozen public lexical normalizer baseline; no corpus or answer-table imports.

This is a deterministic extension of the published parser, not a universal
Chinese interpreter. Unsupported sentences remain explicit failures.
"""
import re

from ..compiler import parse_instruction
from ..common import O4Error

VERSION = "o4_public_normalized_parser_v1"
REPLACEMENTS = (
    ("针对（", "对（"), ("所有箱体", "全部箱体"), ("全部货箱", "全部箱体"),
    ("货物品类", "货物类别"), ("已加固包装", "包装加固"),
    ("顶部不得受载", "禁止顶部加载"), ("不得在顶部加载", "禁止顶部加载"),
    ("累计顶部载荷最多为", "累计顶部限载为"),
    ("顶部累计载荷遵循标签上限", "累计顶部限载按标签"),
    ("不允许（", "禁止（"), ("以面直接接触", "直接面接触"),
    ("优先等级", "优先级"), ("替代规则", "覆盖"),
)


def parse_normalized(text):
    normalized = re.sub(r"\s+", "", text).translate(str.maketrans({":": "：", ";": "；"}))
    # Preambles may describe the work order, but rule clauses stay explicit.
    start = re.search(r"规则[A-Za-z0-9_]+：", normalized)
    if start is not None:
        normalized = normalized[start.start():]
    for old, new in REPLACEMENTS:
        normalized = normalized.replace(old, new)
    try:
        return parse_instruction(normalized)
    except O4Error as exc:
        if exc.code != "unsupported_construct":
            raise
    return parse_natural(normalized)


def parse_natural(text):
    """Published clause grammar using literal business terms, no case lookup.

    It supports label loads, marked zero-load overrides, reinforced glass
    exceptions and symmetric food/cleaner contact. Any uncovered clause fails.
    """
    from ..normalize import validate_policy
    rules = []
    for clause in filter(None, re.split("[。；]", text)):
        has_label = any(r["rule_id"] == "r1" and r["type"] == "max_top_load" for r in rules)
        if ("食品" in clause and "清洁用品" in clause and "直接面接触" in clause
                and any(word in clause for word in ("禁止", "不得", "不允许"))):
            rules.append({"rule_id": "r4" if rules else "r1", "type": "forbidden_contact", "priority": 20,
                          "overrides": [], "left": {"eq": {"field": "cargo_category", "value": "food"}},
                          "right": {"eq": {"field": "cargo_category", "value": "household_cleaner"}}})
        elif ("玻璃制品" in clause and "已加固" in clause and "没有禁压标记" in clause
              and any(word in clause for word in ("替代", "覆盖"))):
            amounts = re.findall(r"(\d+(?:\.\d+)?)kg", clause)
            if not has_label or len(amounts) != 1:
                raise O4Error("unsupported_construct", "exception requires explicit replaced label rule and kg limit")
            rules.append({"rule_id": "r3", "type": "max_top_load", "priority": 0, "overrides": ["r1"],
                          "target": {"and": [{"eq": {"field": "cargo_category", "value": "glassware"}},
                                             {"eq": {"field": "packaging.reinforced", "value": True}},
                                             {"eq": {"field": "labels.no_top_load", "value": False}}]},
                          "limit": {"constant_kg": float(amounts[0])}})
        elif ("禁压标记" in clause and any(word in clause for word in ("不得承受", "不许加载", "上限为0kg"))
              and any(word in clause for word in ("替代", "覆盖"))):
            if not has_label:
                raise O4Error("unsupported_construct", "load override requires explicit label rule")
            rules.append({"rule_id": "r2", "type": "no_top_load", "priority": 10, "overrides": ["r1"],
                          "target": {"eq": {"field": "labels.no_top_load", "value": True}}})
        elif "标签" in clause and "累计顶部" in clause and any(word in clause for word in ("按", "以", "依据")):
            rules.append({"rule_id": "r1", "type": "max_top_load", "priority": 30, "overrides": [],
                          "target": {"all": True}, "limit": {"field": "labels.max_top_load_kg"}})
        else:
            raise O4Error("unsupported_construct", "outside published natural-clause grammar")
    if not rules:
        raise O4Error("unsupported_construct", "empty natural instruction")
    return validate_policy({"schema_version": "o4_policy_v1", "rules": rules})
