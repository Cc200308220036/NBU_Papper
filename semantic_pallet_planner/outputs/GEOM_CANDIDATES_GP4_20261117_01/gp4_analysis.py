"""Offline set analysis of saved output only. Never regenerate or execute."""
import csv,statistics
from gp4_common import *

def keys(cs,equiv=False):return {action(c,equiv) for c in cs}
def sorted_keys(ks):return [list(k) for k in sorted(ks,key=lambda k:(k[0],*(Fraction(x) for x in k[1:])))]
def candidate_metrics(cs,source_by_key=None):
 if cs is None:return None
 support=sorted({tuple(sorted(c['support']['support_item_ids'])) if number(c['pose']['z_base_mm']) else ('GROUND',) for c in cs}) if all('support' in c for c in cs) else None
 heights=sorted({text(c['pose']['z_base_mm']) for c in cs},key=Fraction)
 def score(c):return round(sum(c['geometry_score_components'][k]*v for k,v in {'compactness':.35,'height':.25,'stability':.25,'balance':.15}.items()),9)
 return {'unique_actions':len(keys(cs)),'height_levels':heights,'yaw_counts':{str(y):sum(c['pose']['yaw_deg']==y for c in cs) for y in (0,90)},'quadrants':sorted({(number(c['pose']['x_mm'])>=0,number(c['pose']['y_mm'])>=0) for c in cs}),'support_sets':support,'minimum_resulting_height_mm':min((c['resulting_geometry']['max_height_mm'] for c in cs),default=None) if all('resulting_geometry' in c for c in cs) else None,'maximum_support_ratio':max((c['support']['support_ratio'] for c in cs),default=None) if all('support' in c for c in cs) else None,'geometry_score_range':[min(score(c) for c in cs),max(score(c) for c in cs)] if cs and all('geometry_score_components' in c for c in cs) else None,'sources':sorted({s for c in cs for s in (source_by_key or {}).get(action(c),[])}) if source_by_key is not None else None}

