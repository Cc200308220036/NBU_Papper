"""Recompute saved diagnostic geometry only; no candidates/episodes/LP."""
import sys,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent;B=R/'semantic_pallet_planner/outputs/JEV_JM_REV1_FS_ENGINEERING_20261116_01'
sys.path[:0]=[str(R/'semantic_pallet_planner/src'),str(R/'semantic_pallet_planner/tests/unit')]
import test_packaging_scenario_features
from semantic_pallet_planner.jev_select import packaging_fs_geometry as g
rows=[]
for row in json.loads((B/'saved_state_coverage.json').read_text())['rows']:
 raw=(R/row['input']['path']).read_bytes();assert g.sha(raw)==row['input']['sha256']
 old=json.loads((R/row['result']['path']).read_text())['semantic'];new=g.evaluate(raw,expected_sha256=row['input']['sha256'])['semantic']
 assert new==old
 rows.append(dict(point=row['point_id'],mode=row['mode'],status=new['status'],direction=new['contrast']['direction']))
(O/'static_checks.json').write_text(json.dumps(dict(version='rev1_fs_qa_recompute_v1',status='PASS',rows=rows,scope='10 saved geometry diagnostic scopes;not physical replay',original_verifier='PASS594 identities and10 seals',local_tests=dict(passed=9,errors=1,reason='legacy contracts f-string Python3.9 incompatibility')),ensure_ascii=False,indent=2)+'\n')
print('PASS10_EXACT_SEMANTIC_RECOMPUTATIONS')
