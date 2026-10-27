"""Prove duplicate compilation/output rejection before any HTTP call."""
import shutil
from pathlib import Path
from semantic_pallet_planner.o4.common import read,write,O4Error
from semantic_pallet_planner.o4.extensions.e2.experiment import new_output
from semantic_pallet_planner.o4.extensions.e5.backends import Ledger,RemoteCompiler

WS=Path('/home/cyw/NBU_Papper')
OUT=WS/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'
ROOT=OUT/'collision_fault_copy_v2'
if ROOT.exists():raise RuntimeError('Refusing to overwrite diagnostic evidence')
shutil.copytree(OUT/'preflight_faults_snapshot06/fairness',ROOT)
source=read(ROOT/'responses/txt/D0000.json')['source_request']
calls=[]
class NoHttp:
    test_double=True
    def complete(self,*args):
        calls.append(args)
        raise AssertionError('Duplicate compilation must be rejected before HTTP')
ledger=Ledger(ROOT,4,{'txt':2,'img':2},test_double=True,resume=True)
compiler=RemoteCompiler(ROOT,NoHttp(),ledger)
rows=[]
try:compiler.compile(source,'txt',0,'text')
except O4Error as exc:
    rows.append({'purpose':'duplicate_compilation_rejected_before_http','expected':'duplicate_compilation',
                 'actual':exc.code,'passed':exc.code=='duplicate_compilation' and not calls,'http_calls':len(calls)})
else:rows.append({'purpose':'duplicate_compilation_rejected_before_http','passed':False})
try:new_output(ROOT)
except O4Error as exc:
    rows.append({'purpose':'existing_output_directory_rejected','expected':'unsafe_output','actual':exc.code,
                 'passed':exc.code=='unsafe_output' and len(ledger.rows())==2})
else:rows.append({'purpose':'existing_output_directory_rejected','passed':False})
write(OUT/'collision_fault_audit.json',{'status':'PASS' if all(r['passed'] for r in rows) else 'FAIL','faults':rows,'http_calls':len(calls)})
print({'passed':sum(r['passed'] for r in rows),'total':len(rows),'http_calls':len(calls)})
if not all(r['passed'] for r in rows):raise SystemExit(1)
