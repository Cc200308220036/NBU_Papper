"""Actual manual loop + test fault injection, no real numerical kernel or network."""
import argparse,copy,json,shutil,traceback
from pathlib import Path
from unittest.mock import patch
from test_geometry_execution_n3 import fixture,kernel_double,BACKENDS
from semantic_pallet_planner.jev_select import episode,evaluation,execution
from semantic_pallet_planner.jev_select.geometry_execution import GeometryStore,load_run_config
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
from semantic_pallet_planner.jev_select.candidates import CandidateProvider
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
p=argparse.ArgumentParser();p.add_argument('stage',choices=('before','after'));args=p.parse_args()
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_R1_20261117_01')
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
rows=[]
for kind,backend in [('evaluation_failure',BACKENDS[0]),('commit_failure',BACKENDS[1])]:
 root=OUT/args.stage/kind;store=GeometryStore(root/'durable');cps=[];assess=[]
 task=fixture();cfg=load_run_config(backend=backend,task=task,data_identity=digest('N3_R1_SAME_MANUAL_FIXTURE'))
 def run(resume=None):return episode.run_episode(task,LocalPackagingDouble(),cfg,job_id='R1',method=cfg['selector'],geometry_store=store,on_checkpoint=lambda cp:cps.append(copy.deepcopy(cp)),resume=resume)
 original_eval=evaluation.evaluate_committed_state;original_commit=execution.commit_physical;original_gen=CandidateProvider.build;original_select=LocalPackagingDouble.select
 counts={'generation':0,'selection':0,'monitor':0,'commit':0,'evaluation':0}
 def gen(self,*a,**kw):counts['generation']+=1;return original_gen(self,*a,**kw)
 def select(self,*a,**kw):counts['selection']+=1;return original_select(self,*a,**kw)
 def commit(*a,**kw):
  counts['commit']+=1
  if kind=='commit_failure' and fault[0]:raise JevSelectError('TEST_DOUBLE_COMMIT_BOUNDARY','TEST_DOUBLE failure before original physical mutation')
  return original_commit(*a,**kw)
 def evaluate(*a,**kw):
  counts['evaluation']+=1
  if kind=='evaluation_failure' and fault[0] and a[0]['placed_count']:
   raise ValueError('TEST_DOUBLE_POST_COMMIT_EVALUATION')
  return original_eval(*a,**kw)
 fault=[True]
 with patch.object(CandidateProvider,'build',gen),patch.object(LocalPackagingDouble,'select',select),patch.object(execution,'commit_physical',commit),patch.object(evaluation,'evaluate_committed_state',evaluate),kernel_double(calls=assess),patch('semantic_pallet_planner.jev_select.stability.exact_adapter.assess_candidate',side_effect=AssertionError('REAL_KERNEL_FORBIDDEN')),patch('semantic_pallet_planner.jev_select.stability.balance_network.solve_network',side_effect=AssertionError('REAL_LP_FORBIDDEN')):
  produced=run();cp=copy.deepcopy(produced['checkpoint']);counts['monitor']=len(assess)
  write(root/'config.json',cfg);write(root/'task.json',task);write(root/'failure_result.json',produced);write(root/'failure_checkpoint.json',cp);write(root/'production_phases.json',cps)
  snapshot=dict(counts);cps.clear();fault[0]=False
  try:
   restored=run(cp);counts['monitor']=len(assess);delta={k:counts[k]-snapshot[k] for k in counts}
   write(root/'restored_result.json',restored)
   result={'status':'RESTORED','delta':delta,'reason':restored['checkpoint']['reason']}
  except Exception as e:
   counts['monitor']=len(assess);result={'status':'RECOVERY_REJECTED_FAIL','error':str(e),'type':type(e).__name__,'delta':{k:counts[k]-snapshot[k] for k in counts}}
   (root/'recovery_failure_traceback.log').write_text(traceback.format_exc())
  write(root/'recovery_phases.json',cps);write(root/'counts.json',{'before_resume':snapshot,'after_resume':counts,'recovery':result})
 row={'case':kind,'backend':backend,'fixture_digest':digest(task),'fault':'TEST_DOUBLE_'+kind,'config_digest':digest(cfg),'source_identity':cfg['runtime_identity']['source_identity'],'phase':cp['phase'],'reason':cp['reason'],'recovery':result};rows.append(row)
write(OUT/(args.stage+'_behavior.json'),rows)
print(json.dumps(rows,ensure_ascii=False,indent=2))
if args.stage=='after':
 assert all(r['recovery']['status']=='RESTORED' for r in rows)
 for r in rows:
  assert all(r['recovery']['delta'][k]==0 for k in ('generation','selection','monitor','commit'))