def analyze():
 summary=read(OUT/'generation_summary.json');states=[];items=[];action_rows=[]
 for sr in summary['states']:
  point=sr['point_id'];base=OUT/'states'/point;arms={};raw_new=None;sources={};new_item_audits={};old_item_audits={};old_projection=None
  for backend in BACKENDS:
   record=sr['backends'][backend];valid=record['status'] in ('OK','OK_EMPTY')
   final=read(base/backend/'bundle.json')['physical_candidates'] if valid else None
   arms[backend]={'status':record['status'],'error':record['error'],'final_count':len(final) if final is not None else None,'final_metrics':candidate_metrics(final),'final_pool':final,'raw_availability':'NOT_AVAILABLE_OLD_E2_INTERFACE' if backend==BACKENDS[0] else ('COMPLETE' if valid else 'NOT_AVAILABLE_BACKEND_ERROR'),'provider_wall_s':record['provider_wall_s'],'F0_wall_s':record['F0_wall_s'],'F0_status':record['F0_status'],'F0_error':record['F0_error'],'request_bytes':record['request_bytes'],'telemetry':record['telemetry']}
   if valid:
    audit=read(base/backend/'audit.json')
    if backend==BACKENDS[1]:
     new_item_audits={i['item_id']:i for i in audit['generation']['audit']['items']}
     raw_new=[r['candidate'] for i in new_item_audits.values() for r in i['raw_valid_candidates']]
     sources={action(r['candidate']):r['sources'] for i in new_item_audits.values() for r in i['raw_valid_candidates']}
     arms[backend].update(raw_valid_count=len(raw_new),raw_metrics=candidate_metrics(raw_new,sources),final_metrics=candidate_metrics(final,sources))
    else:
     old_item_audits={r['pick_item_id']:r for r in audit['generation']['items']} if audit['generation']['items'] and 'pick_item_id' in audit['generation']['items'][0] else {r.get('item_id',pick):r for pick,r in zip(sr['item_ids'],audit['generation']['items'])}
     old_projection=[c for r in audit['generation']['items'] for c in r['public_enumerated_candidates']]
     arms[backend].update(raw_valid_count=None,enumeration_projection_count=len(old_projection),enumeration_projection_metrics=candidate_metrics(old_projection),projection_status='PARTIAL_FIELDS_POST_E2_PUBLIC_ENUMERATION_NOT_COMPLETE_RAW')
  old=arms[BACKENDS[0]]['final_pool'];new=arms[BACKENDS[1]]['final_pool']
  def compare(a,b):
   if a is None or b is None:return None
   x,y=keys(a),keys(b)
   return {'intersection_count':len(x&y),'old_only_count':len(x-y),'new_only_count':len(y-x),'intersection':sorted_keys(x&y),'OLD_ONLY':sorted_keys(x-y),'NEW_ONLY':sorted_keys(y-x),'old_retention':len(x&y)/len(x) if x else None,'new_only_fraction':len(y-x)/len(y) if y else None,'square_yaw_equivalent_counts':{'intersection':len(keys(a,True)&keys(b,True)),'old_only':len(keys(a,True)-keys(b,True)),'new_only':len(keys(b,True)-keys(a,True))}}
  final_compare=compare(old,new)
  # This is explicitly final-old vs raw-new, never a fabricated raw/raw comparison.
  old_final_vs_new_raw=compare(old,raw_new)
  for pick in sr['item_ids']:
   o=[c for c in old if c['pick_item_id']==pick] if old is not None else None
   n=[c for c in new if c['pick_item_id']==pick] if new is not None else None
   r=[c for c in raw_new if c['pick_item_id']==pick] if raw_new is not None else None
   proj=[c for c in old_projection if c['pick_item_id']==pick] if old_projection is not None else None
   ia=new_item_audits.get(pick);oa=old_item_audits.get(pick)
   fs=keys(n) if n is not None else None;rs=keys(r) if r is not None else None
   surface={k for k,s in sources.items() if k[0]==pick and 'SURFACE_CORNER' in s and 'EMS_STYLE_3D' not in s}
   it={'point_id':point,'item_id':pick,'old_status':sr['backends'][BACKENDS[0]]['status'],'new_status':sr['backends'][BACKENDS[1]]['status'],'old_final_count':len(o) if o is not None else None,'new_final_count':len(n) if n is not None else None,'old_raw_valid_count':None,'old_raw_status':'NOT_AVAILABLE','old_enumeration_projection_count':len(proj) if proj is not None else None,'old_projection_to_final_removed':len(keys(proj)-keys(o)) if proj is not None and o is not None else None,'old_raw_generation_loss':None,'old_raw_compression_loss':None,'new_raw_valid_count':len(r) if r is not None else None,'new_unique_published_proposals':ia['unique_actions'] if ia else None,'new_raw_point_attempts':ia['raw_point_attempts'] if ia else None,'new_invalid_unique_actions':ia['unique_actions']-ia['raw_valid_count'] if ia else None,'new_proposal_rejection_instances':sum(ia['rejection_counts'].values()) if ia else None,'new_compression_loss':len(rs-fs) if rs is not None else None,'new_surface_only_raw_count':len(surface) if r is not None else None,'new_surface_only_final_count':len(surface&fs) if fs is not None else None,'final_comparison':compare(o,n),'new_coverage':ia['coverage'] if ia else None,'new_dropped_actions':sorted_keys(rs-fs) if rs is not None else None,'new_surface_only_raw_actions':sorted_keys(surface) if r is not None else None,'old_enumeration_counters':{k:v for k,v in (oa or {}).items() if k not in ('public_enumerated_candidates','baseline_candidates')} if oa else None}
   items.append(it)
  for pool,cs in [('OLD_FINAL',old),('NEW_FINAL',new),('NEW_RAW_VALID',raw_new),('OLD_ENUM_PROJECTION',old_projection)]:
   if cs is not None:
    for c in cs:
     k=action(c);cat=('INTERSECTION' if final_compare is not None and k in keys(old)&keys(new) else 'OLD_ONLY' if final_compare is not None and k in keys(old)-keys(new) else 'NEW_ONLY' if final_compare is not None and k in keys(new)-keys(old) else 'NOT_IN_FINAL_OR_NOT_COMPARABLE')
     action_rows.append({'point_id':point,'pool':pool,'item_id':k[0],'length':k[1],'width':k[2],'height':k[3],'yaw':k[4],'x':k[5],'y':k[6],'z':k[7],'final_category':cat,'sources':sources.get(k) if pool.startswith('NEW') else None})
  states.append({'point_id':point,'common_status':sr['common_status'],'common_error':sr['common_error'],'common_admission_s':sr['common_admission_s'],'item_ids':sr['item_ids'],'backends':{b:{k:v for k,v in a.items() if k!='final_pool'} for b,a in arms.items()},'final_comparison':final_compare,'raw_raw_comparison':None,'raw_raw_status':'NOT_AVAILABLE_OLD_FULL_RAW','old_final_vs_new_raw':old_final_vs_new_raw})
 result={'version':'gp4_saved_state_comparison_result_v1','scope':'SAVED_STATE_ANALYSIS_NO_EXECUTION','state_denominator':5,'item_denominator':len(items),'states':states,'items':items,'timing_aggregate':{},'interpretation':'Coverage of fixed candidate pools only; no whole-order/Jev benefit or completeness conclusion','model_calls':0,'PCT_LP_calls':0,'execution_calls':0}
 for b in BACKENDS:
  vals=[s['backends'][b]['provider_wall_s'] for s in states if s['backends'][b]['provider_wall_s'] is not None]
  result['timing_aggregate'][b]={'n':len(vals),'raw_seconds':vals,'median_seconds':statistics.median(vals) if vals else None,'max_seconds':max(vals) if vals else None,'interpretation':'single sequential process, observed cache mix; not repeated cold benchmarks'}
 from jsonschema import Draft202012Validator
 Draft202012Validator(read(OUT/'comparison_result.schema.json')).validate(result)
 save(OUT/'comparison.json',result);save(OUT/'actions.json',action_rows)
 def write_csv(path,rows):
  if not rows:return
  with path.open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
   for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list)) else ('NA' if v is None else v) for k,v in row.items()})
 write_csv(OUT/'items.csv',items);write_csv(OUT/'actions.csv',action_rows)
 write_csv(OUT/'states.csv',[{'point_id':s['point_id'],'common_status':s['common_status'],'common_error':s['common_error'],'old_status':s['backends'][BACKENDS[0]]['status'],'new_status':s['backends'][BACKENDS[1]]['status'],'old_count':s['backends'][BACKENDS[0]]['final_count'],'new_count':s['backends'][BACKENDS[1]]['final_count'],'comparison':s['final_comparison']} for s in states])
 print(json.dumps({'states':len(states),'items':len(items),'actions':len(action_rows),'backend_statuses':{s['point_id']:{b:s['backends'][b]['status'] for b in BACKENDS} for s in states}}),flush=True)
if __name__=='__main__':analyze()
