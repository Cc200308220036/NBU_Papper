"""根据请求和响应重新计算数值证据，并校验不可变源数据。"""
import json
import math
from pathlib import Path
from collections import defaultdict
from ..logging.artifacts import file_hash,digest,core_event,dump,dataset_checksums
from ..validation import validate
from ..protocol import state_hash,resolve_response
from ..domain import PalletState
from ..repository import DatasetRepository
from ..config import generator_config
from ..planner.generator import ExtremePointGenerator
from .geometry_oracle import check_candidate
from .state import apply_candidate,state_metrics
from .metrics import evaluate_fixed


def _same_metric(recorded, recomputed):
    """允许 JSON 浮点往返造成的末位误差，其他指标仍要求精确一致。"""
    if isinstance(recorded, bool) or isinstance(recomputed, bool):
        return recorded is recomputed
    if isinstance(recorded, (int, float)) and isinstance(recomputed, (int, float)):
        return math.isclose(recorded, recomputed, rel_tol=0.0, abs_tol=1e-9)
    return recorded == recomputed


def validate_experiment(directory,regenerate=False):
    root=Path(directory).resolve();cfg=json.loads((root/'config.snapshot.json').read_text());manifest=json.loads((root/'manifest.json').read_text())
    validate('config',cfg);validate('manifest',manifest)
    failures=[];checked=0;geometry_failures=0;request_leaks=0;events=[];returned_checked=0;returned_failures=0
    if manifest['config_sha256']!=digest(cfg):failures.append('config hash')
    if manifest['dataset_checksums']!=dataset_checksums(cfg['dataset']):failures.append('dataset changed')
    for rel,expected in manifest['result_file_checksums'].items():
        if not (root/rel).is_file() or file_hash(root/rel)!=expected:failures.append(f'artifact checksum: {rel}')
    repo=DatasetRepository(cfg['dataset']);generator=ExtremePointGenerator(generator_config(cfg))
    previous={};observed=defaultdict(list)
    for line in (root/'steps.jsonl').read_text().splitlines():
        event=json.loads(line);validate('step',event);events.append(core_event(event));checked+=1
        before=event['before'];req=event['request'];key=(event['method'],event['scenario_id'])
        if event['state_hash']!=state_hash(before['container'],before):failures.append(f'state hash {checked}')
        if req:
            forbidden={'oracle_candidate_id','ground_truth_rule','split','source_order_id','semantic_decision_required','candidate_evaluations'}
            def keys(v):
                if isinstance(v,dict):
                    for k,x in v.items():
                        yield k;yield from keys(x)
                elif isinstance(v,list):
                    for x in v:yield from keys(x)
            if forbidden.intersection(keys(req)):request_leaks+=1
            if req['placed_items']!=before['placed_items'] or req['available_items']!=before['available_items'] or req['container']!=before['container']:
                failures.append(f'request/state mismatch {checked}')
        if event['track']=='episode':
            for candidate in event['candidate_set']['candidates']:
                returned_checked += 1
                returned_failures += len(check_candidate(before, {'container':before['container']}, candidate))
            observed[key].append(event)
            scenario=repo.get_scenario(event['scenario_id'])
            idx=event['step_index']
            expected_item=scenario['arrival_order'][idx] if idx<len(scenario['arrival_order']) else None
            if [x['item_id'] for x in before['available_items']]!=([expected_item] if expected_item else []):failures.append(f'arrival visibility {checked}')
            if key in previous:
                if before!=previous[key]:failures.append(f'state continuity {checked}')
            elif before['placed_items'] or idx!=0:failures.append(f'initial state {checked}')
            previous[key]=event['after']
            if regenerate:
                generated=generator.generate(PalletState.from_dict(before)).candidate_set.data
                if generated!=event['candidate_set']:failures.append(f'regenerated CSET {checked}')
        else:
            case=repo.get_decision_case(event['request_id'])
            if repo.get_candidate_set(case['candidate_set_id'])!=event['candidate_set']:failures.append(f'fixed CSET changed {checked}')
        if event['candidate_id'] and req:
            c=resolve_response(req,event['selector_response'])
            if c['candidate_id']!=event['candidate_id']:failures.append(f'selected ID {checked}')
            errs=check_candidate(req,{'container':before['container']},c);geometry_failures+=len(errs)
            after=apply_candidate(req,c)
            if after!=event['after']['placed_items']:failures.append(f'commit state {checked}')
            if event['track']=='fixed':
                metrics,_=evaluate_fixed(req,c,repo.get_oracle(event['request_id']))
            else:metrics=state_metrics(before['container'],after)
            for k,v in metrics.items():
                if not _same_metric(event['metrics'].get(k),v):failures.append(f'metric {checked}:{k}')
    if digest(events)!=manifest['core_result_sha256']:failures.append('core result hash')
    for key,group in observed.items():
        out=root/'episodes'/key[0]/key[1]
        saved=[json.loads(x) for x in (out/'steps.jsonl').read_text().splitlines()]
        if saved!=group:failures.append(f'episode log differs: {key}')
        episode=json.loads((out/'episode.json').read_text())
        if episode['final_state']!=group[-1]['after']:failures.append(f'episode final state: {key}')
        if (out/'render_manifest.json').exists():
            render=json.loads((out/'render_manifest.json').read_text())
            for mapping,e in zip(render['label_mapping'],group):
                expected={c['candidate_id']:c['display_label'] for c in e['request']['candidates']} if e['request'] else {}
                if mapping['candidate_labels']!=expected:failures.append(f'render mapping: {key}')
            if render['numeric_core_sha256']!=episode['core_result_sha256']:failures.append(f'render core: {key}')
    result=dict(status='PASS' if not failures and not geometry_failures and not request_leaks and not returned_failures else 'FAIL',
        events=checked,geometry_failures=geometry_failures,request_leaks=request_leaks,
        returned_candidates_checked=returned_checked,returned_candidate_failures=returned_failures,regenerated=regenerate,failures=failures[:50],failure_count=len(failures),core_result_sha256=digest(events))
    dump(root/('replay_report.json' if regenerate else 'validation_report.json'),result)
    return result
