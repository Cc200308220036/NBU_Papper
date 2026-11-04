"""Describe saved drop-height mismatches using rectangles only, no LP/generator."""
from pathlib import Path
from semantic_pallet_planner.jev_select.ledger import read,write
OUT=Path(__file__).resolve().parent
RUN=OUT/'run'
cases=[]
for p in sorted((RUN/'jobs').glob('*/actions/*.json')):
    e=read(p);mon=e.get('monitor')
    if not mon or mon['status']!='UNASSESSABLE':continue
    s=e['selection'];c=next(c for c in e['bundle']['physical_candidates'] if c['candidate_id']==s['selected_candidate_id'])
    def bounds(o):
        p=o['pose'];l,w,h=o['oriented_size_mm']
        return p['x_mm']-l/2,p['x_mm']+l/2,p['y_mm']-w/2,p['y_mm']+w/2,p['z_base_mm'],p['z_base_mm']+h
    a=bounds(c);overlaps=[]
    for o in e['before']['placed_items']:
        b=bounds(o);dx=min(a[1],b[1])-max(a[0],b[0]);dy=min(a[3],b[3])-max(a[2],b[2])
        if dx>0 and dy>0:overlaps.append({'item_id':o['item_id'],'xy_overlap_mm':[dx,dy],'bottom_mm':b[4],'top_mm':b[5]})
    max_top=max((o['top_mm'] for o in overlaps),default=0)
    cases.append({'job_id':p.parents[1].name,'decision_id':e['decision_id'],'reason':mon['result']['reason_code'],
                  'selected_item':c['pick_item_id'],'candidate_z_base_mm':a[4],'candidate_top_mm':a[5],
                  'highest_xy_overlap_top_mm':max_top,'geometric_drop_delta_mm':max_top-a[4],
                  'xy_overlaps':overlaps,'native_monitor_height_delta_mm':mon['result'].get('height_delta_mm'),
                  'not_committed':e['action'] is None and e['before']==e['after'],
                  'classification':'lower-cavity/overhang static pose versus conservative top-down drop boundary' if mon['result']['reason_code']=='POSE_HEIGHT_MISMATCH' else 'OTHER_UNASSESSABLE_REQUIRES_REVIEW'})
write(OUT/'monitor_scope_review.json',{'version':'jev_jn1_b_scope_review_v1','cases':cases,'solver_calls':0,'candidate_generation':0,
      'interpretation':'UNASSESSABLE is a declared conservative scope stop, not predicted static instability or physical collapse'})
print({'scope_cases':len(cases),'reasons':[c['reason'] for c in cases]})
