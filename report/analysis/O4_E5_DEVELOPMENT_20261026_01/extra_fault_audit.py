"""Explicit corruption probes on independent copies of frozen E5 evidence."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
from PIL import Image
from semantic_pallet_planner.o4.common import read, write, O4Error
from semantic_pallet_planner.o4.extensions.e2.protocol import rebind, validate_response
from semantic_pallet_planner.o4.extensions.e2.visual_verify import verify as verify_image
from semantic_pallet_planner.o4.extensions.e5.episode import verify_episode

WS = Path('/home/cyw/NBU_Papper')
OUT = WS/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'
PLAN = WS/'semantic_pallet_planner/outputs/PLAN_O4_E5_090_OFFLINE_READY_20261026_06'
SOURCE = OUT/'preflight_faults_snapshot06/remote_image_commit'
ROOT = OUT/'extra_fault_copies_v3'
if ROOT.exists():
    raise RuntimeError('Refusing to overwrite previous fault evidence')
ROOT.mkdir()
config = read(PLAN/'config.snapshot.json')
task = read(PLAN/'private/input_snapshot.json')['constructs'][0]
original = read(SOURCE/'episode.json')
event_index = next(i for i, e in enumerate(original['events']) if e.get('action'))
event = original['events'][event_index]
rows = []

def reject(name, fn, evidence):
    try:
        fn()
    except O4Error as exc:
        rows.append({'purpose': name, 'passed': True, 'error_code': exc.code, 'diagnostic': str(exc), 'evidence': evidence})
    else:
        rows.append({'purpose': name, 'passed': False, 'evidence': evidence})

def image_copy(name):
    target = ROOT/name
    shutil.copytree(SOURCE, target)
    return target, copy.deepcopy(event['request']['images'][0])

root, asset = image_copy('image_bytes_changed')
path = root/asset['path']
path.write_bytes(path.read_bytes()+b'fault-injection')
reject('image_bytes_changed', lambda: verify_image(event['request'], root, asset), str(path.relative_to(WS)))

root, asset = image_copy('image_facts_changed')
path = (root/asset['path']).with_suffix('.facts.json')
facts = read(path)
facts['objects'][0]['facts']['labels']['no_top_load'] = not facts['objects'][0]['facts']['labels']['no_top_load']
write(path, facts)
reject('image_facts_changed', lambda: verify_image(event['request'], root, asset), str(path.relative_to(WS)))

root, asset = image_copy('image_geometry_changed_even_with_updated_digest')
path = root/asset['path']
with Image.open(path) as im:
    im.putpixel((20,20), (255,0,0))
    im.save(path)
asset['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
write(root/'injected_asset.json', asset)
reject('image_geometry_changed_even_with_updated_digest', lambda: verify_image(event['request'], root, asset), str(root.relative_to(WS)))

for name, field, mutate in [
    ('saved_model_response_changed', 'response', lambda e: e['response'].update(state_hash='0'*64)),
    ('saved_reference_metrics_changed', 'reference_evaluation', lambda e: e['reference_evaluation']['allowed_ids'].append('FORGED_CANDIDATE')),
    ('saved_reference_state_changed', 'reference_after', lambda e: e['reference_after']['violations'].append({'type':'FORGED'})),
]:
    result = copy.deepcopy(original)
    mutate(result['events'][event_index])
    path = ROOT/(name+'.json')
    write(path, result)
    reject(name, lambda r=result: verify_episode(r, task, config), str(path.relative_to(WS)))

for name, mutate in [
    ('stale_response_after_label_change', lambda q: q['available_objects'][0]['labels'].update(no_top_load=not q['available_objects'][0]['labels']['no_top_load'])),
    ('stale_response_after_coordinate_change', lambda q: q['container'].update(length_mm=q['container']['length_mm']+1)),
    ('stale_response_after_image_attachment_change', lambda q: q['images'][0].update(sha256='0'*64)),
]:
    req = copy.deepcopy(event['request'])
    mutate(req)
    req = rebind(req)
    path = ROOT/(name+'.json')
    write(path, {'changed_request': req, 'original_response': event['response']})
    reject(name, lambda q=req: validate_response(event['response'], q), str(path.relative_to(WS)))

write(OUT/'extra_fault_audit.json', {'status': 'PASS' if all(r['passed'] for r in rows) else 'FAIL', 'faults': rows,
      'scope': 'Explicit independent-copy probes; frozen E5 runtime; no production artifacts changed; no API requests'})
print(json.dumps({'passed': sum(r['passed'] for r in rows), 'total': len(rows), 'failed': [r for r in rows if not r['passed']]}, indent=2))
if not all(r['passed'] for r in rows):
    raise SystemExit(1)
