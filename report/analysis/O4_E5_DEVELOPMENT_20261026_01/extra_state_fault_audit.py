"""Direct stale-capacity, candidate-identity and hypothetical-clone probes."""
import copy
from pathlib import Path
from unittest.mock import patch
from semantic_pallet_planner.o4.common import read, write, digest, O4Error
from semantic_pallet_planner.o4.extensions.e2 import planning

WS = Path('/home/cyw/NBU_Papper')
OUT = WS/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'
PLAN = WS/'semantic_pallet_planner/outputs/PLAN_O4_E5_090_OFFLINE_READY_20261026_06'
SOURCE = OUT/'preflight_faults_snapshot06'
ROOT = OUT/'extra_state_fault_copies_v2'
if ROOT.exists():
    raise RuntimeError('Refusing to overwrite diagnostic evidence')
ROOT.mkdir()
config = read(PLAN/'config.snapshot.json')
data = read(PLAN/'private/input_snapshot.json')
task = data['constructs'][0]
single = read(SOURCE/'commit_crash/resumed_episode.json')
buffer = read(SOURCE/'remote_image_commit/episode.json')
rows = []

def reject(name, fn, payload, unchanged):
    path = ROOT/(name+'.json')
    write(path, payload)
    try:
        fn()
    except O4Error as exc:
        rows.append({'purpose': name, 'passed': unchanged(), 'error_code': exc.code,
                     'evidence': str(path.relative_to(WS)), 'real_state_unchanged': unchanged()})
    else:
        rows.append({'purpose': name, 'passed': False, 'evidence': str(path.relative_to(WS))})

event = next(e for e in single['events'] if e.get('action'))
changed = copy.deepcopy(event['before'])
changed['buffer_capacity'] = 3
before = digest(changed)
reject('stale_action_after_capacity_change',
       lambda: planning.commit(changed, task['regions'], event['request'], event['response'], event['candidates'], event['action']),
       {'changed_state': changed, 'original_event': event}, lambda: digest(changed) == before)

candidates = copy.deepcopy(event['candidates'])
candidates[0]['candidate_id'] += '_FORGED'
before = digest(event['before'])
reject('stale_action_after_candidate_identity_change',
       lambda: planning.commit(event['before'], task['regions'], event['request'], event['response'], candidates, event['action']),
       {'changed_candidates': candidates, 'original_event': event}, lambda: digest(event['before']) == before)

event = next(e for e in buffer['events'] if e.get('action'))
before = digest(event['before'])
original_place = planning.place
def corrupt_clone(state, candidate):
    clone = original_place(state, candidate)
    clone['placed_count'] += 1
    return clone
with patch.object(planning, 'place', corrupt_clone):
    reject('hypothetical_clone_corruption_detected',
           lambda: planning.choose(event['before'], event['request'], event['response']['policy_ast'], config, 'buffer_search'),
           {'injection': 'Increment placed_count only on the returned hypothetical clone', 'original_event': event},
           lambda: digest(event['before']) == before)
write(OUT/'extra_state_fault_audit.json', {'status': 'PASS' if all(r['passed'] for r in rows) else 'FAIL', 'faults': rows,
      'scope': 'Frozen E5/E2 execution on independent copies; injected hypothetical clone only; zero API'})
print({'passed': sum(r['passed'] for r in rows), 'total': len(rows), 'rows': rows})
if not all(r['passed'] for r in rows):
    raise SystemExit(1)
