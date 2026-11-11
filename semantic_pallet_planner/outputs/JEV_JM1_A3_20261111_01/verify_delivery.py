"""Read-only stdlib audit. No business imports, replay, credentials or network."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def read(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()).hexdigest()
def sealed(value):
    assert value['record_digest'] == digest({k:v for k,v in value.items() if k != 'record_digest'})
def local(path):
    p = (REPO / path).resolve()
    assert p.is_relative_to(REPO)
    return p


def main():
    manifest = read(ROOT / 'delivery_manifest.json')
    for row in manifest['files']:
        p = local(row['path'])
        assert p.stat().st_size == row['bytes'] and sha(p) == row['sha256'], row['path']
    inputs = read(ROOT / 'input_evidence_index.json')['inputs']
    for row in inputs:
        assert sha(local(row['path'])) == row['sha256'], row['path']
    source = read(ROOT / 'source_identity.json')
    base = REPO / 'semantic_pallet_planner/src/semantic_pallet_planner'
    for relative, expected in source['source_manifest'].items():
        assert sha(base / relative) == expected, relative
    counts = {}
    for name in ('constructed', 'legacy_constructed', 'public_regression'):
        tree = ET.parse(ROOT / (name + '_junit.xml'))
        cases = tree.findall('.//testcase')
        assert cases and not tree.findall('.//failure') and not tree.findall('.//error')
        assert not tree.findall('.//skipped')
        counts[name] = len(cases)
    assert counts == read(ROOT / 'acceptance_receipt.json')['test_counts']
    negatives = read(ROOT / 'additional_saved_checks.json')
    assert negatives['business_dispatches'] == 0 and len(negatives['observations']) == 2
    assert all(r['status'] == 'REFUSED_WITH_ZERO_DISPATCH' and r['remaining_bytes_unchanged'] for r in negatives['observations'])
    matrix = read(ROOT / 'recovery_matrix.json')
    assert len(matrix['observations']) == 26
    assert {r['point'] for r in matrix['observations']} == {
        'ACTIVATED','CONTEXT_SAVED','RESERVATION_SAVED','INTENT','SENDING','RESPONSE_SAVED',
        'SELECTION_SAVED','DECISION_READY','SELECTED','MONITORED','COMMITTED','READY','TERMINATED'}
    valid = read(ROOT / 'constructed_evidence_index.json')['valid_recovery_runs']
    for relative in valid:
        root = local(relative)
        activation = read(root / 'activation.json'); sealed(activation)
        ex = activation['execution']; sealed(ex)
        previous = digest(activation)
        paths = sorted((root / 'stages').glob('*.json'))
        for i,p in enumerate(paths,1):
            assert p.name == f'{i:06d}.json'
            row = read(p); sealed(row); sealed(row['checkpoint'])
            assert row['sequence'] == i and row['previous_digest'] == previous
            assert row['execution_digest'] == digest(ex)
            previous = digest(row)
        assert read(root / 'checkpoint_head.json') == {'sequence':len(paths),'digest':previous}
        cp = read(paths[-1])['checkpoint']
        episode = read(root / 'episode.json')
        assert episode['checkpoint'] == cp and episode['events'] == cp['events']
        assert episode['final_state'] == cp['state']
        ledger = read(root / 'ledger/requests.json'); sealed(ledger)
        assert ledger['max_sends'] == ex['max_sends']
        rows = ledger['requests']
        assert sum(r['send_started'] for r in rows) <= ex['max_sends']
        for row in rows:
            context = read(root / 'ledger/contexts' / (row['decision_id'] + '.json'))
            reservation = read(root / 'ledger/reservations' / (row['decision_id'] + '.json'))
            assert context['request_body']['state']['memories'] == []
            assert row['context_digest'] == digest(context)
            assert row['body_digest'] == digest(context['request_body']) == reservation['body_digest']
            assert row['mapping_digest'] == digest(context['display_mapping']) == reservation['mapping_digest']
            assert reservation['repeat_slot'] == ex['repeat_slot']
            assert reservation['allocation_id'] == ex['allocation_id']
            if row['transport'] is not None: assert row['transport_digest'] == digest(row['transport'])
            if row['selection'] is not None: assert row['selection_digest'] == digest(row['selection'])
        saved_counts = read(root / 'counts.json')
        selections = [e['selection'] for e in cp['events'] if e.get('selection')]
        assert saved_counts['forced_actions'] == sum(s['source']=='FORCED_FROM_FROZEN_POOL' for s in selections) == 1
        assert saved_counts['commits'] == sum(e['event']=='PLACE' for e in cp['events'])
        assert saved_counts['constructed_requests'] == sum(r['send_started'] for r in rows)
        observation = read(root / 'recovery_observation.json')
        assert observation['repeat_no_calls'] is True
        expected = [0,1,1] if observation['point']=='SENDING' else [3,4,4]
        assert observation['after_calls'] == expected
    print(json.dumps({'status':'PASS_SAVED_FACTS_ONLY','delivery_files':len(manifest['files']),
                      'inputs':len(inputs),'source_files':len(source['source_manifest']),
                      'tests':counts,'recovery_runs':len(valid)}, ensure_ascii=False))


if __name__ == '__main__': main()
