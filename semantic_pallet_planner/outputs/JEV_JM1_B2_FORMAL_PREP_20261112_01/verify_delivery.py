"""Read-only delivery bytes/source/plan validation; no dispatch/replay/LP."""
import hashlib
import json
from pathlib import Path
from semantic_pallet_planner.jev_select import packaging_jev_training_plan as p
from semantic_pallet_planner.jev_select.experiment import source_manifest

root=Path.cwd()
out=Path(__file__).resolve().parent
manifest=json.loads((out/'delivery_manifest.json').read_text())
for row in manifest['files']:
    raw=(root/row['path']).read_bytes()
    assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'],row['path']
assert json.loads((out/'source_manifest.json').read_text())==source_manifest(),'runtime source drift'
value=json.loads((out/'materials/training_plan.json').read_text())
checked=p.validate_plan(value,root=root)
assert checked==json.loads((out/'saved_validation.json').read_text()),'saved receipt drift'
assert not (out/'materials/future_runs').exists(),'unexpected runtime output'
receipt={'version':'jm_b2_offline_delivery_check_v1','manifest_files':len(manifest['files']),
         'bytes':'PASS','source_identity':'PASS','saved_plan':checked,'runtime_output_created':False,
         'manifest_self_and_this_receipt_excluded':True}
(out/'delivery_checks.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False))
