"""Verify the display audit against immutable original checkpoints and receipts.
Run from the repository root. Standard library only; no simulation or transport.
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text())


def canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(canon(value).encode()).hexdigest()


def js_data(path):
    text = path.read_text()
    return json.loads(text.split('=', 1)[1].rstrip(';\n'))


def pool(event):
    return sorted(({'item_id': c['pick_item_id'], 'pose': c['pose'], 'size': c['oriented_size_mm']}
                   for c in event['bundle']['selectable_candidates']), key=canon)


def selection(event):
    sid = (event.get('selection') or {}).get('selected_candidate_id')
    c = next((c for c in (event.get('bundle') or {}).get('selectable_candidates', []) if c['candidate_id'] == sid), None)
    return {'item_id': c['pick_item_id'], 'pose': c['pose'], 'size': c['oriented_size_mm']} if c else None


audit = read(BASE / 'memory_hit_audit.json')
index = js_data(BASE / 'web/index-data.js')
assert index['memory_hits'] == audit
sources = read(BASE / 'source_manifest.json')
for path, digest in sources.items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
jobs = {j['id']: js_data(BASE / f"web/data/{j['id']}.js") for j in index['jobs']}
checkpoints = {}


def original(job, decision):
    path = Path(jobs[job]['source']['run']) / 'jobs' / job / 'checkpoint.json'
    if path not in checkpoints:
        checkpoints[path] = read(path)
    return next(e for e in checkpoints[path]['events'] if e.get('decision_id') == decision)


assert len(audit['records']) == 296
unique = set()
for r in audit['records']:
    key = (r['job_id'], r['decision_id'])
    assert key not in unique
    unique.add(key)
    job = jobs[r['job_id']]
    e = original(*key)
    ex = job['events'][r['step']]
    assert ex['decision_id'] == r['decision_id']
    raw = e['context']['retrieval_receipt']
    raw = raw.get('reference_receipt', raw)['raw_retrieval']
    mode, ordinal = r['entry_ref'].split('-')
    entry = index['snapshots'][mode]['entries'][int(ordinal) - 1]
    fragment = entry['public_fragment']
    sent_fragments = (e['context'].get('request_body') or {}).get('state', {}).get('memories', [])
    fragments = sent_fragments or (e['context'].get('memory_view') or {}).get('entries', [])
    if r['mode'] == 'CONTROL_REFERENCE':
        assert fragment in raw['view']['entries'] and fragment not in fragments
    else:
        assert fragment in fragments
    assert r['actual_fragment_sha256'] == sha(fragments[0])
    q = raw['query']['features']
    historical = next(c['query']['features'] for c in job['config']['memory_index'] if c['public_digest'] == r['public_digest'])
    score = 1 / (1 + sum(abs(q[k] - historical[k]) for k in q) / len(q))
    assert abs(score - r['score']) < 1e-12
    assert r['similarity']['current']['placed_count'] == e['before']['placed_count']
    assert r['similarity']['historical']['placed_count'] == 0
    assert (r['similarity']['status'] == 'PHASE_MISMATCH') == (e['before']['placed_count'] != 0)
    assert r['choice']['state_sha256'] == sha(e['before'])
    assert r['choice']['pool_sha256'] == sha(pool(e))
    chosen = selection(e)
    assert {k: v for k, v in (r['choice']['selected'] or {}).items() if k != 'label'} == (chosen or {})
    if r['choice']['reference_decision']:
        re = original(r['choice']['reference_job'], r['choice']['reference_decision'])
        assert r['choice']['same_state'] == (e['before'] == re['before'])
        assert r['choice']['same_pool'] == (pool(e) == pool(re))
        if r['choice']['status'] != 'NOT_COMPARABLE':
            assert r['choice']['same_state'] and r['choice']['same_pool'] and r['choice']['same_version']
            assert (r['choice']['status'] == 'DIFFERENT_ACTION_SAME_STATE_POOL') == (chosen != selection(re))
    if r['delivery'] == 'SINGLETON_NOT_SENT':
        assert not sent_fragments and e['selection']['source'] == 'singleton'
    if r['delivery'] == 'CONFIRMED_RESPONSE':
        assert sent_fragments and e['selection']['source'] == 'jev' and e['selection']['probabilities']
    for result in [r['outcome']['actual'], r['outcome']['reference']]:
        metric = jobs[result['job_id']]['metrics']
        assert result['placed_items'] == metric['loading']['placed_items']
        assert result['placed_volume_ratio'] == metric['loading']['placed_volume_ratio']
        assert result['actual_height_mm'] == metric['actual_height_mm']
    assert r['outcome']['hit_benefit'] == r['choice']['causal_effect'] == 'NOT_ESTABLISHED'
    assert r['similarity']['suitability'] == 'NOT_ESTABLISHED'
assert audit['counts']['T']['same_state_action_differences'] == 6
assert audit['counts']['E']['same_state_action_differences'] == 6
assert audit['counts']['T']['singleton_not_sent'] == 1
assert audit['counts']['CONTROL_REFERENCE']['unknown_send'] == 1
r = next(r for r in audit['records'] if r['decision_id'] == 'J0015_D0000')
assert r['similarity']['status'] == 'ACTION_FAMILY_MISMATCH'
assert r['outcome']['pair']['evaluation']['label_v2'] == 'improved'
r = next(r for r in audit['records'] if r['decision_id'] == 'J0016_D0004')
assert r['similarity']['status'] == 'PHASE_MISMATCH'
assert r['outcome']['pair']['evaluation']['label_v2'] == 'degraded'
receipt = {'status': 'PASS', 'date': '2026-11-09', 'original_source_hashes': len(sources),
           'hit_records_checked_against_original_checkpoints': len(audit['records']),
           'counts': audit['counts'],
           'checks': ['actual/prepared/placebo content verified', 'nine-feature scores recomputed',
                      'original states/pools/actions verified', 'whole-job metrics retained',
                      'singleton and unknown send distinguished', 'causal/suitability limits retained'],
           'scope': 'saved-record verification only; no model/solver/retrieval dispatch/order replay'}
(BASE / 'qa/memory_hit_data_checks.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(receipt, ensure_ascii=False))
