"""共享运行器；选择器不会收到Repository、评价器、数据划分或未来物料。"""
import copy
import random
from pathlib import Path
from time import perf_counter
from ..protocol import build_request,resolve_response,state_hash
from ..selectors.baselines import make_selector
from ..environment import PalletEnvironment
from ..evaluation.metrics import evaluate_fixed
from ..evaluation.state import state_metrics
from ..evaluation.semantic import semantic_evaluation
from ..domain import restore_placed
from ..logging.artifacts import dump,digest


def method_rng(seed,method,identifier):
    return random.Random(int(digest([seed,method,identifier])[:16],16))


def base_event(experiment,track,method,scenario_id,split,index,request,cset,selector,before):
    return dict(schema_version='pallet_step_v1',experiment_id=experiment.identifier,track=track,method=method,
        scenario_id=scenario_id,split=split,step_index=index,request_id=before['request_id'],
        state_hash=state_hash(before['container'],before),candidate_set_id=cset['candidate_set_id'],
        privileged_input=bool(selector.privileged_input),future_visible=bool(getattr(selector,'future_visible',False)),
        request=request,candidate_set=cset,selector_response=None,submitted_response=None,before=before,after=before,
        fallback=False,error=None,committed=False,termination_reason=None,candidate_id=None,audit={},timing={},metrics={},metrics_before=state_metrics(before['container'],before['placed_items']),model_trace={})


def selector_trace(selector):
    return copy.deepcopy(getattr(selector,'last_trace',{}) or {})


def trace_metrics(trace):
    keys=('vlm_response_valid','attempt_count','repair_count','cache_hit','input_tokens','output_tokens',
          'api_latency_s','estimated_cost','leakage_hit_count','selected_display_position','error_category',
          'prompt_version','prompt_sha256','mapping_sha256')
    return {k:trace[k] for k in keys if k in trace}


def metric_identity(experiment,track,selector,sid,split):
    return dict(experiment_id=experiment.identifier,track=track,method=selector.name,scenario_id=sid,
                split=split,privileged_input=bool(selector.privileged_input),future_visible=bool(getattr(selector,'future_visible',False)))


