"""Read-only JM1-A1 delivery verification using the standard library only.

Never imports the project, dispatches a selector, generates candidates, commits,
or calls a monitor/solver. Run from the repository root.
"""
import hashlib
import json
import re
from pathlib import Path
from math import prod

REPO = Path.cwd()
ROOT = Path(__file__).resolve().parent


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def quantities(state):
    return {'items':len(state['placed_items']),
            'volume_mm3':sum(prod(x['oriented_size_mm']) for x in state['placed_items']),
            'mass_kg':sum(x['mass_kg'] for x in state['placed_items'])}


identity = read(ROOT/'source_identity.json')
for name, expected in identity['changed_source_and_test_sha256'].items():
    assert sha(REPO/name) == expected, ('source_changed',name)
package = REPO/'semantic_pallet_planner/src/semantic_pallet_planner'
for name, expected in identity['runtime_package_source_sha256'].items():
    assert sha(package/name) == expected, ('runtime_source_changed',name)
inputs = read(ROOT/'input_evidence_index.json')
assert not inputs['missing_required_inputs']
for row in inputs['files']:
    assert sha(REPO/row['path']) == row['sha256'], ('input_changed',row['path'])
rows = []
for path in sorted((ROOT/'constructed_evidence').glob('*/branch/counts.json')):
    if path.parent.parent.is_symlink():
        continue
    counts = read(path); branch = path.parent
    binding = read(branch/'binding.json'); episode = read(branch/'episode.json')
    start = binding['start']['snapshot']; event = episode['events'][0]
    assert len(episode['events']) == 1 and episode['checkpoint']['decision'] == 1
    assert event['before'] == start['state'] and event['bundle'] == start['pool']
    assert event['context']['display_mapping'] == start['mapping']
    assert event['proposed_action'] == binding['exact_action']
    selected = event['selection']; label = selected['selected_display_id']
    assert selected['source'] == 'FORCED_FROM_FROZEN_POOL'
    assert selected['forced_action_count'] == counts['forced_actions'] == 1
    assert selected['model_call_count'] == counts['model_calls'] == counts['transport_calls'] == counts['solver_calls'] == counts['credential_reads'] == 0
    assert counts['monitor_calls'] == 1
    assert start['mapping'][label]['candidate_id'] == selected['selected_candidate_id'] == binding['forced_candidate']['candidate_id']
    assert binding['forced_candidate'] in start['pool']['selectable_candidates']
    stages = [read(p) for p in sorted((branch/'stages').glob('*.json'))]
    assert stages[0]['phase'] == 'SELECTED' and stages[0]['pending_event']['monitor'] is None
    assert stages[1]['phase'] == 'MONITORED'
    stable = counts['monitor_status'] == 'STABLE'
    assert counts['commits'] == sum(x['phase']=='COMMITTED' for x in stages) == int(stable)
    before = quantities(start['state']); after = quantities(episode['final_state'])
    delta = {k:after[k]-before[k] for k in before}
    if stable:
        assert delta['items'] == 1 and delta['volume_mm3'] == prod(binding['forced_candidate']['oriented_size_mm'])
        item_id = binding['forced_candidate']['pick_item_id']
        assert delta['mass_kg'] == next(x['item']['mass_kg'] for x in start['buffer'] if x['item']['item_id']==item_id)
        assert len(episode['final_state']['pending_items']) == len(start['buffer'])-1
        assert episode['checkpoint']['reason'] == 'JM_CONTINUATION_NOT_IMPLEMENTED'
    else:
        assert delta == {'items':0,'volume_mm3':0,'mass_kg':0}
        assert episode['final_state'] == start['state'] and event['action'] is None
    rows.append({'intervention':counts['intervention'],'monitor_status':counts['monitor_status'],'commits':counts['commits'],'increment':delta})
assert len(rows) == 12, len(rows)
assert len({(r['intervention'],r['monitor_status']) for r in rows}) == 12
report = REPO/'docs/03_阶段产出分析/Jev/Jev_JM1-A1分叉绑定状态复制与强制首步验收_20261111_01.md'
for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):
    assert (report.parent/target).resolve().exists(), ('missing_link',target)
manifest = read(ROOT/'delivery_manifest.json')
for name, expected in manifest['files_sha256'].items():
    assert sha(ROOT/name) == expected, ('delivery_changed',name)
for name, expected in manifest['repository_files_sha256'].items():
    assert sha(REPO/name) == expected, ('repository_delivery_changed',name)
print(json.dumps({'status':'PASS','scope':'saved bytes/accounting/links only; no project imports or execution',
                  'input_files':len(inputs['files']),'first_step_records':rows,
                  'delivery_files':len(manifest['files_sha256'])},ensure_ascii=False))
