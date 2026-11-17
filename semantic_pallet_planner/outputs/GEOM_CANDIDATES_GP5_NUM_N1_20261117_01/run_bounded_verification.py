"""N1 fixed validation; stop first unexpected E failure, never extend matrix.
No freezer/real-kernel/network calls. Uses the existing TEST_DOUBLE interface.
"""
import copy,json,socket,traceback
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from test_geometry_order_p1 import SNAP,adapted,monitor_double
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p,geometry_order_execution as o
from semantic_pallet_planner.jev_select.contracts import digest,canonical,validate_schema,JevSelectError
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields
from semantic_pallet_planner.jev_select.geometry_native_shape_bridge import restore_size,N,unN,H,L,B
from semantic_pallet_planner.jev_select.geometry_runtime_contracts import same_native
OUT=Path(__file__).parent

def write(name,v):
 path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')

def main():
 rows=[]
 for tag,values in [('I',[100,80,60]),('F',[100.0,80.5,60.25]),('M',[100,80.0,60])]:
  for yaw in (0,90):
   dims=dict(zip(('length','width','height'),values));target=values if yaw==0 else [values[1],values[0],values[2]]
   raw=[float(target[0]),float(target[1]),target[2]];restored,proof=restore_size(raw,dims,yaw)
   assert same_native(restored,target) and same_native(unN(N(restored)),restored)
   payload={'native_tree':N(restored)}
   rows.append({'case':tag+str(yaw),'source':dims,'raw':raw,'target':restored,'axis_equalities':proof,'H':H('target_size',payload),'L':L(restored),'B':B(canonical(restored).encode()),'status':'PASS'})
 write('C_results.json',rows)
 negative=[]
 for name,args in [('bool',([True,80,60],{'length':100,'width':80,'height':60},0)),('rounding',([99.99999999999999,80,60],{'length':100,'width':80,'height':60},0)),('unrepresentable',([9007199254740992.0,80,60],{'length':9007199254740993,'width':80,'height':60},0)),('axis',([100,80,60],{'length':100,'width':80,'height':60},90)),('yaw_float',([100,80,60],{'length':100,'width':80,'height':60},0.0))]:
  try:restore_size(*args)
  except JevSelectError as exc:negative.append({'case':name,'status':'REJECTED','code':exc.code})
  else:raise AssertionError(name)
 write('X_pure_results.json',negative)
 tasks=[adapted('K02_INT'),adapted('K02')]
 plan=p.prepare_order_plan(tasks,data_identity=digest('NUM_N1_FIXED_SYNTHETIC'),scope=p.DEVELOPMENT,native=True)
 adm={**identity_fields(plan),'version':'geometry_development_binding_v2','scope':p.DEVELOPMENT,'evidence':'TEST_DOUBLE','plan_digest':digest(plan)}
 write('plan.json',plan);write('admission.json',adm);write('monitor_snapshot.json',SNAP)
 results=[];totalcalls=[]
 with ExitStack() as stack:
  for name in ('exact_adapter.assess_candidate','balance_adapter.assess_candidate','balance_network.solve_network','balance_network.linprog','monitor.exact_freeze','monitor.freeze'):
   stack.enter_context(patch('semantic_pallet_planner.jev_select.stability.'+name,side_effect=AssertionError('REAL_KERNEL_FREEZE_LP_FORBIDDEN')))
  stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')))
  for job in plan['jobs']:
   task=next(t for t in tasks if t['identity']['task_id']==job['task_id']);calls=[];cps=[]
   try:
    with monitor_double(calls):result=o.run_order_job(plan,job['job_id'],task,monitor_snapshot=SNAP,admission=adm,root=OUT/'E',on_checkpoint=lambda cp:cps.append(copy.deepcopy(cp)))
    totalcalls+=calls;write('E/'+job['job_id']+'_phases.json',cps)
    row={'job_id':job['job_id'],'task_id':job['task_id'],'backend':job['backend'],'method':job['method'],'monitor_calls':len(calls),'completed':result['summary']['completed'],'placed_items':result['summary']['placed_items'],'reason':result['summary']['termination_reason']}
    results.append(row);write('E_results.json',results);write('test_double_calls.json',totalcalls)
    if not row['completed']:
     write('stop.json',{'status':'STOPPED_UNEXPECTED_TECHNICAL_OR_FIXED_FIXTURE_FAILURE','job':row,'no_retry':True,'remaining_jobs':'NOT_RUN','R':'NOT_RUN','reason':'User/QA explicit stop condition; no matrix expansion'})
     return 2
   except Exception as exc:
    totalcalls+=calls;write('E/'+job['job_id']+'_phases.json',cps);write('test_double_calls.json',totalcalls)
    write('stop.json',{'status':'STOPPED_UNEXPECTED_TECHNICAL_FAILURE','job':job,'type':type(exc).__name__,'detail':str(exc),'traceback':traceback.format_exc(),'no_retry':True,'remaining_jobs':'NOT_RUN','R':'NOT_RUN'})
    return 2
 write('E_results.json',results)
 return 0
if __name__=='__main__':raise SystemExit(main())
