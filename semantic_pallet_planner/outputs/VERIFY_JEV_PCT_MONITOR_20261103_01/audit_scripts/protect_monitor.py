from pathlib import Path
import hashlib,json
repo=Path('/home/cyw/NBU_Papper');out=repo/'semantic_pallet_planner/outputs/VERIFY_JEV_PCT_MONITOR_20261103_01'
roots=[repo/'semantic_pallet_planner/outputs',repo/'Online-3D-BPP-PCT']
paths=[repo/'.gitignore']
for root in roots:
 if root.exists():paths.extend(p for p in root.rglob('*') if p.is_file() and out not in p.parents and '.git' not in p.parts and '__pycache__' not in p.parts)
manifest={str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
(out/'protected_before.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(len(manifest))
