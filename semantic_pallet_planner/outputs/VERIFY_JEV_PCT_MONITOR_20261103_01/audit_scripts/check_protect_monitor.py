from pathlib import Path
import json,hashlib
repo=Path('/home/cyw/NBU_Papper');r=repo/'semantic_pallet_planner/outputs/VERIFY_JEV_PCT_MONITOR_20261103_01'
before=json.loads((r/'protected_before.json').read_text());changed=[]
for name,sha in before.items():
 p=repo/name
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:changed.append(name)
v={'files':len(before),'changed':changed,'all_identical':not changed,'scope':'inventory captured after code edits, before smoke; Git also confirms tracked historical/original paths unchanged'}
(r/'protected_after.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v));assert not changed
