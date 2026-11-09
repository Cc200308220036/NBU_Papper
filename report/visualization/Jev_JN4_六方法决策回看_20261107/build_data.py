"""Offline projection of saved JN4 evidence. Stdlib only; no credential/solver/model imports."""
import base64,copy,hashlib,json,math
from memory_audit import build_audit
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent;WEB=OUT/'web'
SOURCES={}
def probability_ties(probabilities,chosen=None):
 if not probabilities:return {'available':False,'top_labels':[],'top_tie':False,'any_tie':False}
 assert all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in probabilities.values())
 groups={}
 for label,value in probabilities.items():groups.setdefault(value,[]).append(label)
 maximum=max(groups);top=sorted(groups[maximum])
 return {'available':True,'maximum':maximum,'top_labels':top,'top_tie':len(top)>1,'any_tie':any(len(labels)>1 for labels in groups.values()),'candidate_count':len(probabilities),'selected':chosen,'selected_in_top':chosen in top,'equal_groups':[{'value':v,'labels':sorted(labels)} for v,labels in sorted(groups.items(),reverse=True) if len(labels)>1]}

def read(path):
 p=ROOT/path if not Path(path).is_absolute() else Path(path);raw=p.read_bytes();SOURCES[str(p.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
def js(path,name,data):
 text=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
 path.write_text(name+'='+text+';\n',encoding='utf-8')
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
analysis=Path('semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_RUN_20261106_01')
rows=read(analysis/'all_36_slots.json');pairs=read(analysis/'paired_comparisons_v2.json');summary=read(analysis/'descriptive_summary.json')
names=['几何基线','固定顺序','Jev 无经验','T 历史案例','E 对比经验','无关E 对照'];methods=list(dict.fromkeys(r['method_id'] for r in rows))
tie_decisions=[];plans={};ledgers={};jobcards=[];counts=Counter();arithmetic=[];library={};audit_jobs={}
for row in rows:
 run=Path(row['run']);planpath=run.parent/'plan/plan.json'
 if str(run) not in plans:
  plans[str(run)]=read(planpath);ledgers[str(run)]={r['decision_id']:r for r in read(run/'request_ledger/requests.json')['requests']}
 p=plans[str(run)];j=next(x for x in p['jobs'] if x['job_id']==row['job_id']);folder=run/'jobs'/j['job_id']
 cp=read(folder/'checkpoint.json');metric=read(folder/'metrics.json');task=read(folder/'task.snapshot.json');status=read(folder/'status.json')
 events=[];flow=[];local_rule='按几何分降序，再按x、y、z、朝向、箱体别名升序打破并列。' if j['method_id']==methods[0] else '按当前展示候选标签的字典序取最小值（C01）；不是按最早到货箱固定取箱。' if j['method_id']==methods[1] else 'Jev按实际英文目标，在当前可观察状态与展示候选中输出Choice标签；没有保存自然语言理由。'
 for i,e in enumerate(cp['events']):
  flow.append({'index':i,'event':e['event'],'reason':e.get('reason'),'decision_id':e.get('decision_id'),'placed_before':e['before']['placed_count'],'placed_after':e['after']['placed_count'],'arrived_before':e['before']['arrival_count'],'arrived_after':e['after']['arrival_count']})
  if not (e.get('decision_id') or e['event']=='STOP' or i==len(cp['events'])-1):continue
  context=e.get('context') or {};request=context.get('request_body');mapping=context.get('display_mapping',{});bundle=e.get('bundle') or {};physical={c['candidate_id']:c for c in bundle.get('physical_candidates',[])}
  candidates=[]
  for label,m in mapping.items():
   c=physical.get(m['candidate_id'],{});candidates.append({'label':label,'candidate_id':m['candidate_id'],'item_id':m['pick_item_id'],'candidate_digest':m.get('candidate_digest'),'geometry_score_components':c.get('geometry_score_components'),'support':c.get('support'),'load':c.get('load'),'ems':c.get('ems'),'physical_valid':c.get('physical_valid')})
  candidates.sort(key=lambda c:c['label']);selection=e.get('selection');monitor=copy.deepcopy(e.get('monitor'))
  if monitor and monitor.get('result'):
   result=monitor['result'];result.pop('algorithm_identity',None);counts['monitored']+=1;counts[result['status']]+=1
   d=result.get('diagnostics',{});reactions=d.get('reactions',[])
   for node in d.get('nodes',[]):
    id=node['item_id'];incoming=[r for r in reactions if r['lower']==id];outgoing=[r for r in reactions if r['upper']==id];cx,cy=node['own_center_mm'][:2]
    residual=[sum(r['mass_kg'] for r in outgoing)-sum(r['mass_kg'] for r in incoming)-node['own_mass_kg'],sum(r['mass_kg']*(r['point_mm'][0]-cx) for r in outgoing)-sum(r['mass_kg']*(r['point_mm'][0]-cx) for r in incoming),sum(r['mass_kg']*(r['point_mm'][1]-cy) for r in outgoing)-sum(r['mass_kg']*(r['point_mm'][1]-cy) for r in incoming)]
    ok=abs(residual[0])<=node['mass_tolerance_kg'] and max(map(abs,residual[1:]))<=node['moment_tolerance_kg_mm']
    arithmetic.append({'job_id':j['job_id'],'decision_id':e.get('decision_id'),'item_id':id,'mass_residual_kg':residual[0],'moment_residual_kg_mm':residual[1:],'within_saved_tolerances':ok})
  r=ledgers[str(run)].get(e.get('decision_id'));raw=None
  if r and r.get('transport') and r['transport'].get('raw_body_b64'):
   rawbytes=base64.b64decode(r['transport']['raw_body_b64']);assert hashlib.sha256(rawbytes).hexdigest()==r['transport']['raw_sha256'];raw=rawbytes.decode('utf-8')
  if selection and selection.get('source')=='jev' and selection.get('probabilities'):
   assert set(selection['probabilities'])==set(mapping),'missing candidate probability'
   counts['scored_decisions']+=1;counts['candidate_probabilities']+=len(mapping)
   tie_decisions.append({'job_id':j['job_id'],'method_id':j['method_id'],'task_id':j['task_id'],'algorithm':row['algorithm'],'step':len(events),'decision_id':e['decision_id'],'injected_count':len((request or {}).get('state',{}).get('memories',[])),**probability_ties(selection['probabilities'],selection['selected_display_id'])})
  if selection and selection.get('selected_display_id') and j['method_id'] in methods[:2]:
   criteria=context['criteria'];key=lambda l:(-criteria[l]['features']['geometry_score'],criteria[l]['pose']['x_mm'],criteria[l]['pose']['y_mm'],criteria[l]['pose']['z_base_mm'],criteria[l]['pose']['yaw_deg'],criteria[l]['pick_object'])
   expected=min(criteria,key=key) if j['method_id']==methods[0] else min(criteria)
   assert expected==selection['selected_display_id'];counts['local_rule_verified']+=1
  if e['event']=='PLACE':counts['committed']+=1
  mem=copy.deepcopy(context.get('memory_view'));entries=(request or {}).get('state',{}).get('memories',[])
  if mem:mem.pop('entries',None)
  for entry in entries:library[hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()]=entry
  events.append({'event_index':i,'decision_id':e.get('decision_id'),'event':e['event'],'reason':e.get('reason'),'route':e.get('route'),'before':e['before'],'after':e['after'],'action':e.get('action'),'proposed_action':e.get('proposed_action'),'request':request,'mapping':mapping,'candidates':candidates,'generation_counts':bundle.get('generation_counts',[]),'physical_count':len(physical),'unshown_candidates':[c for id,c in physical.items() if id not in {m['candidate_id'] for m in mapping.values()}],'selection':selection,'monitor':monitor,'memory':mem,'retrieval':context.get('retrieval_receipt'),'raw_response':raw,'transport':{k:r['transport'].get(k) for k in ['status','network_attempted','http_status','error_code','error_stage','latency_s']} if r and r.get('transport') else None,'request_state':r['state'] if r else None,'timings':e.get('timings'),'binding':context.get('local_binding'),'evidence':{'checkpoint':str(folder/'checkpoint.json'),'json_pointer':f'/events/{i}','checkpoint_sha256':SOURCES[str(folder/'checkpoint.json')]}})
  if request is None and context.get('criteria'):events[-1]['prepared_criteria']=copy.deepcopy(context['criteria'])
  if not entries and (context.get('memory_view') or {}).get('entries'):events[-1]['prepared_memory_entries']=copy.deepcopy(context['memory_view']['entries'])
 data={'id':j['job_id'],'method':j['method_id'],'method_name':names[methods.index(j['method_id'])],'task_id':j['task_id'],'items':task['items'],'container':task['container'],'events':events,'event_log':flow,'metrics':metric,'status':status,'source':row,'rule':local_rule,'algorithm_identity':j['config']['stability_monitor']['algorithm_identity'],'monitor_config':j['config']['stability_monitor']['kernel_config'],'config':j['config']}
 audit_jobs[data['id']]=data
 js(WEB/'data'/f'{j["job_id"]}.js',f'window.JN4_JOBS["{j["job_id"]}"]',data)
 jobcards.append({k:data[k] for k in ['id','method','method_name','task_id','status','metrics'] }|{'algorithm':row['algorithm'],'source_digest':row['source_manifest_digest'],'source_revision':row['source_delivery_commit'],'run':str(run),'steps':len(events),'committed':metric['loading']['placed_items'],'items':len(task['items'])})
 counts['decisions_and_stops']+=len(events);counts['all_events']+=len(flow)
print(dict(counts))
assert len(jobcards)==36 and counts['committed']==602 and counts['scored_decisions']==411 and counts['STABLE']==602 and counts['UNASSESSABLE']==1
assert all(r['within_saved_tolerances'] for r in arithmetic)
# Do not duplicate the per-step memory/area ledgers in the small overview index.
for card in jobcards:card['metrics']={k:card['metrics'][k] for k in ['loading','actual_height_mm','envelope_utilization','fixed_container_utilization','stable_complete','cost','monitor_statuses','memory_metrics']};card['metrics']['memory_metrics']={k:v for k,v in card['metrics']['memory_metrics'].items() if k!='decisions'}
snapshots={}
for mode,key in [('T','cases'),('E','cards')]:
 snap=p['snapshots'][mode];snapshots[mode]={k:snap[k] for k in ['snapshot_digest','retrieval_rule','review_status','source_groups','frozen_at'] if k in snap}
 snapshots[mode]['entries']=[{k:entry[k] for k in ['case_digest','public_digest','public_fragment','provenance','review_status','evidence','fact_audit','semantic_review'] if k in entry} for entry in snap[key]]
# Read only the two unique training decisions actually underlying the frozen T/E cards.
historical={}
for mode,snap in snapshots.items():
 for ordinal,entry in enumerate(snap['entries'],1):
  source=entry['provenance']['snapshot_path']
  if source not in historical:
   fork=read(source)['value'];snapshot=fork['snapshot'];record_path=Path(snapshot['parent_identity']['parent'])/'run'/snapshot['record'];record=read(record_path)
   assert record['record_digest']==snapshot['parent_record_digest']
   native=fork['selection']['native_probabilities'];selection=record['selection']
   assert native==selection['probabilities'] and fork['selection']['native_probability_complete']
   historical[source]={'snapshot_path':source,'record_path':str(record_path),'record_sha256':SOURCES[str(record_path)],'record_digest':record['record_digest'],'decision_id':snapshot['decision_id'],'source_group':snapshot['source_group'],'probabilities':native,'branches':[{k:b[k] for k in ['parent_display_id','native_probability','intervention']} for b in fork['selection']['branches']],'library_refs':[],**probability_ties(native,selection['selected_display_id'])}
  historical[source]['library_refs'].append(mode+'-'+str(ordinal))
assert len(tie_decisions)==411 and sum(x['top_tie'] for x in tie_decisions)==37
assert sum(x['any_tie'] for x in tie_decisions)==404
assert len(historical)==2 and all(not x['top_tie'] and x['any_tie'] for x in historical.values())
tie_audit={'version':'jn4_saved_probability_ties_v1','semantics':'Exact equality of finite native saved numbers before display rounding; no epsilon or normalization','decisions':tie_decisions,'historical_sources':list(historical.values()),'scored_decisions':len(tie_decisions),'top_tied_decisions':sum(x['top_tie'] for x in tie_decisions),'any_tied_decisions':sum(x['any_tie'] for x in tie_decisions)}
write(OUT/'probability_tie_audit.json',tie_audit)
run_history=[]
for run in plans:
 hist=read(Path(run)/'summary.json');run_history.append({'run':run,**{k:hist[k] for k in ['status','planned_jobs','categories','request_statistics'] if k in hist}})
run_history[0]['technical_failure']=read(Path(run_history[0]['run'])/'technical_failure.json')
memory_audit=build_audit(audit_jobs,snapshots,pairs)
write(OUT/'memory_hit_audit.json',memory_audit)
js(WEB/'index-data.js','window.JN4_INDEX',{'memory_hits':memory_audit,'probability_ties':tie_audit,'run_history':run_history,'jobs':jobcards,'pairs':pairs,'summary':summary,'counts':dict(counts),'methods':[{'id':m,'name':n} for m,n in zip(methods,names)],'memory_library':list(library.values()),'snapshots':snapshots,'built_on':'2026-11-09','scope':'合成组合订单 · 36个原始槽位 · 旧7项v2 / 后29项v3 · 仅回看保存事实'})
write(OUT/'source_manifest.json',SOURCES)
# Existing historical floating-point arithmetic receipt remains byte-identical.
# Current arithmetic was checked above; Python versions may differ at roundoff scale.
if (OUT/'arithmetic_audit.json').exists():
 prior=json.loads((OUT/'arithmetic_audit.json').read_text())
 assert prior['node_checks']==len(arithmetic) and prior['failed']==0
 assert [(r['job_id'],r['decision_id'],r['item_id'],r['within_saved_tolerances']) for r in prior['rows']]==[(r['job_id'],r['decision_id'],r['item_id'],r['within_saved_tolerances']) for r in arithmetic]
else:write(OUT/'arithmetic_audit.json',{'type':'saved_reactions_arithmetic_only_not_new_LP','node_checks':len(arithmetic),'failed':0,'rows':arithmetic})
write(OUT/'export_receipt.json',{'status':'PASS_DATA_EXPORT','memory_hit_audit':{'version':memory_audit['version'],'counts':memory_audit['counts'],'assessment_type':'POST_HOC_DESCRIPTIVE_RETRIEVAL_AUDIT'},'counts':dict(counts),'source_files':len(SOURCES),'source_changed':False,'model_calls':0,'credential_reads':0,'solver_calls':0,'episode_runs':0,'limitations':['Jev Choice has no saved natural-language reasoning','Candidate probabilities are raw reported values, not utility or PCT scores','No PCT assessment exists for unselected alternatives','Same step across different method trajectories need not share state or pool','Kernel reaction coordinates are corner-based; viewport is bottom-center-based','Full task inventory is retrospective, not a model input']})
