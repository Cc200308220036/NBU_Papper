"""Export complete saved training traces and exact T/E input boundaries.

No production imports, replay, solver, credential loading or model requests.
Run from repository root: python3 report/visualization/.../build_origins.py --repo .
"""
import argparse
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def build(repo, output):
    sources = {}

    def read(relative):
        path = repo / relative
        raw = path.read_bytes()
        sources[str(relative)] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    def ref(relative, pointer):
        return {'path': str(relative), 'sha256': sources[str(relative)], 'pointer': pointer}

    def state_view(state):
        def box(b):
            return {k: b[k] for k in ['item_id', 'dimensions_mm', 'mass_kg', 'stackable', 'top_load_limit_kg_synthetic', 'pose', 'oriented_size_mm'] if k in b}
        return {'container': state['container'], 'placed_count': state['placed_count'],
                'arrival_count': state['arrival_count'], 'end_of_stream': state['end_of_stream'],
                'placed_items': [box(b) for b in state['placed_items']],
                'pending_items': [{'item': box(p['item'])} for p in state['pending_items']]}

    def trace(cp_path, receipt_path=None, metric_path=None, title='', policy=''):
        cp = read(cp_path)
        rec = read(receipt_path) if receipt_path else None
        metric = rec['metrics'] if rec else read(metric_path)
        events = cp['events']
        first_state = events[0]['before']
        frames = [{'event': 'SAVED_START', 'decision_id': None, 'state': state_view(first_state),
                   'source': ref(cp_path, '/events/0/before'), 'new_item_ids': []}]
        first_placement = True
        for i, e in enumerate(events):
            before_ids = {b['item_id'] for b in e['before']['placed_items']}
            new_ids = [b['item_id'] for b in e['after']['placed_items'] if b['item_id'] not in before_ids]
            candidate = None
            sel = e.get('selection') or {}
            if sel.get('selected_candidate_id') and e.get('bundle'):
                candidate = next((c for c in e['bundle']['physical_candidates'] if c['candidate_id'] == sel['selected_candidate_id']), None)
            if e['event'] == 'PLACE':
                assert len(new_ids) == 1
            else:
                assert not new_ids
            frames.append({'event': e['event'], 'decision_id': e.get('decision_id'),
                           'reason': e.get('reason'), 'state': state_view(e['after']),
                           'new_item_ids': new_ids, 'selection_label': sel.get('selected_display_id'),
                           'selection_source': sel.get('source'),
                           'selected_action': {k: candidate[k] for k in ['pick_item_id', 'pose', 'oriented_size_mm']} if candidate else None,
                           'monitor': {k: (e.get('monitor') or {}).get('result', {}).get(k) for k in ['status', 'reason_code']},
                           'is_first_placement': e['event'] == 'PLACE' and first_placement,
                           'source': ref(cp_path, f'/events/{i}/after')})
            if e['event'] == 'PLACE':
                first_placement = False
        assert frames[-1]['state'] == state_view(cp['state'])
        loading = metric['loading']
        assert sum(e['event'] == 'PLACE' for e in events) == loading['placed_items'] == cp['state']['placed_count']
        assert len(frames) == len(events) + 1
        return {'title': title, 'policy': policy, 'job_id': cp['job_id'], 'reason': cp['reason'],
                'frames': frames, 'event_count': len(events), 'final_state': state_view(cp['state']),
                'metrics': {'loading': loading, 'actual_height_mm': metric['actual_height_mm'],
                            'envelope_utilization': metric['envelope_utilization']},
                'first': rec['first'] if rec else None,
                'source': ref(cp_path, ''), 'receipt_source': ref(receipt_path, '') if receipt_path else None}

    outputs = Path('semantic_pallet_planner/outputs')
    t_path = outputs / 'JEV_JN3_20261104_01/trajectory_snapshot.json'
    e_path = outputs / 'JEV_JN3_20261104_02/contrast_snapshot.json'
    t = read(t_path)
    e = read(e_path)
    audit_path = Path('report/visualization/Jev_JN4_六方法决策回看_20261107/memory_hit_audit.json')
    audit = read(audit_path)
    index_path = Path('report/visualization/Jev_JN4_六方法决策回看_20261107/web/index-data.js')
    index_bytes = (repo / index_path).read_bytes()
    sources[str(index_path)] = hashlib.sha256(index_bytes).hexdigest()
    index = json.loads(index_bytes.decode().split('=', 1)[1].rstrip(';\n'))
    rows = {j['id']: j for j in index['jobs']}
    cases = []
    for ti, case in enumerate(t['cases']):
        provenance = case['provenance']
        cid = provenance['comparison_id']
        ei, ecase = next((i, c) for i, c in enumerate(e['cards']) if c['provenance']['comparison_id'] == cid)
        saved_input = read(Path(provenance['snapshot_path']))['value']
        snapshot = saved_input['snapshot']
        parent_job = Path(snapshot['parent_identity']['parent']) / 'run/jobs' / snapshot['parent_job_id']
        parent = trace(parent_job / 'checkpoint.json', metric_path=parent_job / 'metrics.json',
                       title='当时真实Jev的原始轨迹', policy='每步继续由无经验Jev选择；仅供理解来源，不作为几何分支的收益参照')
        branches = {}
        for role, title in [('reference', '原动作＋几何后续'), ('alternative', '替代动作＋相同几何后续')]:
            receipt = Path(provenance['receipts'][role]['path'])
            branches[role] = trace(receipt.parent / 'checkpoint.json', receipt_path=receipt,
                                   title=title, policy='第一步固定为保存动作；后续每步选当前几何分最高候选，再经监测与提交')
        assert branches['reference']['frames'][0]['state'] == branches['alternative']['frames'][0]['state']
        # The first committed actions are exactly the two archived intervention actions.
        for branch in branches.values():
            frame = next(f for f in branch['frames'] if f['event'] == 'PLACE')
            assert frame['selected_action'] == {k: branch['first']['candidate'][k] for k in ['pick_item_id', 'pose', 'oriented_size_mm']}
        assert next(f['selected_action'] for f in parent['frames'] if f['event'] == 'PLACE') == next(f['selected_action'] for f in branches['reference']['frames'] if f['event'] == 'PLACE')
        fragment = case['public_fragment']
        for role in ['reference', 'alternative']:
            actual = branches[role]['metrics']
            observed = fragment['historical_result'][role]
            for k in ['placed_items', 'placed_volume_ratio', 'placed_mass_kg']:
                assert abs(actual['loading'][k] - observed[k]) < 1e-10
            assert actual['actual_height_mm'] == observed['actual_height_mm']
        examples = {}
        for mode, ordinal, public in [('T', ti, fragment), ('E', ei, ecase['public_fragment'])]:
            entry_ref = f'{mode}-{ordinal + 1}'
            hits = [h for h in audit['records'] if h['mode'] == mode and h['entry_ref'] == entry_ref and h['delivery'] == 'CONFIRMED_RESPONSE']
            # Deterministic example selection, independent of final win/loss.
            preferred = sorted(hits, key=lambda h: (h['choice']['status'] != 'DIFFERENT_ACTION_SAME_STATE_POOL',
                                                    int(h['task_id'][-2:]) < 3, h['task_id'] != 'SYN_COMBO_03', h['job_id'], h['step']))[0]
            cp_path = Path(rows[preferred['job_id']]['run']) / 'jobs' / preferred['job_id'] / 'checkpoint.json'
            cp = read(cp_path)
            i, decision = next((i, x) for i, x in enumerate(cp['events']) if x.get('decision_id') == preferred['decision_id'])
            request = decision['context']['request_body']
            assert request['state']['memories'] == [public]
            examples[mode] = {'job_id': preferred['job_id'], 'step': preferred['step'],
                              'decision_id': preferred['decision_id'], 'task_id': preferred['task_id'],
                              'entry_ref': entry_ref, 'score': preferred['score'], 'request': request,
                              'before': state_view(decision['before']), 'choice': preferred['choice'],
                              'outcome': preferred['outcome'], 'request_source': ref(cp_path, f'/events/{i}/context/request_body'),
                              'memory_source': ref(cp_path, f'/events/{i}/context/request_body/state/memories/0'),
                              'actual_memory_equal_frozen_fragment': True}
        cases.append({'id': cid, 'title': f'案例{ti+1}：先放哪个箱子，会改变后续装入量',
                      'T_ref': f'T-{ti+1}', 'E_ref': f'E-{ei+1}', 'parent': parent,
                      'branches': branches, 'T': fragment, 'E': ecase['public_fragment'],
                      'T_source': ref(t_path, f'/cases/{ti}/public_fragment'),
                      'E_source': ref(e_path, f'/cards/{ei}/public_fragment'),
                      'snapshot_source': ref(Path(provenance['snapshot_path']), '/value/snapshot'),
                      'examples': examples})
    data = {'version': 'jn4_experience_origins_v1', 'date': '2026-11-09', 'cases': cases,
            'boundary': {'complete_trajectories_sent_to_model': False, 'T_and_E_sent_together': False,
                         'T_payload': 'One frozen public_fragment only', 'E_payload': 'One frozen public_fragment only',
                         'sample_selection': 'Prefer same-state/pool differences, main tasks, task03, then job/step; no outcome criterion'},
            'source_files': sources, 'new_model_calls': 0, 'new_solver_calls': 0, 'new_episode_runs': 0}
    output.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    (output / 'web').mkdir(exist_ok=True)
    (output / 'web/origins-data.js').write_text('window.JN4_ORIGINS=' + text + ';\n')
    receipt = {'version': data['version'], 'sources': sources, 'cases': [{
        'id': c['id'], 'parent_events': c['parent']['event_count'],
        'reference_events': c['branches']['reference']['event_count'],
        'alternative_events': c['branches']['alternative']['event_count'],
        'T_request': c['examples']['T']['decision_id'], 'E_request': c['examples']['E']['decision_id'],
        'exact_fragments_verified': True} for c in cases],
        'checks': ['all saved branch events exported', 'branch endpoints match receipts and T outcomes',
                   'first exact actions match branch receipts', 'same initial branch state', 'actual T/E requests contain exact frozen fragments'],
        'model_calls': 0, 'solver_calls': 0, 'episode_runs': 0}
    (output / 'origin_source_manifest.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'sources'}, ensure_ascii=False))
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    build(args.repo.resolve(), args.output.resolve())
