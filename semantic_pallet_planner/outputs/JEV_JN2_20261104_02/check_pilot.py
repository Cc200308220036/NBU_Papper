from pathlib import Path
import shutil
from semantic_pallet_planner.jev_select import packaging_comparisons as c
from semantic_pallet_planner.jev_select import packaging_counterfactual as f
from semantic_pallet_planner.jev_select.ledger import read,write
root=Path('semantic_pallet_planner/outputs/JEV_JN2_20261104_02')
validation=c.validate(root,deep=False)
s=read(root/'comparison_summary.json');assert s['budget']['A_used']==3 and s['budget']['B_started']==3 and s['budget']['cumulative_started']==6
assert read(root/'batch_status.json')['state']=='PAUSED'
write(root/'pilot_gate.json',{'status':'PASS','validation':validation,'validation_scope':'canonical input + saved receipt/metric/label derivation; F01 frozen runner performed its standard validation before returning',
 'completed_group':'F01','completed_files_sha256':f.file_manifest(root/'forks/F01'),'A_files_sha256':f.file_manifest(Path(c.A_DEFAULT)),
 'budget':s['budget'],'new_model_calls':0})
for n in ['comparison_summary.json','budget_ledger.json','comparison_dataset_receipt.json','source_index.json']:
 target=root/'pilot_snapshot'/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/n,target)
shutil.copytree(root/'comparisons',root/'pilot_snapshot/comparisons')
print({'status':'PASS','cumulative_suffixes':6,'remaining_registered_suffixes':6})
