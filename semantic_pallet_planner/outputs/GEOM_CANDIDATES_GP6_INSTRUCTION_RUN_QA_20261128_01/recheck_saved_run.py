"""Independently reconcile the GP6 archived wire bodies, responses and outcomes."""
import base64
import hashlib
import json
from collections import Counter
from math import fsum, isclose
from pathlib import Path

OUTPUT = Path('semantic_pallet_planner/outputs')
AUTH = OUTPUT / 'GP6_INSTRUCTION_PROBE_EXEC_AUTH_20261128_01'
RUN = OUTPUT / 'GP6_INSTRUCTION_PROBE_EXEC_RUN_20261125_01'
PREP = OUTPUT / 'GP6_INSTRUCTION_PROBE_PREP_20261125_01'
PLAN = OUTPUT / 'GP6_INSTRUCTION_PROBE_EXEC_SCORE_FIX_20261126_01/pending_execution/execution_plan.json'
QA = OUTPUT / 'GEOM_CANDIDATES_GP6_INSTRUCTION_SCORE_QA_20261126_01'


def read(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode())


def main():
    manifest = read(AUTH / 'manifest.json')
    for name, ref in manifest['files'].items():
        raw = Path(name).read_bytes()
        assert len(raw) == ref['bytes'] and sha(raw) == ref['sha256'], name
    plan = read(PLAN)
    plan_id = digest(plan)
    authorization = read(AUTH / 'authorization.json')
    approval = read(AUTH / 'user_authorization_record.json')
    assert all(value in approval['text'] for value in
               (plan_id, plan['model'], plan['endpoint'], '18', '单次', '不重试、不补跑'))
    assert plan_id == authorization['plan_digest'] == manifest['plan_digest']
    assert plan_id == read(QA / 'next_stage_admission.json')['plan_digest']
    assert authorization['status'] == 'AUTHORIZED'
    assert all(authorization[key] == plan[key] for key in
               ('endpoint', 'model', 'max_reservations', 'run_root'))
    assert all(sha(Path(path).read_bytes()) == expected
               for path, expected in plan['frozen_files'].items())
    started = read(RUN / 'started.json')
    receipt = read(AUTH / 'run_receipt.json')
    assert started['authorization'] == authorization
    assert started['status'] == 'CONSUMED_NO_RESUME' and not receipt['retry_performed']
    ledger = read(RUN / 'requests.json')
    stats = read(RUN / 'statistics.json')
    assert plan_id == ledger['plan_digest'] == started['plan_digest'] == receipt['plan_digest']
    assert ledger['authorization_digest'] == digest(authorization)
    assert ledger['status'] == receipt['status'] == 'FINISHED' and ledger['origin'] == 'jev'
    assert len(ledger['rows']) == len(plan['slots']) == ledger['network_attempts'] == ledger['reservations'] == 18
    assert receipt['recorded_network_attempts'] == receipt['reservations'] == 18
    assert ledger['service_cost_usd'] == receipt['service_cost_usd'] == 'UNKNOWN'

    contexts = {state: read(PREP / 'contexts' / f'{state}.json')
                for state in {slot['state'] for slot in plan['slots']}}
    distributions = {condition: Counter() for condition in ('original', 'left', 'right')}
    by_pair = {}
    tokens = Counter()
    scanned_bodies = set()
    for row, slot in zip(ledger['rows'], plan['slots']):
        assert all(row[key] == slot[key] for key in ('slot_id', 'state', 'round', 'condition'))
        assert row['status'] == 'selected' and row['request_sha256'] == slot['request']['sha256']
        filename = Path(slot['request']['path']).name
        sent = (RUN / 'sent_requests' / filename).read_bytes()
        assert sha(sent) == row['request_sha256'] and sent == (PREP / slot['request']['path']).read_bytes()
        scanned_bodies.add(filename)
        context = contexts[row['state']]
        original = context['request_body']
        body = json.loads(sent)
        question = body['questions']['next_action']
        instructions = question['instructions']
        assert instructions == slot['request']['instructions']
        question['instructions'] = original['questions']['next_action']['instructions']
        assert body == original

        transport = row['transport']
        assert transport['status'] == 'OK' and transport['http_status'] == 200
        assert transport['network_attempted'] is True
        raw = base64.b64decode(transport['raw_body_b64'], validate=True)
        answer = json.loads(raw)
        choice = answer['answers']['next_action']
        selection = row['selection']
        assert sha(raw) == transport['raw_sha256'] == selection['raw_response_digest']
        assert answer['model'] == selection['served_model'] == plan['model']
        assert selection['source'] == 'jev' and selection['status'] == 'selected'
        label = choice['choice']
        options = question['criteria']
        assert label == selection['selected_display_id'] == row['label']
        assert selection['selected_candidate_id'] == context['display_mapping'][label]['candidate_id']
        assert options[label] == row['action']
        assert choice['probabilities'] == selection['probabilities']
        assert set(choice['probabilities']) == set(options)
        half_pallet = body['state']['container']['length_mm'] / 2
        sides = {}
        for option_label, option in options.items():
            x = option['pose']['x_mm']
            half_box = option['oriented_size_mm'][0] / 2
            left = abs(x - half_box + half_pallet) <= 1e-6
            right = abs(x + half_box - half_pallet) <= 1e-6
            sides[option_label] = 'both' if left and right else 'left' if left else 'right' if right else 'other'
        assert row['side'] == sides[label]
        for side, mass in row['native_probability_mass'].items():
            assert isclose(mass, fsum(choice['probabilities'][key]
                                     for key in options if sides[key] == side), abs_tol=1e-12)
        distributions[row['condition']][row['side']] += 1
        by_pair.setdefault((row['state'], row['round']), {})[row['condition']] = row
        assert answer['usage'] == selection['usage']
        tokens.update(answer['usage'])

    assert len(scanned_bodies) == 9
    assert tokens == {'input_tokens': 131700, 'output_tokens': 5544}
    groups = {name: {side: counts[side] for side in ('left', 'right', 'other', 'both')}
              for name, counts in distributions.items()}
    for condition, counts in groups.items():
        spec = stats['groups'][condition]
        assert spec['valid'] == spec['planned'] == sum(counts.values()) == 6
        assert spec['distribution'] == counts and spec['statuses']['selected'] == 6
    expected_reversals = 0
    changed = 0
    changes_from_original = Counter()
    paired_rows = []
    for key, values in sorted(by_pair.items()):
        left, right, original = (values[name] for name in ('left', 'right', 'original'))
        reversed_ = left['side'] == 'left' and right['side'] == 'right'
        changed_ = left['label'] != right['label']
        expected_reversals += reversed_
        changed += changed_
        for name in ('left', 'right'):
            changes_from_original[name] += values[name]['label'] != original['label']
        paired_rows.append({'state': key[0], 'round': key[1], 'valid': True, 'reversed': reversed_,
                            'label_changed_without_reversal': changed_ and not reversed_})
    assert paired_rows == stats['pairs']
    assert len(paired_rows) == changed == 6 and expected_reversals == 0
    assert groups['left']['left'] == 0 and groups['right']['right'] == 2
    print(json.dumps({'status': 'PASS', 'plan_digest': plan_id, 'manifest_files': len(manifest['files']),
                      'frozen_files': len(plan['frozen_files']), 'valid_choices': 18,
                      'groups': groups, 'planned_pairs': 6, 'expected_reversals': expected_reversals,
                      'changed_labels_left_vs_right': changed, 'changes_from_original': changes_from_original,
                      'raw_tokens': tokens, 'qa_network_calls': 0}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
