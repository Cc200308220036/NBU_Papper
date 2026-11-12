"""Technical/identity/accounting continue gate; no performance-based decision."""
from pathlib import Path
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select import packaging_jev_training_freeze as f
out=Path(__file__).resolve().parent
base=Path('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01')
freeze=read(base/'formal_freeze.json');f.validate_frozen_plan(freeze,root=Path.cwd())
rows=[]
for i in (1,2,3):
 j=read(out/f'job_{i}_receipt.json');c=j['counts']
 assert j['technical_valid'] is True and c['requests']<=freeze['jobs'][i-1]['max_sends'] and c['unknown_sends']==0
 assert all(s=='SELECTION_SAVED' for s in j['ledger_states'])
 rows.append(dict(ordinal=i,job_id=j['job_id'],requests=c['requests'],max_sends=c['max_sends'],unknown_sends=c['unknown_sends'],saved_validation='PASS',identity='PASS'))
write(out/'wave1_continue_gate.json',dict(version='jm_c1_wave1_technical_continue_v1',technical_continue=True,criterion='identity, saved stage/ledger closure and per-job accounting only; no reward or packing metrics used',jobs=rows,actual_requests=sum(x['requests'] for x in rows),wave_upper=51,next_wave_registered_upper=52,global_upper=103,no_budget_reallocation=True))
print('PASS_TECHNICAL_CONTINUE_ONLY')
