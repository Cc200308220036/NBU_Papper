"""Freeze then ONE main provider call per admitted point/backend; never execute."""
import argparse,copy,sys,time,traceback
from gp4_common import *

def freeze():
 if (OUT/'freeze_manifest.json').exists():raise RuntimeError('comparison already frozen; never resign')
 from semantic_pallet_planner.jev_select.candidate_backends import load_geometry_config,backend_config
 from semantic_pallet_planner.jev_select.geometry_runtime_contracts import environment
 source=read(OUT/'source_manifest.json')['files']
 root=Path('semantic_pallet_planner/src/semantic_pallet_planner')
 assert all(sha(root/n)==h for n,h in source.items())
 monitor=digest({'scope':'SAVED_STATE_COMPARISON_NO_EXECUTION_NO_MONITOR','files':{n:h for n,h in source.items() if n in ('jev_select/stability/monitor.py','jev_select/stability/exact_adapter.py','jev_select/stability/exact_contracts.py')}})
 data=digest({'scope':'SAVED_CURRENT_PUBLIC_STATES_ONLY','inputs':{p:sha(OUT/'inputs'/p/'original_snapshot.json') for p in POINTS}})
 plan={'version':'gp4_saved_state_analysis_plan_v1','scope':'GP4_SAVED_STATE_COMPARE_ONLY','points':POINTS,'state_denominator':5,'backends':BACKENDS,'profile':'geometry_runtime_shortest_decimal_v1','protocol':'jev_packaging_geometry_compare_v14','construction_only':True,'source_digest':digest(source),'data_identity':data,'monitor_identity':monitor,'generations_per_admitted_point_backend':1,'replacement_points':False,'extra_seeds':False,'input_adapter':'gp4_current_saved_public_adapter_v1','input_source':'GP0 frozen snapshots + leaf provenance only; no source episode/task reads','matching':['box','oriented_size','yaw','exact published pose shortest-decimal mathematical value'],'numeric_rules':'Fraction(int) or Fraction(repr(finite float)); no epsilon; 2==2.0; -0==0; square-yaw equivalence separate','raw_pool_rules':'NEW complete raw passing all original checks; OLD raw NOT_AVAILABLE, enum projection separate','surface_contribution':'raw valid with SURFACE_CORNER and not EMS_STYLE_3D; not a rerun ablation','timing':'single fresh generator process; sequential fixed order OLD then NEW for each point; actual E2 cache deltas; no clearing or repeated trials','F0':'same existing projection/question/anonymous/seed and 96000 bytes; construct only; no send; technical audit outside body','backend_error':'whole arm ERROR, no partial pool/no fallback; item results null with audit counters separate','common_failure':'whole point NOT_COMPARABLE_RUNTIME_INPUT; backend NOT_RUN; no generation','interpretation':'candidate set differences, not whole-order/Jev benefit/global completeness','model_calls':0,'PCT_LP_calls':0,'execution_calls':0,'historical_gp0_plan':'DRAFT_REFERENCE_ONLY_NOT_RESIGNED'}
 save(OUT/'comparison_plan.json',plan);save(OUT/'environment.json',environment())
 for point in POINTS:
  task_id=digest({'scope':'SAVED_STATE_ANALYSIS_NOT_TASK_EXECUTION','point':point,'raw_sha':sha(OUT/'inputs'/point/'original_snapshot.json')})
  for backend in BACKENDS:
   cfg=load_geometry_config(backend=backend,data_identity=data,task_identity=task_id,monitor_identity=monitor)
   assert cfg['construction_only'] and cfg['runtime_identity']['source_identity']==digest(source)
   save(OUT/'configs'/point/(backend+'.json'),cfg)
   save(OUT/'configs'/('generator_'+backend+'.json'),backend_config(backend))
 paths=[p for folder in ('inputs','configs','historical') for p in (OUT/folder).rglob('*') if p.is_file()]
 paths += [OUT/n for n in ('source_manifest.json','comparison_plan.json','environment.json','gp4_common.py','gp4_runner.py','gp4_analysis.py','gp4_plots.py','test_analysis.py','comparison_result.schema.json')]
 save(OUT/'freeze_manifest.json',{'version':'gp4_analysis_freeze_v1','status':'FROZEN_BEFORE_ANY_GENERATION','files':[{'path':p.as_posix(),'sha256':sha(p)} for p in sorted(set(paths))]})
 print('FROZEN_NO_GENERATION',flush=True)

