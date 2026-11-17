"""Real saved-input consumer calls, no generation or execution. Run before/after fix."""
import json
from pathlib import Path
from semantic_pallet_planner.jev_select.candidate_backends import GeometryCandidateBundle
from semantic_pallet_planner.jev_select.candidates import PublicBusinessGuard
from semantic_pallet_planner.jev_select.context import ContextBuilder,validate_context
from semantic_pallet_planner.jev_select.contracts import PublicPolicyContext,digest
from semantic_pallet_planner.jev_select.packaging_runtime import build_context
p=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N2_20261117_01/cases/empty')
def read(p):return json.loads(p.read_bytes())
new=p/'ems_surface_hybrid_v1';cfg=read(p/'e2_original_v1/config.json');obs=read(new/'observation.json')
bundle=GeometryCandidateBundle.from_artifacts(read(new/'bundle.json'),read(new/'audit.json'),read(new/'telemetry.json'))
policy=PublicPolicyContext.from_dict(read(new/'public_policy.json'))
# Saved mismatched context exists only in this new remediation evidence after real pre-fix build.
out=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N2_R1_20261117_01')
def full():
 from semantic_pallet_planner.jev_select.contracts import DecisionContext
 return validate_context(DecisionContext.from_dict(read(out/'before_mismatched_context.json')),obs,bundle,cfg)
rows=[]
for name,call in [('filter',lambda:PublicBusinessGuard().filter(obs,policy,bundle,cfg)),('ContextBuilder',lambda:ContextBuilder(cfg).build(obs,bundle,policy)),('direct_F0',lambda:build_context(cfg,obs,bundle,policy)),('full_context',full)]:
 try:
  result=call()
  if name=='ContextBuilder' and not (out/'before_mismatched_context.json').exists():
   (out/'before_mismatched_context.json').write_text(json.dumps(result.data,ensure_ascii=False,indent=2)+'\n')
  rows.append({'entry':name,'result':'ACCEPTED_MISMATCH_FAIL','error':None})
 except Exception as e:rows.append({'entry':name,'result':'REJECTED','error':str(e),'type':type(e).__name__})
print(json.dumps({'input_config_digest':digest(cfg),'bundle_config_digest':digest(bundle.audit['config']),'rows':rows,'generation_calls':0,'requests_sent':0},ensure_ascii=False,indent=2))
