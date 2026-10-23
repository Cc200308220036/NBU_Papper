"""Replay frozen A/B logic using C's complete historical source snapshot.

Only workspace resolution for the original protection check is remapped; it
still computes and compares all real original file hashes.
"""
import sys
from pathlib import Path
actual=Path('/home/cyw/NBU_Papper')
sys.path.insert(0,str(actual/'semantic_pallet_planner/outputs/EXP_O4_C_ONLINE_20261021_01/code_snapshot/semantic_pallet_planner/src'))
import semantic_pallet_planner.config as cfg
cfg.DEFAULTS['dataset']=str(actual/'semantic_pallet_dataset_v1')
from semantic_pallet_planner.runners import o4 as ab
from semantic_pallet_planner.o4.common import write
original=ab.check_protected

def check(hashes):
    saved=ab.WORKSPACE
    try:
        ab.WORKSPACE=actual
        return original(hashes)
    finally:ab.WORKSPACE=saved

ab.check_protected=check
result=ab.replay(actual/'semantic_pallet_planner/outputs/EXP_O4_AB_OFFLINE_20261021_01')
result['snapshot_execution_context']={'source':'frozen C complete snapshot, containing original AB code','protection':'original hash checker against actual workspace'}
write(actual/'report/analysis/O4_F_BUFFER_20261021_01/legacy_ab_snapshot_replay.json',result)
print(result)
if result['status']!='PASS':raise SystemExit(1)
