"""值快照：由 JSON 支撑的冻结记录在每个边界都返回深拷贝。"""
from dataclasses import dataclass
from typing import Any
import copy
import json


@dataclass(frozen=True)
class ValueRecord:
    _json: str

    @classmethod
    def from_dict(cls, value: dict):
        return cls(json.dumps(value, ensure_ascii=False, allow_nan=False))

    @property
    def data(self) -> dict:
        return json.loads(self._json)


class Item(ValueRecord): pass
class PlacedItem(ValueRecord): pass
class PalletState(ValueRecord): pass
class Candidate(ValueRecord): pass
class CandidateSet(ValueRecord): pass
class SelectionRequest(ValueRecord): pass
class SelectorResponse(ValueRecord): pass
class StepResult(ValueRecord): pass


@dataclass(frozen=True)
class CandidateGenerationResult:
    candidate_set: CandidateSet
    audit: ValueRecord
    timing: ValueRecord


def internal_item(item: dict) -> dict:
    result = copy.deepcopy(item)
    result['dimensions'] = [item['dimensions_mm'][k] for k in ('length', 'width', 'height')]
    return result


def restore_placed(records: list[dict]) -> list[dict]:
    """根据有序的不可变位姿恢复精确的支撑比例和载荷。

    数据集公开的载荷与比例已经过舍入，因此每一步都重新计算，避免将舍入值
    再次送入候选生成器。
    """
    placed = []
    by_id = {}
    def propagate(identifier, mass):
        p = by_id[identifier]
        p['supported_load_kg'] += mass
        for sid, fraction in p['supports']:
            propagate(sid, mass * fraction)
    for p in records:
        l, w, h = p['oriented_size_mm']
        x, y, z = (float(p['pose'][k]) for k in ('x_mm','y_mm','z_base_mm'))
        rec = dict(item_id=p['item_id'], item=internal_item(p), x0=x-l/2, x1=x+l/2,
                   y0=y-w/2, y1=y+w/2, z0=z, z1=z+h, yaw=p['pose']['yaw_deg'],
                   supports=[], supported_load_kg=0.0)
        areas = []
        if z > 0:
            for support in placed:
                if abs(support['z1'] - z) > 1e-6:
                    continue
                area = max(0, min(rec['x1'],support['x1'])-max(rec['x0'],support['x0'])) * max(0, min(rec['y1'],support['y1'])-max(rec['y0'],support['y0']))
                if area:
                    areas.append((support['item_id'], area))
        total = sum(a for _, a in areas)
        rec['supports'] = [(sid, a/total) for sid, a in areas]
        for sid, fraction in rec['supports']:
            propagate(sid, rec['item']['mass_kg'] * fraction)
        placed.append(rec)
        by_id[rec['item_id']] = rec
    return placed
