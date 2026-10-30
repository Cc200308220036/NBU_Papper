"""确定性在线环境：只暴露当前物料，使用局部 ID，并独立校验每次提交。"""
import copy
import random
from .domain import PalletState, StepResult
from .protocol import build_request, resolve_response, state_hash
from .evaluation.geometry_oracle import check_candidate
from .evaluation.state import apply_candidate
from .selectors.baselines import make_selector


class PalletEnvironment:
    def __init__(self, repository, generator, fallback_policy='geometry_greedy'):
        if fallback_policy not in ('geometry_greedy','abort'): raise ValueError('invalid fallback_policy')
        self.repository=repository; self.generator=generator; self.fallback_policy=fallback_policy
        self.done=True; self.termination_reason=None

    def reset(self, scenario_id, max_steps=None):
        self.scenario=self.repository.get_scenario(scenario_id)
        if self.scenario['buffer_size']!=1: raise ValueError('buffer_size=3 is deferred; stage1A/B requires 1')
        if max_steps is not None and max_steps<1: raise ValueError('max_steps must be positive')
        by_id={i['item_id']:i for i in self.scenario['items']}
        self.items=[by_id[i] for i in self.scenario['arrival_order']]
        self.placed=[]; self.step_index=0; self.max_steps=max_steps
        self.done=False; self.termination_reason=None; self._generation=None; self._request=None
        return self.observe()

    def snapshot(self):
        available=[] if self.step_index>=len(self.items) else [copy.deepcopy(self.items[self.step_index])]
        return PalletState.from_dict(dict(container=self.scenario['container'],placed_items=self.placed,
            available_items=available,step_index=self.step_index,
            request_id=f"{self.scenario['scenario_id']}_STEP_{self.step_index:03d}",
            instruction_text=self.scenario['instruction']['text']))

    def observe(self):
        return self.snapshot().data

    def generate_candidates(self):
        if self.done: raise ValueError('episode has terminated')
        if self._generation is None:
            self._generation=self.generator.generate(self.snapshot())
            cs=self._generation.candidate_set.data
            if not cs['candidates']:
                self.done=True; self.termination_reason='no_feasible_candidate'
            else:
                case=self.observe(); case['decision_case_id']=case['request_id']
                self._request=build_request(self.scenario['container'],case,cs,'workspace.png','candidates_montage.png')
        return self._generation

    def selection_request(self):
        self.generate_candidates()
        if self._request is None: raise ValueError('no feasible candidate')
        return copy.deepcopy(self._request)

    def step(self, selector_response):
        if self.done: raise ValueError('episode has terminated')
        self.generate_candidates()
        if self.done: raise ValueError('no feasible candidate')
        before=self.snapshot().data
        fallback=False; error=None; actual_response=copy.deepcopy(selector_response)
        try:
            candidate=resolve_response(self._request,selector_response)
        except (ValueError,TypeError,KeyError) as exc:
            error=str(exc)
            if self.fallback_policy=='abort':
                self.done=True; self.termination_reason='invalid_selector_response'
                return StepResult.from_dict(dict(committed=False,fallback=False,error=error,response=None,
                    candidate=None,before=before,after=before,done=True,termination_reason=self.termination_reason,geometry_errors=[]))
            fallback=True
            actual_response=make_selector('geometry_greedy').select(self._request,rng=random.Random(0))
            candidate=resolve_response(self._request,actual_response)
        errors=check_candidate(self._request,self.scenario,candidate)
        if errors:
            self.done=True; self.termination_reason='internal_error'
            return StepResult.from_dict(dict(committed=False,fallback=fallback,error='independent geometry rejection',
                response=actual_response,candidate=candidate,before=before,after=before,done=True,
                termination_reason=self.termination_reason,geometry_errors=errors))
        self.placed=apply_candidate(self._request,candidate)
        self.step_index+=1
        if self.step_index==len(self.items):
            self.done=True; self.termination_reason='all_items_placed'
        elif self.max_steps is not None and self.step_index>=self.max_steps:
            self.done=True; self.termination_reason='max_steps_reached'
        after=self.snapshot().data
        self._request=None; self._generation=None
        return StepResult.from_dict(dict(committed=True,fallback=fallback,error=error,response=actual_response,
            candidate=candidate,before=before,after=after,done=self.done,termination_reason=self.termination_reason,
            geometry_errors=[],state_hash_after=state_hash(after['container'],after)))