class FixedCaseRunner:
    def __init__(self,repository,experiment):
        self.repo=repository;self.exp=experiment

    def run(self,case_ids,methods):
        for cid in case_ids:
            case=self.repo.get_decision_case(cid)
            scenario=self.repo.get_scenario(case['base_scenario_id'])
            cset=self.repo.get_candidate_set(case['candidate_set_id'])
            req=build_request(scenario['container'],case,cset,'workspace.png','candidates_montage.png')
            # 现有固定视图是只读产物，此处解析路径供后续选择器使用。
            req['visual_inputs']={k:str(self.repo.root/'views/rendered'/cid/name) for k,name in [('workspace_image','workspace.png'),('candidate_montage','candidates_montage.png')]}
            before=dict(container=scenario['container'],placed_items=case['placed_items'],available_items=case['available_items'],
                        request_id=cid,step_index=case['step_index'],instruction_text=case['instruction_text'])
            split=self.repo.split_for(cid)
            for method in methods:
                kwargs={}
                if method=='candidate_oracle':kwargs['oracle']=self.repo.get_oracle(cid)
                if method=='handcrafted_rule':kwargs['rules']=self.repo.get_rules(scenario['scenario_id'])
                selector=make_selector(method,**kwargs)
                event=base_event(self.exp,'fixed',method,scenario['scenario_id'],split,case['step_index'],req,cset,selector,before)
                t=perf_counter()
                try:
                    if getattr(selector,'requires_images',False):
                        from ..visualization.renderer import prepare_visual_request
                        req=prepare_visual_request(req,self.exp.root/'selector_inputs'/method/cid)
                        event['request']=req
                    submitted=selector.select(copy.deepcopy(req),rng=method_rng(self.exp.cfg['seed'],method,cid),memories=None)
                    event['submitted_response']=submitted
                    chosen=resolve_response(req,submitted)
                    resolved=submitted
                except Exception as exc:
                    event['model_trace']=selector_trace(selector)
                    event['error']=f'{type(exc).__name__}: {exc}'
                    if self.exp.cfg['fallback_policy']=='abort':
                        event['termination_reason']='invalid_selector_response'
                        event['timing']={'selection':perf_counter()-t,'generation':0.0}
                        self.exp.append(event)
                        self.exp.metric({**metric_identity(self.exp,'fixed',selector,scenario['scenario_id'],split),
                            'decision_case_id':cid,'candidate_set_id':cset['candidate_set_id'],'candidate_id':None,
                            'invalid_selector_response':True,'fallback':False,'oracle_hit':False,
                            'selection_time_s':event['timing']['selection'],'generation_time_s':0.0,
                            **trace_metrics(event['model_trace'])})
                        continue
                    resolved=make_selector('geometry_greedy').select(req,rng=random.Random(0))
                    chosen=resolve_response(req,resolved);event['fallback']=True
                elapsed=perf_counter()-t
                event['model_trace']=selector_trace(selector)
                # 普通选择器只有完成选择后，才能在此处使用隐藏答案进行评价。
                oracle=self.repo.get_oracle(cid)
                metrics,after=evaluate_fixed(req,chosen,oracle)
                metrics.update(selection_time_s=elapsed,generation_time_s=0.0,fallback=event['fallback'])
                metrics.update(trace_metrics(event['model_trace']))
                after_state={**before,'placed_items':after,'available_items':[]}
                event.update(selector_response=resolved,after=after_state,committed=False,candidate_id=chosen['candidate_id'],
                             timing={'selection':elapsed,'generation':0.0},metrics=metrics)
                self.exp.append(event)
                self.exp.metric({**metric_identity(self.exp,'fixed',selector,scenario['scenario_id'],split),
                    'decision_case_id':cid,'candidate_set_id':cset['candidate_set_id'],'candidate_id':chosen['candidate_id'],**metrics})
        return self.exp.decisions


