"""Declared private policy specifications and independent public text forms.

No parser/executor is used to author references. Synthetic templates are a
controlled holdout, not independently authored human language or a blind test.
"""
import copy

from ..fixtures import eq, policy, rule, render_policy

CORE = ("label", "marked", "contact", "exception")
COMBINATIONS = ("contact_exclusion", "mass_override")


def specification(family):
    label = rule("r1", limit="label", priority=30)
    marked = rule("r2", "no_top_load", eq("labels.no_top_load", True), priority=10, overrides=("r1",))
    if family == "label":
        return policy([label])
    if family == "marked":
        return policy([label, marked])
    if family == "contact":
        return policy([rule("r1", "forbidden_contact")])
    if family == "exception":
        target = {"and": [eq("cargo_category", "glassware"), eq("packaging.reinforced", True),
                          eq("labels.no_top_load", False)]}
        return policy([label, marked, rule("r3", target=target, limit=2, priority=0, overrides=("r1",))])
    if family == "contact_exclusion":
        contact = rule("r3", "forbidden_contact")
        contact["left"] = {"and": [eq("cargo_category", "food"), {"not": eq("packaging.reinforced", True)}]}
        return policy([label, marked, contact])
    if family == "mass_override":
        target = {"and": [{"or": [eq("cargo_category", "glassware"), eq("cargo_category", "electronics")]},
                          {"ge": {"field": "mass_kg", "value": 3}}, eq("labels.no_top_load", False)]}
        return policy([label, marked, rule("r3", target=target, limit=1.5, priority=0, overrides=("r1",))])
    raise ValueError("unknown policy family")


def instruction(family, style):
    text = render_policy(specification(family))
    if style.startswith("natural_"):
        bank = {
            "natural_development": {
                "label": "所有箱体都要按各自标签执行累计顶部限载。",
                "marked": "所有箱体都要按各自标签执行累计顶部限载。带禁压标记的箱体不得承受顶部载荷，这项要求替代这些箱体的标签限值。",
                "contact": "食品与清洁用品可以同托盘，但禁止直接面接触。",
                "exception": "所有箱体都要按各自标签执行累计顶部限载。带禁压标记的箱体不得承受顶部载荷，这项要求替代这些箱体的标签限值。仅玻璃制品且包装已加固且没有禁压标记的箱体，累计顶部限载改为2 kg，替代这些箱体的标签限值。"},
            "natural_calibration": {
                "label": "每个箱体的累计顶部载荷上限，以它自己的标签限值为准。",
                "marked": "每个箱体的累计顶部载荷上限，以它自己的标签限值为准。对于有禁压标记的箱体，顶部不许加载，原标签限值由这项禁压要求替代。",
                "contact": "允许食品和清洁用品共用托盘，不过两类箱体不得直接面接触。",
                "exception": "每个箱体的累计顶部载荷上限，以它自己的标签限值为准。对于有禁压标记的箱体，顶部不许加载，原标签限值由这项禁压要求替代。只有包装已加固且没有禁压标记的玻璃制品箱体，累计顶部限载改为2 kg，覆盖其原标签限值。"},
            "natural_heldout": {
                "label": "码垛时，累计顶部载荷应依据每个箱体自身标签所注明的限值控制。",
                "marked": "码垛时，累计顶部载荷应依据每个箱体自身标签所注明的限值控制。若箱体带有禁压标记，其顶部载荷上限为0 kg，这条要求覆盖该箱的标签限值。",
                "contact": "同一托盘可以容纳食品及清洁用品，然而两者不允许形成直接面接触。",
                "exception": "码垛时，累计顶部载荷应依据每个箱体自身标签所注明的限值控制。若箱体带有禁压标记，其顶部载荷上限为0 kg，这条要求覆盖该箱的标签限值。玻璃制品中仅限包装已加固且没有禁压标记的箱体，将累计顶部限载设为2 kg并替代其标签限值。"},
        }
        return bank[style][family]
    if style == "canonical":
        return text
    if style == "development":
        return "作业要求如下：" + text.replace("全部箱体", "所有箱体").replace("禁止顶部加载", "不得在顶部加载")
    if style == "calibration":
        return "请遵守以下要求：" + text.replace("货物类别", "货物品类").replace("累计顶部限载为", "累计顶部载荷最多为")
    if style == "heldout":
        return ("本次码垛请执行：" + text.replace("对（", "针对（").replace("全部箱体", "全部货箱")
                .replace("禁止顶部加载", "顶部不得受载").replace("累计顶部限载按标签", "顶部累计载荷遵循标签上限")
                .replace("禁止（", "不允许（").replace("直接面接触", "以面直接接触")
                .replace("优先级", "优先等级").replace("覆盖", "替代规则"))
    raise ValueError("unknown text style")


def split_records(split):
    style = {"development": "development", "calibration": "calibration", "test": "heldout"}[split]
    rows = [(family, "canonical", "control") for family in CORE]
    rows += [(family, style, "surface") for family in CORE]
    rows += [(family, "natural_" + style, "expression") for family in CORE]
    if split == "test":
        rows += [(family, "canonical", "combination") for family in COMBINATIONS]
    return copy.deepcopy(rows)
