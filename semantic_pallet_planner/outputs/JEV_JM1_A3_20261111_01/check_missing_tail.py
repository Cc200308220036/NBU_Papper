"""Two targeted pure-validation negatives over copies of NEW A3 fixtures only."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

OUT = Path(__file__).resolve().parent
REPO = OUT.parents[2]
sys.path.insert(0, str(REPO / 'semantic_pallet_planner/src'))
from semantic_pallet_planner.jev_select import packaging_jev_forks as jm
from semantic_pallet_planner.jev_select import packaging_jev_recovery as a3
from semantic_pallet_planner.jev_select import episode, execution, transport
from semantic_pallet_planner.jev_select.candidates import CandidateProvider
from semantic_pallet_planner.jev_select.packaging_remote import PackagingRemoteSelector
from semantic_pallet_planner.jev_select.stability import monitor, balance_adapter, exact_adapter

calls = []
def forbidden(*a, **kw):
    calls.append(True)
    raise AssertionError('saved validation dispatched business operation')

for obj, name in [(episode,'decision_inputs'), (execution,'commit_physical'),
                  (transport,'credential'), (CandidateProvider,'build'),
                  (PackagingRemoteSelector,'select'), (monitor,'monitor_selected_action'),
                  (balance_adapter,'assess_candidate'), (exact_adapter,'assess_candidate')]:
    setattr(obj, name, forbidden)
source = OUT / 'constructed_evidence/test_crash_matrix_False_ACTIVA0'
assert source.is_dir()
observations = []
for kind in ('missing_tail', 'missing_head'):
    target = OUT / 'additional_negative_evidence' / kind
    assert not target.exists(), 'fresh constructed negative root required'
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('*current'))
    jm.REPO = target
    root = next((target / 'a3/slots').iterdir())
    if kind == 'missing_tail': path = sorted((root / 'stages').glob('*.json'))[-1]
    else: path = root / 'checkpoint_head.json'
    removed_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    path.unlink()
    before = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob('*') if p.is_file()}
    try:
        a3.validate_saved_execution(root)
    except (FileNotFoundError, ValueError) as exc:
        reason = type(exc).__name__ + ':' + str(exc).replace(str(REPO), 'REPO')
    else: raise AssertionError('missing durable checkpoint accepted')
    after = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for p in root.rglob('*') if p.is_file()}
    assert before == after and not calls
    observations.append({'case':kind, 'status':'REFUSED_WITH_ZERO_DISPATCH',
                         'removed_file':path.relative_to(OUT).as_posix(),
                         'removed_sha256':removed_hash, 'reason':reason,
                         'remaining_bytes_unchanged':True})
receipt = {'version':'jm1_a3_missing_tail_check_v1','scope':'copies of new A3 constructed fixtures; no historical edits',
           'business_dispatches':len(calls), 'observations':observations}
(OUT / 'additional_saved_checks.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False))
