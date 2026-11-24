import json,hashlib
from pathlib import Path
out=Path('report/visualization/GP6_EMS_原指令与强制顺序指令三维对比_20261123')
base=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_RUN_20261122_01/jobs/G01')
new=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_EMS_MANDATORY_20261123_01')
sources={}
def read(p):
 sources[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest();return json.loads(p.read_text())
jobs=[]
for title,p in [('原指令 · 归档 G01',base),('强制顺序文字 · 本次实验',new/'run/jobs/G01')]:
 cp=read(p/'checkpoint.json');m=read(p/'metrics.json');steps=[]
 for e in cp['events']:
  if e.get('event')!='PLACE':continue
  c=next(c for c in e['bundle']['physical_candidates'] if c['candidate_id']==e['selection']['selected_candidate_id'])
  steps.append(dict(item=c['pick_item_id'],label=e['selection']['selected_display_id'],pose=c['pose'],size=c['oriented_size_mm'],monitor=e['monitor']['status']))
 assert len(steps)==m['placed_items']
 jobs.append(dict(title=title,steps=steps,metrics=m))
data=dict(jobs=jobs,audit=read(new/'saved_result_audit.json'),instruction=(new/'final_selection_instructions.txt').read_text(),source_hashes=sources)
(out/'case_data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
(out/'index.html').write_text((out/'template.html').read_text().replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('</','<\\/')))
print('built',out)
