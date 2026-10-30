"""选择器接收独立的公开请求；特权输入只能通过构造函数传入。"""
from typing import Protocol
from ..planner.scoring import geometry_score, pareto_candidates
from ..evaluation.state import apply_candidate
from ..evaluation.semantic import semantic_evaluation
from ..domain import restore_placed


class Selector(Protocol):
    name: str
    privileged_input: bool
    def select(self, request, *, rng, memories=None) -> dict: ...


def response(request, candidate, reason):
    return dict(schema_version='pallet_selector_response_v1',request_id=request['request_id'],
                state_hash=request['state_hash'],candidate_id=candidate['candidate_id'],confidence=None,reason=reason)


class Baseline:
    privileged_input = False
    future_visible = False
    def __init__(self, name, *, rules=None, oracle=None):
        self.name = name
        self.rules = rules
        self.oracle = oracle
        self.privileged_input = name in ('handcrafted_rule','candidate_oracle')

    def select(self, request, *, rng, memories=None):
        candidates = request['candidates']
        if not candidates:
            raise ValueError('no feasible candidates')
        if self.name == 'random_valid':
            choice = rng.choice(candidates)
        elif self.name == 'lowest':
            choice = min(candidates,key=lambda c:(c['pose']['z_base_mm'],c['resulting_geometry']['max_height_mm'],c['resulting_geometry']['center_of_mass_offset_mm'],c['candidate_id']))
        elif self.name == 'geometry_greedy':
            choice = min(candidates,key=lambda c:(-geometry_score(c),c['candidate_id']))
        elif self.name == 'pareto_greedy':
            # 先按帕累托集合筛选，再依次比较高度、支撑、平衡、紧凑度和 ID；这不同于加权求和。
            choice = min(pareto_candidates(candidates),key=lambda c:(
                -c['geometry_score_components']['height'],-c['geometry_score_components']['stability'],
                -c['geometry_score_components']['balance'],-c['geometry_score_components']['compactness'],c['candidate_id']))
        elif self.name == 'candidate_oracle':
            if self.oracle is None: raise ValueError('CandidateOracle is fixed-case only')
            choice = next(c for c in candidates if c['candidate_id']==self.oracle['oracle_candidate_id'])
        elif self.name == 'handcrafted_rule':
            if not self.rules: raise ValueError('HandcraftedRule requires explicit privileged rules')
            def rank(c):
                after = restore_placed(apply_candidate(request,c))
                violations=[]; scores=[]
                for rule in self.rules:
                    values,errors=semantic_evaluation(after,rule,{'container':request['container']})
                    violations.extend(errors); scores.extend(values.values())
                return (len(violations),-sum(scores)/max(len(scores),1),-geometry_score(c),c['candidate_id'])
            choice = min(candidates,key=rank)
        else:
            raise ValueError(f'unknown selector: {self.name}')
        return response(request,choice,self.name)


NAMES = ('random_valid','lowest','geometry_greedy','pareto_greedy','handcrafted_rule','candidate_oracle')
REGISTRY = {name:(lambda name=name, **kwargs: Baseline(name,**kwargs)) for name in NAMES}

def register(name, factory):
    if name in REGISTRY: raise ValueError('selector already registered')
    REGISTRY[name]=factory

def make_selector(name, **kwargs):
    if name not in REGISTRY: raise ValueError(f'unknown selector {name}')
    return REGISTRY[name](**kwargs)
