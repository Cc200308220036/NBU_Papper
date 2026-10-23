"""Run unmodified frozen C replay with actual dataset/protection path mapping."""
import sys
from pathlib import Path
actual=Path('/home/cyw/NBU_Papper')
sys.path.insert(0,str(actual/'semantic_pallet_planner/outputs/EXP_O4_C_ONLINE_20261021_01/code_snapshot/semantic_pallet_planner/src'))
import semantic_pallet_planner.config as cfg
cfg.DEFAULTS['dataset']=str(actual/'semantic_pallet_dataset_v1')
from semantic_pallet_planner.runners import o4 as ab
from semantic_pallet_planner.runners import o4_online as c
from semantic_pallet_planner.o4.common import write
original=ab.check_protected

def check(hashes):
    saved=ab.WORKSPACE
    try:
        ab.WORKSPACE=actual
        return original(hashes)
    finally:ab.WORKSPACE=saved

c.check_protected=check
result=c.replay(actual/'semantic_pallet_planner/outputs/EXP_O4_C_ONLINE_20261021_01',check_protection=True)
result['snapshot_execution_context']={'source':'unmodified C frozen code_snapshot','dataset_mapping':cfg.DEFAULTS['dataset'],
                                    'protection':'enabled; original hash checker against actual workspace'}
write(actual/'report/analysis/O4_F_BUFFER_20261021_01/legacy_c_snapshot_replay.json',result)
print(result)
if result['status']!='PASS':raise SystemExit(1)
