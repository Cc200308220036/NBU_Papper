"""Static control-flow probe on a NEW copy of constructed saved records.
Runs ONLY the source AST of validate_saved_execution with identity/schema
preconditions replaced by read-only checks of unchanged archived JSON.
NOT a full production-validator execution or order/fork recovery test.
No project imports, selector, monitor, commit, model, network or credentials.
"""
from pathlib import Path
import ast,hashlib,json,shutil,types
R=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent
B=R/'semantic_pallet_planner/outputs/JEV_JM1_A3_20261111_01'
def read(p):return json.loads(Path(p).read_text())
def dg(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def require(ok,code):
 if not ok:raise ValueError(code)
def check_seal(v):require(v['record_digest']==dg({k:x for k,x in v.items() if k!='record_digest'}),'seal')
origin=R/read(B/'constructed_evidence_index.json')['valid_recovery_runs'][0]
# Original is a valid completed NEW A3 construction, not historical model data.
activation=read(origin/'activation.json');rows=read(origin/'ledger/requests.json')['requests']
require(bool(rows),'probe needs saved requests')
clone=O/'missing_journal_control_flow_copy'
if not clone.exists():
 clone.mkdir();shutil.copy2(origin/'activation.json',clone/'activation.json');shutil.copytree(origin/'ledger',clone/'ledger')
require(not (clone/'stages').exists() and not (clone/'checkpoint_head.json').exists() and not(clone/'episode.json').exists(),'copy must have no progress journal/head/episode')
ex=activation['execution'];initial=activation['initial_checkpoint']
known_contexts={p.stem:read(p) for p in (origin/'ledger/contexts').glob('*.json')}
known_reservations={p.stem:read(p) for p in (origin/'ledger/reservations').glob('*.json')}
class Context:
 @classmethod
 def from_dict(cls,data):return types.SimpleNamespace(data=data)
class SavedLedger:
 def __init__(self,root):
  self.data=read(root/'requests.json');check_seal(self.data)
  require(read(root/'execution.json')==ex,'execution anchor')
  for row in self.data['requests']:
   c=read(root/'contexts'/(row['decision_id']+'.json'))
   require(c==known_contexts[row['decision_id']] and row['context_digest']==dg(c),'context identity')
   require(row['body_digest']==dg(c['request_body']) and row['mapping_digest']==dg(c['display_mapping']),'body/map identity')
 def check_context(self,ctx,job,did):require(ctx.data==known_contexts[did] and job==ex['branch_id'],'known valid context')
 def reservation(self,ctx,job,did):return known_reservations[did]
def validate_execution(value):
 require(value==ex,'unchanged execution');check_seal(value);return (None,None)
def validate_cp(value,value_ex,**kw):
 require(value==initial and value_ex==ex,'unchanged initial checkpoint');check_seal(value)
def shape(name,value):
 # Only activation is reached with an empty journal; unchanged archive bytes.
 require(name=='jm_activation_v1' and value==activation,'unchanged activation')
source=R/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_jev_recovery.py'
fn=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='validate_saved_execution')
env={'Path':Path,'read':read,'validate_schema':shape,'check_seal':check_seal,'validate_execution':validate_execution,'require':require,'validate_saved_checkpoint':validate_cp,'digest':dg,'_ledger_readonly':lambda root,execution,**kw:SavedLedger(root),'DecisionContext':Context}
exec(compile(ast.Module(body=[fn],type_ignores=[]),'<read-only saved-validator control flow>','exec'),env)
result=env['validate_saved_execution'](clone,expected_execution=ex)
summary={'version':'jm1_a3_missing_journal_control_flow_probe_v1','scope':'EXACT_VALIDATE_SAVED_EXECUTION_AST_WITH_ALREADY_VALID_IDENTITY_PRECONDITIONS; NOT_FULL_PRODUCTION_VALIDATOR','source':str(source.relative_to(R)),'copied_from':str(origin.relative_to(R)),'copy':str(clone.relative_to(R)),'copied_files_unchanged':all(p.read_bytes()==(origin/p.relative_to(clone)).read_bytes() for p in clone.rglob('*') if p.is_file()),'missing':['stages/*.json','checkpoint_head.json','episode.json'],'returned_phase':result['checkpoint']['phase'],'returned_decision':result['checkpoint']['decision'],'returned_sequence':result['sequence'],'preserved_requests':result['requests'],'preserved_request_states':result['states'],'finding':'Control flow returns initial forced SELECTED despite intact later request history; no reverse ledger-to-checkpoint progress consistency check. On resumption run_repeat would use this returned checkpoint; actual resumption NOT_RUN.','business_dispatches':0,'full_production_validator_run':False,'identity_adapter_limit':'Identity/schema helpers are substituted, and only accept original unchanged recorded activation/initial checkpoint/contexts. No claim of full validator or runtime replay passing.'}
(O/'missing_journal_probe.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ['returned_phase','returned_decision','returned_sequence','preserved_requests','preserved_request_states','copied_files_unchanged','full_production_validator_run']},ensure_ascii=False))
