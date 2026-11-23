"""Export only saved facts; no model, planner, monitor, replay or credentials."""
from pathlib import Path
import json,hashlib
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=ROOT/'semantic_pallet_planner/outputs'
NEW=BASE/'GEOM_CANDIDATES_GP6_EMS_CORNER_20261123_01'
OLD=BASE/'GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_RUN_20261122_01'
sources={}
def load(p):
 sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
 return json.loads(p.read_text())
def shape(c):return tuple(c['oriented_size_mm'])+tuple(c['pose'][k] for k in ('x_mm','y_mm','z_base_mm','yaw_deg'))
def corner(c):
 p=c['pose'];l,w,_=c['oriented_size_mm'];return abs(p['x_mm']-l/2+600)<1e-6 and abs(p['y_mm']-w/2+500)<1e-6 and p['z_base_mm']==0
jobs=[]
for title,path in [('原选择指令',OLD),('加入靠角偏好',NEW/'run')]:
 cp=load(path/'jobs/G01/checkpoint.json');m=load(path/'jobs/G01/metrics.json');steps=[]
 events=[e for e in cp['events'] if e.get('event')=='PLACE']
 for e in events:
  c=next(c for c in e['bundle']['physical_candidates'] if c['candidate_id']==e['selection']['selected_candidate_id'])
  steps.append({'item_id':c['pick_item_id'],'label':e['selection']['selected_display_id'],'pose':c['pose'],'oriented_size_mm':c['oriented_size_mm'],'monitor':e['monitor']['status'],'candidate_count':len(e['bundle']['physical_candidates']),'support_ratio':c['support']['support_ratio']})
 first=events[0];mapping=first['context']['display_mapping'];pool=first['bundle']['physical_candidates'];options=[]
 for label,v in mapping.items():
  c=next(c for c in pool if c['candidate_id']==v['candidate_id'])
  if c['pick_item_id']==steps[0]['item_id'] and corner(c): options.append({'label':label,'pose':c['pose'],'oriented_size_mm':c['oriented_size_mm']})
 jobs.append({'title':title,'steps':steps,'metrics':{k:m[k] for k in ('placed_items','planned_items','fixed_container_utilization','max_height_mm','envelope_utilization','termination_reason','counts','cost','placed_mass_kg')},'first_corner_options':options,'first_pool_count':len(pool),'first_corner_count':sum(corner(c) for c in pool),'base_instruction':first['context']['request_body']['questions']['next_action']['instructions'],'source_path':str(path.relative_to(ROOT))})
audit=load(NEW/'saved_result_audit.json');spec=load(NEW/'single_experiment_plan_FROZEN.json')
wires=[load(p) for p in sorted((NEW/'run/sent_requests').glob('[0-9][0-9].json'))]
assert len(wires)==4 and all(w['questions']['next_action']['instructions']==jobs[0]['base_instruction']+'\n\n'+spec['placement_instruction'] for w in wires)
assert all(j['metrics']['placed_items']==4 for j in jobs)
data={'jobs':jobs,'added_instruction':spec['placement_instruction'],'actual_instruction':wires[0]['questions']['next_action']['instructions'],'wire_instruction_count':len(wires),'same_final_geometry':sorted(shape(c) for c in jobs[0]['steps'])==sorted(shape(c) for c in jobs[1]['steps']),'audit':audit,'source_hashes':sources,'experiment_plan_digest':audit['experiment_plan_digest'],'runtime_plan_digest':audit['runtime_plan_digest'],'new_model_calls':0,'new_monitor_calls':0,'new_episode_runs':0}
assert data['same_final_geometry']
(HERE/'case_data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
html=(HERE/'template.html').read_text().replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('</','<\\/'))
(HERE/'index.html').write_text(html)
print(json.dumps({'steps':[len(j['steps']) for j in jobs],'same_final_geometry':data['same_final_geometry'],'actual_instruction_verified':len(wires),'new_calls':0}))
