"""极值点/支撑层候选生成器，不使用隐藏语义或未来物料。"""
import copy
from collections import Counter
from time import perf_counter
from typing import Protocol
from ..domain import PalletState, CandidateSet, CandidateGenerationResult, ValueRecord, internal_item, restore_placed
from ..protocol import state_hash
from .constraints import candidate_points, evaluate_pose, pareto_front, select_diverse_topk


class CandidateGenerator(Protocol):
    name: str
    version: str
    def generate(self, state: PalletState) -> CandidateGenerationResult: ...


class ExtremePointGenerator:
    name = 'extreme_point_ems_style'
    version = '1.0.0'

    def __init__(self, config):
        self.config = copy.deepcopy(config)

    def generate(self, state):
        start = perf_counter()
        data = state.data
        if len(data['available_items']) != 1:
            raise ValueError('stage1A/B supports buffer_size=1 only')
        cfg = copy.deepcopy(self.config)
        cfg['container'] = data['container']
        item = internal_item(data['available_items'][0])
        placed = restore_placed(data['placed_items'])
        dims = item['dimensions']
        timings = dict(enumerate=0.0, filter=0.0, score=0.0, top_k=0.0)
        attempted = set()
        candidates = []
        rejection = Counter()
        duplicate = 0
        raw = 0
        for yaw in cfg['candidate_generator']['yaw_degrees']:
            l,w = (dims[0],dims[1]) if yaw == 0 else (dims[1],dims[0])
            t = perf_counter()
            points = candidate_points(placed,l,w,cfg['container'])
            timings['enumerate'] += perf_counter()-t
            for x,y,z in points:
                raw += 1
                key = (x,y,z,yaw)
                if key in attempted:
                    duplicate += 1
                    continue
                attempted.add(key)
                phases = {}
                candidate,reason = evaluate_pose(item,placed,x,y,z,l,w,yaw,cfg,_timing=phases)
                timings['filter'] += phases.get('filter',0)
                timings['score'] += phases.get('score',0)
                if candidate is None:
                    rejection[reason or 'unknown'] += 1
                else:
                    candidates.append(candidate)
        t = perf_counter()
        front = pareto_front(candidates)
        front_ids = {x['visible']['candidate_fingerprint'] for x in front}
        if cfg.get('topk_mode','diverse_v1') == 'diverse_v1':
            # 除阶段 0 的分层字段外，还显式记录偏航角和帕累托集合成员关系。
            for c in candidates:
                c['stratum'] = (*c['stratum'],c['visible']['pose']['yaw_deg'],c['visible']['candidate_fingerprint'] in front_ids)
        top = select_diverse_topk(candidates,cfg['candidate_generator']['top_k'])
        timings['top_k'] = perf_counter()-t
        top_ids = {c['visible']['candidate_fingerprint'] for c in top}
        best = max(candidates,key=lambda x:(x['geometry_score'],x['visible']['candidate_id'])) if candidates else None
        audit = {
            'rejection_histogram':dict(sorted(rejection.items())),
            'raw_candidate_count':raw, 'physical_valid_count':len(candidates),
            'duplicate_count':duplicate,'pareto_candidate_count':len(front), 'returned_count':len(top),
            'pareto_candidate_fingerprints':sorted(front_ids),
            'pareto_recall_at_k':round(len(top_ids&front_ids)/len(front_ids),6) if front else 0.0,
            'geometry_oracle_fingerprint':best['visible']['candidate_fingerprint'] if best else None,
            'geometry_oracle_score':best['geometry_score'] if best else None,
            # V0.1 指标是存在性标记，不是对全部 epsilon 最优候选计算的召回率。
            'epsilon_optimal_recall_at_k':bool(best and any(best['geometry_score']-c['geometry_score']<=cfg['candidate_generator']['epsilon'] for c in top)),
            'strata_count':len({c['stratum'] for c in candidates}),
            'returned_strata_count':len({c['stratum'] for c in top}),
        }
        timings['total'] = perf_counter()-start
        h = state_hash(data['container'],data)
        cset = dict(candidate_set_id=f"ONLINE_{data['request_id']}",physical_state_hash=h,
                    candidates=[copy.deepcopy(c['visible']) for c in top],generator=self.name,
                    version=self.version,topk_mode=cfg.get('topk_mode','diverse_v1'))
        return CandidateGenerationResult(CandidateSet.from_dict(cset),ValueRecord.from_dict(audit),ValueRecord.from_dict(timings))
