"""Read-only attribution of saved O3 failures; never calls a model or edits source runs.

PYTHONPATH=semantic_pallet_planner/src MPLCONFIGDIR=/tmp/o3-mpl python \
  semantic_pallet_planner/scripts/analyze_o3_failures.py --source ... --output ...
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from semantic_pallet_planner.config import generator_config
from semantic_pallet_planner.domain import PalletState, internal_item, restore_placed
from semantic_pallet_planner.evaluation.attribute_metrics_v2 import box_bounds, reconstruct
from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
from semantic_pallet_planner.evaluation.policy_v2 import evaluate, violations
from semantic_pallet_planner.evaluation.replay_values_v2 import replay_values_equal
from semantic_pallet_planner.evaluation.state import apply_candidate
from semantic_pallet_planner.planner.constraints import candidate_points, evaluate_pose
from semantic_pallet_planner.planner.generator import ExtremePointGenerator
from semantic_pallet_planner.protocol import state_hash
from semantic_pallet_planner.runners.attribute_o3_online import step_state
from semantic_pallet_planner.runners.attribute_pilot_v2 import read_json, sha, write_csv, write_json
from semantic_pallet_planner.runners.o3_online_adapter import public_request
from semantic_pallet_planner.selectors.instruction_parser_o1b import resolved_public_policy
from semantic_pallet_planner.selectors.policy_executor_v2 import execute_policy
from semantic_pallet_planner.vlm.pilot_protocol_v2 import digest


def inventory(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def footprint_signature(placed):
    """Keep item identity/height, ignore physically redundant yaw on square bases."""
    return [(p['item_id'], *box_bounds(p)) for p in placed]


def largest_rectangle(free, xs, ys):
    """Exact largest axis-aligned rectangle on a non-uniform edge arrangement."""
    best = (0., None)
    for left in range(len(xs)-1):
        available = np.ones(len(ys)-1, dtype=bool)
        for right in range(left+1, len(xs)):
            available &= free[right-1]
            start = None
            for j in range(len(ys)):
                if j < len(ys)-1 and available[j]:
                    if start is None:
                        start = j
                elif start is not None:
                    area = (xs[right]-xs[left])*(ys[j]-ys[start])
                    if area > best[0]:
                        best = area, [xs[left], xs[right], ys[start], ys[j]]
                    start = None
    return best


def components(mask, xs, ys):
    """Edge adjacency only; area of a component need not form a usable rectangle."""
    unseen = set(map(tuple, np.argwhere(mask)))
    areas = []
    while unseen:
        todo = [unseen.pop()]
        area = 0.
        while todo:
            i, j = todo.pop()
            area += (xs[i+1]-xs[i])*(ys[j+1]-ys[j])
            for q in ((i-1,j), (i+1,j), (i,j-1), (i,j+1)):
                if q in unseen:
                    unseen.remove(q)
                    todo.append(q)
        areas.append(area)
    return areas


def surface_metrics(container, placed):
    """Exact XY skyline cells, not sampled pixels; no future boxes used here.

    Floor measures full-height-clear columns. Exposed support components only
    include the highest box top in each XY column; under-overhang space is not
    included. These are geometric proxies, not candidate feasibility proofs.
    """
    bounds = [box_bounds(p) for p in placed]
    xs = sorted({-container['length_mm']/2, container['length_mm']/2} |
                {x for b in bounds for x in b[:2]})
    ys = sorted({-container['width_mm']/2, container['width_mm']/2} |
                {y for b in bounds for y in b[2:4]})
    heights = np.zeros((len(xs)-1, len(ys)-1))
    owner = np.full(heights.shape, -1, dtype=int)
    for k, b in enumerate(bounds):
        for i in range(len(xs)-1):
            if xs[i] >= b[1] or xs[i+1] <= b[0]:
                continue
            for j in range(len(ys)-1):
                if ys[j] < b[3] and ys[j+1] > b[2] and b[5] > heights[i,j]:
                    heights[i,j] = b[5]
                    owner[i,j] = k
    weights = np.outer(np.diff(xs), np.diff(ys))
    floor = heights == 0
    rect_area, rect = largest_rectangle(floor, xs, ys)
    floor_components = components(floor, xs, ys)
    stackable = np.zeros(heights.shape, dtype=bool)
    fragile = np.zeros(heights.shape, dtype=bool)
    exposed_ids = set()
    for i, j in np.argwhere(owner >= 0):
        k = owner[i,j]
        exposed_ids.add(k)
        stackable[i,j] = placed[k]['stackable']
        fragile[i,j] = placed[k]['fragile']
    support_components = []
    for z in np.unique(heights[stackable]):
        support_components.extend(components(stackable & (heights == z), xs, ys))
    rebuilt = reconstruct(placed)
    remaining = [rebuilt[k]['top_load_limit_kg_synthetic']-rebuilt[k]['supported_load_kg']
                 for k in exposed_ids if rebuilt[k]['stackable']]
    return {
        'placed_count': len(placed),
        'max_height_mm': float(heights.max()),
        'empty_volume_mm3': container['length_mm']*container['width_mm']*container['max_height_mm']-
                             sum(math.prod(p['oriented_size_mm']) for p in placed),
        'floor_clear_column_area_mm2': float(weights[floor].sum()),
        'floor_clear_component_count': len(floor_components),
        'largest_floor_clear_rectangle_mm2': rect_area,
        'largest_floor_clear_rectangle': rect,
        'exposed_stackable_area_mm2': float(weights[stackable].sum()),
        'exposed_stackable_component_count': len(support_components),
        'largest_exposed_stackable_component_mm2': max(support_components, default=0.),
        'exposed_fragile_top_area_mm2': float(weights[fragile].sum()),
        'min_exposed_stackable_remaining_physical_kg': min(remaining, default=None),
    }


def request_for(source, method, ep, event):
    return read_json(source/'episodes'/method/ep/'selector_inputs'/event['request_id']/'public_request.json')


def chosen(req, event):
    return next((c for c in req['candidates'] if c['display_label'] == event['committed_label']), None)


def enumerate_audit(state, settings):
    """Same finite enumeration and first-rejection order as the frozen generator."""
    item = internal_item(state['available_items'][0])
    placed = restore_placed(state['placed_items'])
    cfg = copy.deepcopy(settings)
    cfg['container'] = state['container']
    rejection = Counter()
    candidates = []
    attempts = []
    seen = set()
    for yaw in cfg['candidate_generator']['yaw_degrees']:
        l,w = item['dimensions'][:2] if yaw == 0 else item['dimensions'][:2][::-1]
        for x,y,z in candidate_points(placed,l,w,state['container']):
            if (x,y,z,yaw) in seen:
                continue
            seen.add((x,y,z,yaw))
            c, reason = evaluate_pose(item,placed,x,y,z,l,w,yaw,cfg)
            rejection[reason or 'valid'] += 1
            attempts.append({'x0_mm':x, 'y0_mm':y, 'z_base_mm':z, 'yaw_deg':yaw,
                             'length_mm':l, 'width_mm':w, 'reason':reason or 'valid'})
            if c:
                candidates.append(c['visible'])
    return candidates, dict(sorted(rejection.items())), attempts


def offline_rollout(scenario, task, cfg, start=0, prefix=None, forced=None):
    """Public Parser only; force at most one stored action, then original executor.

    Future arrivals are supplied one at a time by step_state. No remote API.
    This is a simulator intervention, not an actual Flash continuation.
    """
    placed = copy.deepcopy(prefix or [])
    gen = ExtremePointGenerator(generator_config(cfg))
    events = []
    errors = []
    for i in range(start, len(scenario['arrival_order'])):
        state = step_state(scenario,task,placed,i)
        generated = gen.generate(PalletState.from_dict(state))
        req,mapping,_ = public_request(state,generated.candidate_set.data['candidates'],
                                       task['instruction_text'],seed=cfg['seed'])
        if not mapping:
            events.append({'step_index':i, 'step_number':i+1, 'status':'no_physical_candidate',
                           'before_placed':copy.deepcopy(placed), 'after_placed':copy.deepcopy(placed)})
            break
        policy = resolved_public_policy(req['instruction_text'],req)
        label = execute_policy(req,policy,allow_business_violation=True)
        candidate = mapping[label]
        if forced is not None and i == start:
            # Resolve by exact physical pose, never by another method's Cxx label.
            matches = [c for c in mapping.values() if c['pick_item_id']==forced['pick_item_id'] and
                       c['pose']==forced['pose'] and c['oriented_size_mm']==forced['oriented_size_mm']]
            if not matches:
                raise ValueError('forced action is absent from shared physical Top-K')
            candidate = matches[0]
        physical = check_candidate(req,{'container':scenario['container']},candidate)
        if physical:
            errors.extend(physical)
            raise ValueError('counterfactual physical failure: '+str(physical))
        value = evaluate(req,candidate,policy,req['container'])
        before = copy.deepcopy(placed)
        placed = apply_candidate(state,candidate)
        events.append({'step_index':i, 'step_number':i+1, 'status':'select',
                       'forced_action':forced is not None and i==start,
                       'pose':candidate['pose'], 'current_item_id':candidate['pick_item_id'],
                       'new_violations':value['new_business_violation_count'],
                       'worsened_violations':value['worsened_existing_violation_count'],
                       'before_placed':before, 'after_placed':copy.deepcopy(placed)})
    final,_ = violations(reconstruct(placed),task['truth_policy'])
    return {'placed_items':len(placed), 'planned_items':len(scenario['arrival_order']),
            'completed':len(placed)==len(scenario['arrival_order']),
            'final_business_violation_count':len(final), 'final_violation_ids':final,
            'physical_violations':len(errors), 'events':events}


def plot_case(out, name, case, parser_events, geo_events, divergences, curve):
    container = case['container']
    fig, axes = plt.subplots(2,3,figsize=(16,9))
    first = divergences['first_bbox_divergence_step_index']
    stop = len(parser_events)-1
    for row,(index,title) in enumerate(((first,'First geometric divergence'), (stop,'Failure before placement'))):
        for col,(method,events) in enumerate((('Parser / Flash',parser_events),('Geometry',geo_events))):
            ax = axes[row,col]
            e = events[index]
            ps = e['after_placed'] if row == 0 else e['before_placed']
            for p in ps:
                x0,x1,y0,y1,z0,z1 = box_bounds(p)
                ax.add_patch(Rectangle((x0,y0),x1-x0,y1-y0,facecolor=plt.cm.viridis(z1/container['max_height_mm']),
                                       edgecolor='black',alpha=.65))
                ax.text((x0+x1)/2,(y0+y1)/2,p['item_id'].replace('item_','')+f'\nz={z0:g}',
                        ha='center',va='center',fontsize=7)
            metric = surface_metrics(container,ps)
            rect = metric['largest_floor_clear_rectangle']
            if rect:
                x0,x1,y0,y1=rect
                ax.add_patch(Rectangle((x0,y0),x1-x0,y1-y0,fill=False,edgecolor='red',lw=2,linestyle='--'))
            ax.set(xlim=(-container['length_mm']/2,container['length_mm']/2),
                   ylim=(-container['width_mm']/2,container['width_mm']/2),aspect='equal',
                   title=f'{method}: {title}\narrival #{index+1}, placed={len(ps)}',xlabel='X / mm',ylabel='Y / mm')
        ax = axes[row,2]
        key = 'largest_floor_clear_rectangle_mm2' if row==0 else 'exposed_stackable_area_mm2'
        for method,color in (('public_parser','tab:orange'),('geometry_greedy','tab:blue')):
            points=[c for c in curve if c['method']==method]
            ax.plot([c['placed_count'] for c in points],[c[key]/1e6 for c in points],label=method,color=color,marker='.')
        ax.set(xlabel='Placed boxes',ylabel='Area / m²',title=key.replace('_mm2','').replace('_',' '))
        ax.legend(fontsize=8); ax.grid(alpha=.3)
    fig.suptitle(name+' | offline diagnosis; red dashed = largest clear floor rectangle\n'
                 'Top projections overlap for stacked boxes; colors indicate top height, not material properties.')
    fig.tight_layout(rect=(0,0,1,.94))
    fig.savefig(out/'figures'/f'{name}.png',dpi=150)
    plt.close(fig)


def run(source, out):
    source,out=source.resolve(),out.resolve()
    if out.exists():
        raise FileExistsError('choose a fresh output directory')
    if source == out or source in out.parents or out in source.parents:
        raise ValueError('diagnostic output must be outside original experiment')
    original = inventory(source)
    manifest=read_json(source/'manifest.json')
    if manifest.get('execution_mode') != 'observe_business':
        raise ValueError('requires original business observation experiment')
    pkg=Path(__file__).resolve().parents[1]/'src/semantic_pallet_planner'
    mismatches=[p for p,h in manifest['source_sha256'].items() if sha(pkg/p)!=h]
    if mismatches:
        raise ValueError('current source differs from frozen run: '+str(mismatches))
    cfg=read_json(source/'config.snapshot.json')
    settings=generator_config(cfg)
    dataset=Path(cfg['dataset'])
    for p,h in manifest['dataset_sha256'].items():
        if sha(dataset/p)!=h:
            raise ValueError('dataset mismatch '+p)
    tasks=read_json(source/'data/tasks.private.json')
    out.mkdir(parents=True)
    (out/'figures').mkdir()
    (out/'counterfactuals').mkdir()
    write_json(out/'source_inventory.before.json',original)
    failure_rows=[]; divergence_rows=[]; curve_rows=[]; terminal_rows=[]; intervention_rows=[]
    checks=[]; gate_rows=[]
    for task in tasks:
        ep=task['episode_id']
        fp=source/'episodes/flash_policy_parser'/ep
        summary=read_json(fp/'episode.json')['summary']
        if summary['completed']:
            continue
        scenario=read_json(dataset/'tasks/scenarios'/f"{task['scenario_id']}.json")
        events={}
        for method in ('flash_policy_parser','public_parser','geometry_greedy'):
            directory=source/'episodes'/method/ep
            events[method]=[json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
            record=read_json(directory/'episode.json')
            assert record['core_result_sha256']==digest(events[method])
            if method == 'geometry_greedy':
                assert record['summary']['completed'], 'geometry control did not complete'
        a,g=events['public_parser'],events['geometry_greedy']
        f=events['flash_policy_parser']
        assert len(a)==len(f)
        for x,y in zip(a,f):
            assert all(x[k]==y[k] for k in ('before_state_hash','after_state_hash','proposed_label','committed_label','status'))
        hash_first=next(i for i,(x,y) in enumerate(zip(a,g)) if x['after_state_hash']!=y['after_state_hash'])
        first=next(i for i,(x,y) in enumerate(zip(a,g)) if footprint_signature(x['after_placed'])!=footprint_signature(y['after_placed']))
        assert a[first]['before_state_hash']==g[first]['before_state_hash']
        assert a[-1]['status']=='no_physical_candidate'
        baseline=offline_rollout(scenario,task,cfg)
        assert len(baseline['events'])==len(a)
        assert all(replay_values_equal(x['after_placed'],y['after_placed']) for x,y in zip(baseline['events'],a))
        checks.append({'episode_id':ep,'saved_event_digests':True,'flash_parser_equal':True,
                       'public_parser_full_offline_reproduction':True,'common_divergence_before_state':True})
        drow={'episode_id':ep,'first_hash_divergence_step_index':hash_first,
              'first_hash_divergence_arrival_number':hash_first+1,
              'first_bbox_divergence_step_index':first,'first_bbox_divergence_arrival_number':first+1,
              'current_item_id':a[first]['current_item_id'],'shared_before_state_hash':a[first]['before_state_hash']}
        for method,event in (('public_parser',a[first]),('geometry_greedy',g[first])):
            req=request_for(source,method,ep,event)
            c=chosen(req,event)
            value=evaluate(req,c,resolved_public_policy(req['instruction_text'],req),req['container'])
            drow[method+'_choice']={k:c[k] for k in ('display_label','pose','oriented_size_mm','geometry_score')}
            drow[method+'_policy_evaluation']=value
            drow[method+'_after_surface']=surface_metrics(scenario['container'],event['after_placed'])
        divergence_rows.append(drow)
        # One historical action intervention, same shared prefix and original public executor.
        geo_choice=chosen(request_for(source,'geometry_greedy',ep,g[first]),g[first])
        intervention=offline_rollout(scenario,task,cfg,start=first,prefix=a[first]['before_placed'],forced=geo_choice)
        write_json(out/'counterfactuals'/f'{ep}.json',{'task':task,'intervention_arrival_number':first+1,
                   'interpretation':'Public Parser simulated continuation, not real Flash; single action override',
                   'baseline_reproduced':{k:v for k,v in baseline.items() if k!='events'},
                   'result':intervention})
        irow={'episode_id':ep,'intervention_arrival_number':first+1,'baseline_placed':summary['placed_items'],
              'intervention_placed':intervention['placed_items'],
              'placed_delta':intervention['placed_items']-summary['placed_items'],
              'intervention_completed':intervention['completed'],
              'baseline_final_violations':summary['final_business_violation_count'],
              'intervention_final_violations':intervention['final_business_violation_count'],
              'physical_violations':intervention['physical_violations']}
        intervention_rows.append(irow)
        local_curves=[]
        for method,history in (('public_parser',a),('geometry_greedy',g)):
            states=[[]]+[e['after_placed'] for e in history if e['committed_label']]
            for k,ps in enumerate(states):
                row={'episode_id':ep,'method':method,'placed_count':k,
                     **surface_metrics(scenario['container'],ps)}
                if k<len(history):
                    row.update(next_arrival_number=k+1,physical_valid_count=history[k]['generation_audit']['physical_valid_count'],
                               topk_count=history[k]['candidate_count'],topk_business_feasible_count=history[k]['topk_feasible_count'])
                local_curves.append(row)
        curve_rows.extend(local_curves)
        terminal=a[-1]; index=terminal['step_index']
        for method,history in (('public_parser',a),('geometry_greedy',g)):
            event=history[index]
            state=step_state(scenario,task,event['before_placed'],index)
            candidates,hist,attempts=enumerate_audit(state,settings)
            assert len(candidates)==event['generation_audit']['physical_valid_count']
            assert {k:v for k,v in hist.items() if k!='valid'}==event['generation_audit']['rejection_histogram']
            # Gate counts are ordered, not independent/multiple-cause counts.
            remaining=len(attempts)
            for gate in ('out_of_bounds','over_payload','overlap','insufficient_support',
                         'com_outside_support','non_stackable_support','overload'):
                rejected=hist.get(gate,0)
                gate_rows.append({'episode_id':ep,'method':method,'arrival_number':index+1,
                                  'gate':gate,'entering':remaining,'rejected_first_here':rejected,
                                  'remaining_after_gate':remaining-rejected})
                remaining-=rejected
            assert remaining==len(candidates)
            checks.append({'episode_id':ep,'method':method,'terminal_step_enumeration_matches':True})
            terminal_rows.append({'episode_id':ep,'method':method,'arrival_number':index+1,
                                  'current_item_id':event['current_item_id'],'physical_count':len(candidates),
                                  'rejections':hist,'current_item':state['available_items'][0],
                                  **surface_metrics(scenario['container'],event['before_placed'])})
            write_csv(out/f'terminal_attempts_{ep}_{method}.csv',attempts)
        failure_rows.append({'episode_id':ep,'source_order_key':task['source_order_key'],
            'scenario_id':task['scenario_id'],'policy_id':task['policy_id'],
            'planned_items':summary['planned_items'],'placed_items':summary['placed_items'],
            'failed_arrival_number':index+1,'failed_item_id':terminal['current_item_id'],
            'first_geometric_divergence_arrival_number':first+1,
            'final_business_violation_count':summary['final_business_violation_count'],
            'terminal_rejections':terminal['generation_audit']['rejection_histogram'],
            'geometry_completed':True,'intervention_placed_delta':irow['placed_delta']})
        plot_case(out,ep,scenario,a,g,drow,local_curves)
        print(ep,'placed',summary['placed_items'],'/',summary['planned_items'],
              'first divergence',first+1,'override delta',irow['placed_delta'],flush=True)
    write_csv(out/'failure_cases.csv',failure_rows)
    write_csv(out/'divergence_steps.csv',divergence_rows)
    write_csv(out/'state_metrics.csv',curve_rows)
    write_csv(out/'terminal_diagnostics.csv',terminal_rows)
    write_csv(out/'single_action_interventions.csv',intervention_rows)
    write_csv(out/'terminal_gate_funnel.csv',gate_rows)
    write_json(out/'divergence_details.json',divergence_rows)
    write_json(out/'terminal_details.json',terminal_rows)
    write_json(out/'checks.json',checks)
    after=inventory(source)
    changed=[p for p in set(original)|set(after) if original.get(p)!=after.get(p)]
    assert not changed, 'source changed during analysis'
    result={'status':'PASS','source':str(source),'failures':len(failure_rows),
            'independent_failure_source_orders':len({r['source_order_key'] for r in failure_rows}),
            'first_geometric_divergence_arrival_histogram':dict(Counter(r['first_geometric_divergence_arrival_number'] for r in failure_rows)),
            'single_action_override_more_placed':sum(r['placed_delta']>0 for r in intervention_rows),
            'single_action_override_fewer_placed':sum(r['placed_delta']<0 for r in intervention_rows),
            'single_action_override_completed':sum(r['intervention_completed'] for r in intervention_rows),
            'source_files_hashed':len(original),'source_files_changed':changed,
            'model_api_calls':0,'diagnostic_only':True,'new_test_evidence':False,
            'analyst_script_sha256':sha(Path(__file__)),
            'generator_config_sha256':sha(dataset/'configs/mvd_v0.1.json'),
            'frozen_source_mismatches':mismatches}
    write_json(out/'analysis_summary.json',result)
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    print(json.dumps(run(args.source,args.output),ensure_ascii=False,indent=2))
