"""Export real V2 traces to a standalone offline 3D presentation. No API calls."""
from pathlib import Path
import csv
import hashlib
import json
import sys
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'semantic_pallet_planner/src'))
from semantic_pallet_planner.evaluation.attribute_metrics_v2 import reconstruct,raw_metrics
from semantic_pallet_planner.evaluation.policy_v2 import evaluate,violations
from semantic_pallet_planner.evaluation.layout_preservation import layout_features
from semantic_pallet_planner.evaluation.state import state_metrics

EXP=ROOT/'semantic_pallet_planner/outputs/EXP_OPT_O3_LAYOUT_FLASH_V2_VALIDATION_20261020_01'
VARS=['original','relaxed_geometry','relaxed_wo_floor']
NAMES=['原策略','预算＋几何','预算＋布局']
sources={}
def read(p):
    sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    return json.loads(p.read_text(encoding='utf-8-sig'))
def log(p):
    sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    return [json.loads(s) for s in p.read_text().splitlines()]
acceptance=read(EXP/'acceptance_report.json')
assert acceptance['status']=='PASS'
tasks=read(EXP/'data/tasks.private.json')
task=next(t for t in tasks if t['episode_id']=='O3_SCN_0054_P1')
scenario=read(ROOT/'semantic_pallet_dataset_v1/tasks/scenarios/SCN_0054.json')
policy=task['truth_policy']
container=scenario['container']
data={'scenario':'SCN_0054','policy':'P1','planned':17,'instruction':task['instruction_text'],
      'container':container,'experiment':EXP.name,'ranking_version':acceptance['ranking_version'],
      'variants':[{'key':v,'name':n} for v,n in zip(VARS,NAMES)],'modes':{},'acceptance':{'status':'PASS','episodes':240,'calls':1502},
      'policy_definition':policy,'source_order':task['source_order_key']}
csvrows=[]
def metrics(placed,current_mass):
    pp=reconstruct(placed);ids,_=violations(pp,policy)
    return {'count':len(placed),'violation_ids':ids,'violations':len(ids),
            'geometry':state_metrics(container,placed),'attributes':raw_metrics(pp),
            'layout':layout_features(container,placed,policy,current_mass)}
for mode in ['safe','observe_business']:
    tracks=[]
    for variant in VARS:
        sub=f'episodes/{mode}/{variant}'
        events=log(EXP/f'{sub}/public_parser/O3_SCN_0054_P1/steps.jsonl')
        flash=log(EXP/f'{sub}/flash/O3_SCN_0054_P1/steps.jsonl')
        assert len(events)==len(flash)
        for a,b in zip(events,flash):
            for k in ['before_state_hash','after_state_hash','proposed_label','committed_label','status','after_placed']:
                assert a[k]==b[k],(mode,variant,k)
        report=read(EXP/f'{sub}/public_parser/O3_SCN_0054_P1/episode.json')['summary']
        steps=[]
        for e in events:
            req=e['request'];item=req['available_items'][0];before=req['placed_items'];after=e['after_placed']
            evs=[evaluate(req,c,policy,container) for c in req['candidates']]
            cs=[]
            for c,ev in zip(req['candidates'],evs):
                cc={k:c[k] for k in ['display_label','pick_item_id','pose','oriented_size_mm','geometry_score','support','load']}
                cc.update(feasible=not ev['after_violation_instances'],violation_ids=ev['after_violation_instances'],
                          new=ev['new_business_violation_count'],worsened=ev['worsened_existing_violation_count'],
                          soft_quality=ev['soft_quality'],layout=e['trace'].get('layout_scores',{}).get(c['display_label']),
                          eligible=c['display_label'] in e['trace'].get('eligible_labels',[]))
                cs.append(cc)
            selected=next((c for c in cs if c['display_label']==e['committed_label']),None)
            step={'arrival':e['step_index']+1,'item':item,'before':before,'after':after,
                  'before_metrics':metrics(before,item['mass_kg']),'after_metrics':metrics(after,item['mass_kg']),
                  'status':e['status'],'proposed':e['proposed_label'],'committed':e['committed_label'],
                  'candidates':cs,'feasible_count':sum(c['feasible'] for c in cs),'selected':selected,
                  'raw_evaluation':e['raw_evaluation'],'trace':e['trace'],'audit':e['generation_audit'],
                  'physical_errors':e['physical_errors'],'request_id':req['request_id'],
                  'before_state_hash':e['before_state_hash'],'after_state_hash':e['after_state_hash'],
                  'policy_digest':req['policy_digest'],'screen_intervened':e['screen_intervened'],
                  'would_screen_block':e['would_screen_block']}
            assert not step['physical_errors']
            steps.append(step)
            csvrows.append({'mode':mode,'variant':variant,'arrival':step['arrival'],'item_id':item['item_id'],
                            'placed':len(after),'physical_enumerated':e['audit']['physical_valid_count'] if 'audit' in e else e['generation_audit']['physical_valid_count'],
                            'topk':len(cs),'topk_business_feasible':step['feasible_count'],
                            'proposed':step['proposed'],'committed':step['committed'],
                            'business_violations':step['after_metrics']['violations'],
                            'max_height_mm':step['after_metrics']['geometry']['max_height_mm'],
                            'selected_z_base_mm':selected['pose']['z_base_mm'] if selected else None,'status':step['status']})
        assert len(steps[-1]['after'])==report['placed_items']
        assert steps[-1]['after_metrics']['violations']==report['final_business_violation_count']
        tracks.append({'key':variant,'summary':report,'steps':steps,'flash_matches':True})
    assert next(e['arrival'] for e,f in zip(tracks[0]['steps'],tracks[2]['steps']) if e['after_state_hash']!=f['after_state_hash'])==5
    assert next(e['arrival'] for e,f in zip(tracks[0]['steps'],tracks[1]['steps']) if e['after_state_hash']!=f['after_state_hash'])==6
    assert [t['summary']['placed_items'] for t in tracks]==([11,15,17] if mode=='safe' else [11,17,17])
    data['modes'][mode]=tracks

data['initial_metrics']=metrics([],scenario['items'][0]['mass_kg'])
payload=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
(HERE/'case_data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
with (HERE/'step_metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(csvrows[0]));w.writeheader();w.writerows(csvrows)
# The installed Plotly resource is embedded, with its original license header.
import plotly.offline
plotly_js=plotly.offline.get_plotlyjs()
html=(HERE/'template.html').read_text().replace('__STYLE__',(HERE/'style.css').read_text()).replace('__APP__',(HERE/'app.js').read_text()).replace('__DATA__',payload).replace('__PLOTLY__',plotly_js)
(HERE/'index.html').write_text(html)
assert '__DATA__' not in html and '__APP__' not in html
assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in sources.items())
evidence={'scenario':'SCN_0054','policy':'P1','status':'PASS','mode_variant_tracks':6,
          'actual_events':sum(len(t['steps']) for ts in data['modes'].values() for t in ts),
          'public_parser_flash_actions_states_equal':True,'first_divergence_original_layout_arrival':5,
          'first_divergence_original_geometry_arrival':6,'source_sha256':sources,
          'build_api_calls':0,'experimental_sources_modified':False,
          'explanation_scope':'Saved V2 trajectories; enumerated candidate failure is not continuous-space impossibility.'}
(HERE/'evidence_manifest.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'index':str(HERE/'index.html'),'bytes':(HERE/'index.html').stat().st_size,'events':evidence['actual_events']},ensure_ascii=False))
