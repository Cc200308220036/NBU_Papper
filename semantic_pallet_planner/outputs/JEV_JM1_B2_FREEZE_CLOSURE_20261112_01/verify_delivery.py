"""Read-only verification: prints receipt, never updates old or current artifacts."""
import hashlib,json
from pathlib import Path
from semantic_pallet_planner.jev_select import packaging_jev_training_freeze as f
from semantic_pallet_planner.jev_select.experiment import source_manifest
root=Path.cwd();out=Path(__file__).resolve().parent
manifest=json.loads((out/'delivery_manifest.json').read_text())
for row in manifest['files']:
 raw=(root/row['path']).read_bytes()
 assert hashlib.sha256(raw).hexdigest()==row['sha256'] and len(raw)==row['bytes'],row['path']
assert source_manifest()==json.loads((out/'source_manifest.json').read_text())
receipt=json.loads((out/'formal_freeze.json').read_text())
checked=f.validate_frozen_plan(receipt,root=root)
assert checked==json.loads((out/'freeze_validation.json').read_text())
assert not Path(receipt['runtime_root']).exists()
print(json.dumps({'version':'jm_b2_closure_delivery_check_v1','manifest_files':len(manifest['files']),'bytes':'PASS','frozen_plan':checked,'runtime_output_created':False,'read_only':True},ensure_ascii=False))
