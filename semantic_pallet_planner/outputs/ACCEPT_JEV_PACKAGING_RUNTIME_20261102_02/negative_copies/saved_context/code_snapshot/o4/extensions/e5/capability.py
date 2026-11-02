"""Reject explicitly unsupported public orientation requirements, not parse answers."""
import re
from ...common import O4Error


def check_instruction(text):
    if re.search(r'allowed_yaw|(?<![A-Za-z0-9_])(?:roll|pitch)(?![A-Za-z0-9_])|(?:180|270)\s*(?:°|度)|yaw\s*(?:=|为|:|：)\s*(?:180|270)|标签[^。\n]*朝外|侧面[^。\n]*朝',text,re.IGNORECASE):
        raise O4Error('unsupported_construct','E5 supports upright top labels and yaw0/90 only; orientation business rules are deferred')
