"""Export existing frozen-rule sets/audits, no new matching or generation."""
import csv
from gp4_common import *
r=read(OUT/'comparison.json');rows=[];details=[]
def write_csv(path,data):
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader()
  for row in data:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else 'NA' if v is None else v for k,v in row.items()})
for item in r['items']:
 p=item['point_id'];pick=item['item_id'];comp=item['final_comparison']
 raw={tuple([a['item_id'],a['length'],a['width'],a['height'],a['yaw'],a['x'],a['y'],a['z']]) for a in read(OUT/'actions.json') if a['point_id']==p and a['pool']=='NEW_RAW_VALID' and a['item_id']==pick}
 old_only={tuple(x) for x in comp['OLD_ONLY']} if comp else None
 rows.append({'point_id':p,'item_id':pick,'old_final':item['old_final_count'],'new_final':item['new_final_count'],'intersection':comp['intersection_count'] if comp else None,'old_only':comp['old_only_count'] if comp else None,'new_only':comp['new_only_count'] if comp else None,'old_only_absent_new_raw':len(old_only-raw) if old_only is not None else None,'old_only_removed_new_compression':len(old_only&raw) if old_only is not None else None,'old_full_raw':'NOT_AVAILABLE','new_raw_valid':item['new_raw_valid_count'],'new_compression_loss':item['new_compression_loss'],'new_surface_only_raw':item['new_surface_only_raw_count'],'new_surface_only_final':item['new_surface_only_final_count']})
 if old_only is not None:assert rows[-1]['old_only_absent_new_raw']+rows[-1]['old_only_removed_new_compression']==len(old_only)
for state in r['states']:
 p=state['point_id'];d=OUT/'states'/p;sources={}
 newaudit=d/BACKENDS[1]/'audit.json'
 if state['backends'][BACKENDS[1]]['status'] in ('OK','OK_EMPTY'):
  for item in read(newaudit)['generation']['audit']['items']:
   for raw in item['raw_valid_candidates']:sources[action(raw['candidate'])]=raw['sources']
 for backend in BACKENDS:
  if state['backends'][backend]['status'] not in ('OK','OK_EMPTY'):continue
  for i,c in enumerate(read(d/backend/'bundle.json')['physical_candidates']):
   k=action(c);details.append({'point_id':p,'backend':backend,'math_action':list(k),'item_id':k[0],'oriented_size_mm':list(k[1:4]),'yaw':k[4],'published_pose_mm':list(k[5:]),'support_ids':c['support']['support_item_ids'],'support_ratio':c['support']['support_ratio'],'sources':sources[k] if backend==BACKENDS[1] else None,'source_availability':'AUDITED' if backend==BACKENDS[1] else 'NOT_AVAILABLE_OLD_INTERFACE','audit_pointer':str(d/backend/'bundle.json')+'#/physical_candidates/'+str(i)})
save(OUT/'decomposition.json',rows);write_csv(OUT/'decomposition.csv',rows)
save(OUT/'action_details.json',details);write_csv(OUT/'action_details.csv',details)
write_csv(OUT/'timing_and_requests.csv',[{'point_id':s['point_id'],'backend':b,'common_admission_s':s['common_admission_s'],**{k:v for k,v in s['backends'][b].items() if k in ('status','provider_wall_s','F0_wall_s','request_bytes','F0_status','telemetry')}} for s in r['states'] for b in BACKENDS])
print(json.dumps({'decomposition_rows':len(rows),'detailed_final_actions':len(details),'old_only_absent_new_raw':sum(x['old_only_absent_new_raw'] for x in rows if x['old_only_absent_new_raw'] is not None),'old_only_removed_new_compression':sum(x['old_only_removed_new_compression'] for x in rows if x['old_only_removed_new_compression'] is not None)}))