class EpisodeRunner:
    def __init__(self,repository,generator,experiment):
        self.repo=repository;self.generator=generator;self.exp=experiment

    def run(self,scenario_id,method,*,max_steps=None,render=False,selector=None):
        if method=='candidate_oracle':raise ValueError('CandidateOracle cannot run online episodes')
        rules=self.repo.get_rules(scenario_id) if method=='handcrafted_rule' else None
        selector=selector or make_selector(method,**({'rules':rules} if rules is not None else {}))
        env=PalletEnvironment(self.repo,self.generator,self.exp.cfg['fallback_policy'])
        env.reset(scenario_id,max_steps=max_steps)
        split=self.repo.split_for(scenario_id)
        out=self.exp.root/'episodes'/method/scenario_id
        out.mkdir(parents=True,exist_ok=False)
        (out/'steps.jsonl').touch()
        times=[];selection_times=[];fallbacks=0;geometry_errors=0;events=[]
        rng=method_rng(self.exp.cfg['seed'],method,scenario_id)
        while not env.done:
            before=env.snapshot().data
            try:
                generation=env.generate_candidates()
            except Exception as exc:
                env.done=True;env.termination_reason='internal_error'
                cset=dict(candidate_set_id=f"ERROR_{before['request_id']}",candidates=[])
                event=base_event(self.exp,'episode',method,scenario_id,split,env.step_index,None,cset,selector,before)
                event.update(error=f'{type(exc).__name__}: {exc}',termination_reason='internal_error')
                event['metrics']=state_metrics(before['container'],before['placed_items'])
                self.exp.append(event,out);events.append(event);break
            cset=generation.candidate_set.data
            event=base_event(self.exp,'episode',method,scenario_id,split,env.step_index,None,cset,selector,before)
            event.update(audit=generation.audit.data,timing=generation.timing.data)
            times.append(generation.timing.data['total'])
            if env.done:
                event['termination_reason']=env.termination_reason
                event['metrics']=state_metrics(before['container'],before['placed_items'])
                self.exp.append(event,out);events.append(event);break
            req=env.selection_request();event['request']=req
            t=perf_counter()
            try:
                if getattr(selector,'requires_images',False):
                    from ..visualization.renderer import prepare_visual_request
                    req=prepare_visual_request(req,out/'selector_inputs'/before['request_id'])
                    event['request']=req
                submitted=selector.select(copy.deepcopy(req),rng=rng,memories=None)
            except Exception as exc:
                submitted={};event['error']=f'{type(exc).__name__}: {exc}'
            event['model_trace']=selector_trace(selector)
            elapsed=perf_counter()-t;selection_times.append(elapsed)
            try:
                result=env.step(submitted).data
            except Exception as exc:
                env.done=True;env.termination_reason='internal_error'
                event.update(submitted_response=submitted,error=f'{type(exc).__name__}: {exc}',termination_reason='internal_error')
                event['metrics']=state_metrics(before['container'],before['placed_items'])
                self.exp.append(event,out);events.append(event);break
            event.update(submitted_response=submitted,selector_response=result['response'],after=result['after'],
                         fallback=result['fallback'],committed=result['committed'],termination_reason=result['termination_reason'],
                         error=event['error'] or result['error'],candidate_id=result['candidate']['candidate_id'] if result['candidate'] else None)
            event['timing']['selection']=elapsed
            geometry_errors+=len(result['geometry_errors']);fallbacks+=result['fallback']
            event['metrics']=state_metrics(before['container'],result['after']['placed_items'])
            event['metrics'].update(trace_metrics(event['model_trace']))
            # 动作提交后才计算隐藏在线规则反馈，不读取缓存的Decision Case Oracle。
            if result['committed']:
                evaluation_rules=self.repo.get_rules(scenario_id)
                values=[];violations=[]
                for rule in evaluation_rules:
                    scores,errors=semantic_evaluation(restore_placed(result['after']['placed_items']),rule,{'container':before['container']})
                    values.extend(scores.values());violations.extend(errors)
                event['metrics'].update(soft_utility=sum(values)/max(1,len(values)),semantic_hard_violations=len(violations),hard_violations=len(result['geometry_errors']))
            self.exp.append(event,out);events.append(event)
        final=env.snapshot().data
        metrics=state_metrics(final['container'],final['placed_items'])
        metrics.update(requested_count=len(env.items),placed_item_ratio=len(env.placed)/len(env.items),
                       completed=env.termination_reason=='all_items_placed',termination_reason=env.termination_reason,
                       hard_violations=geometry_errors,fallback_count=fallbacks,
                       generation_time_s=sum(times),selection_time_s=sum(selection_times),
                       generation_p50_s=sorted(times)[len(times)//2] if times else 0,
                       max_steps=max_steps)
        for k in ('soft_utility','semantic_hard_violations'):
            metrics[k]=next((e['metrics'][k] for e in reversed(events) if k in e['metrics']),None)
        row={**metric_identity(self.exp,'episode',selector,scenario_id,split),**metrics}
        self.exp.metric(row)
        dump(out/'metrics.json',row)
        dump(out/'episode.json',dict(schema_version='pallet_episode_v1',scenario_id=scenario_id,method=method,
             initial_scenario=env.scenario,termination_reason=env.termination_reason,final_state=final,metrics=row,
             core_result_sha256=digest([e for e in self.exp.events if e['track']=='episode' and e['method']==method and e['scenario_id']==scenario_id])))
        if render:
            from ..visualization.renderer import render_episode
            try:render_episode(out)
            except Exception as exc:dump(out/'render_error.json',dict(error=f'{type(exc).__name__}: {exc}'))
        return row