def generate():
 for r in read(OUT/'freeze_manifest.json')['files']:assert sha(r['path'])==r['sha256'],r['path']
 if (OUT/'generation_started.json').exists():raise RuntimeError('main generation already reserved; no implicit retry')
 from semantic_pallet_planner.jev_select.candidate_backends import capture_common_input,validate_common_input,_admit,GeometryConstructionError
 from semantic_pallet_planner.jev_select.candidates import CandidateProvider,PublicBusinessGuard
 from semantic_pallet_planner.jev_select.context import ContextBuilder
 from semantic_pallet_planner.jev_select.config import generator_config_for
 from semantic_pallet_planner.jev_select.geometry_runtime_contracts import environment
 from semantic_pallet_planner.o4.extensions.e2.candidates import _cached_generation
 assert digest(environment())==digest(read(OUT/'environment.json'))
 assert _cached_generation.cache_info().currsize==0
 from semantic_pallet_planner.jev_select.ledger import write
 write(OUT/'generation_started.json',{'version':'gp4_one_shot_reservation_v1','scope':'five fixed saved states only','freeze_sha':sha(OUT/'freeze_manifest.json')})
 state_results=[]
 for point in POINTS:
  base=OUT/'states'/point;cfg=read(OUT/'configs'/point/(BACKENDS[0]+'.json'))
  row={'point_id':point,'common_status':None,'common_error':None,'item_ids':[],'backends':{}}
  started=time.perf_counter()
  try:
   state,obs=adapt_saved(point);row['item_ids']=[p['item']['item_id'] for p in sorted(state['pending_items'],key=lambda x:x['arrival_index'])]
   common=capture_common_input(state,obs,cfg)
   save(base/'observation.json',obs);save(base/'state.json',state)
   base.mkdir(parents=True,exist_ok=True);(base/'B_native.json').write_bytes(common[0]);(base/'B_geometry.json').write_bytes(common[1]);save(base/'common_binding.json',common[2])
   views=validate_common_input(*common,cfg,state=state,observation=obs)
   admission=_admit(views,common[2]);save(base/'common_admission.json',admission)
   row['common_status']='PASS'
  except (ValueError,KeyError,TypeError) as exc:
   row['common_status']='NOT_COMPARABLE_RUNTIME_INPUT';row['common_error']={'code':getattr(exc,'code','SAVED_INPUT_ERROR'),'detail':str(exc)}
   (base).mkdir(parents=True,exist_ok=True);(base/'common_failure.log').write_text(traceback.format_exc())
   if not row['item_ids']:row['item_ids']=[v['item_id'] for v in read(OUT/'inputs'/point/'public_provenance.json')['buffer_order']]
  row['common_admission_s']=time.perf_counter()-started
  for backend in BACKENDS:
   dest=base/backend;dest.mkdir(parents=True,exist_ok=True)
   record={'status':'NOT_RUN_COMMON_INPUT' if row['common_status']!='PASS' else None,'provider_calls':0,'error':None,'F0_status':'NOT_RUN','F0_error':None,'request_bytes':None,'provider_wall_s':None,'F0_wall_s':None,'telemetry':None}
   if row['common_status']=='PASS':
    config=read(OUT/'configs'/point/(backend+'.json'));t=time.perf_counter();record['provider_calls']=1
    # Durable per-combination reservation before the single call.
    write(dest/'generation_reserved.json',{'point':point,'backend':backend,'config_digest':digest(config)})
    try:
     bundle=CandidateProvider().build(state,obs,generator_config_for(config),config=config,common_input=common)
     record['provider_wall_s']=time.perf_counter()-t;record['status']='OK' if bundle.data['physical_candidates'] else 'OK_EMPTY'
     assert canonical(bundle.audit['common_admission'])==canonical(admission)
     policy=PublicBusinessGuard().resolve(obs);bundle=PublicBusinessGuard().filter(obs,policy,bundle,config)
     save(dest/'bundle.json',bundle.data);save(dest/'audit.json',bundle.audit);save(dest/'telemetry.json',bundle.telemetry);save(dest/'public_policy.json',policy.data)
     record['telemetry']=bundle.telemetry;t=time.perf_counter()
     try:
      ctx=ContextBuilder(config).build(obs,bundle,policy);body=ctx.data['request_body']
      save(dest/'context.json',ctx.data);save(dest/'request.json',body)
      record['F0_status']='CONSTRUCTED' if body is not None else 'NO_REQUEST_'+ctx.data['route']
      record['request_bytes']=len(canonical(body)) if body is not None else None
     except (ValueError,KeyError,TypeError) as exc:
      record['F0_status']='ERROR';record['F0_error']={'code':getattr(exc,'code','F0_CONSTRUCTION_ERROR'),'detail':str(exc)}
      (dest/'F0_failure.log').write_text(traceback.format_exc())
     record['F0_wall_s']=time.perf_counter()-t
    except GeometryConstructionError as exc:
     record.update(status='ERROR',provider_wall_s=time.perf_counter()-t,error={'scope':exc.scope,'code':exc.code,'detail':str(exc)},telemetry=exc.telemetry)
     save(dest/'audit.json',exc.audit);save(dest/'telemetry.json',exc.telemetry);(dest/'generation_failure.log').write_text(traceback.format_exc())
    except (ValueError,KeyError,TypeError) as exc:
     record.update(status='ERROR',provider_wall_s=time.perf_counter()-t,error={'scope':'BACKEND_OR_PUBLIC_VALIDATION_ERROR','code':getattr(exc,'code','PROVIDER_VALIDATION_ERROR'),'detail':str(exc)})
     (dest/'generation_failure.log').write_text(traceback.format_exc())
   row['backends'][backend]=record;save(dest/'outcome.json',record)
  save(base/'outcome.json',row);state_results.append(row)
  print(point,row['common_status'],{b:r['status'] for b,r in row['backends'].items()},flush=True)
 save(OUT/'generation_summary.json',{'version':'gp4_generation_summary_v1','states':state_results,'provider_calls':sum(v['provider_calls'] for r in state_results for v in r['backends'].values()),'actual_PCT_LP_calls':0,'model_calls':0,'execution_calls':0})
 assert 'semantic_pallet_planner.jev_select.stability.exact_adapter' not in sys.modules
 assert 'semantic_pallet_planner.jev_select.stability.balance_adapter' not in sys.modules
 assert 'scipy.optimize' not in sys.modules
 print('GENERATION_COMPLETE_NO_EXECUTION_NO_KERNEL',flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('freeze','generate'));a=p.parse_args()
 freeze() if a.mode=='freeze' else generate()
