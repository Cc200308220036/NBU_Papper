"""Post-hoc display audit of frozen memory hits. No planner/model imports.

Outcomes are whole-job observations, never credit assigned to an individual hit.
Mismatch flags describe evidence scope, not a newly validated retrieval policy.
"""
import hashlib
import json
from collections import Counter


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def normalized_pool(event):
    criteria = (event.get('request') or {}).get('questions', {}).get('next_action', {}).get('criteria', {}) or event.get('prepared_criteria', {})
    return sorted(({'item_id': c['item_id'], 'pose': criteria[c['label']]['pose'],
                    'size': criteria[c['label']]['oriented_size_mm']} for c in event['candidates']), key=canonical)


def selected_action(event):
    label = (event.get('selection') or {}).get('selected_display_id')
    return next(({'label': label, **action} for c, action in zip(event['candidates'], actions_in_display_order(event))
                 if c['label'] == label), None)


def actions_in_display_order(event):
    criteria = (event.get('request') or {}).get('questions', {}).get('next_action', {}).get('criteria', {}) or event.get('prepared_criteria', {})
    return [{'item_id': c['item_id'], 'pose': criteria[c['label']]['pose'],
             'size': criteria[c['label']]['oriented_size_mm']} for c in event['candidates']]


def without_label(action):
    return {k: v for k, v in action.items() if k != 'label'} if action else None


def dimensions_summary(condition):
    boxes = condition.get('observed_buffer', [])
    return {'placed_count': condition.get('placed_count'), 'buffer_count': len(boxes),
            'buffer_capacity': condition.get('buffer_capacity'),
            'stackable_count': sum(bool(b['stackable']) for b in boxes),
            'boxes': boxes}


def job_result(job):
    return {'job_id': job['id'], 'category': job['status']['category'],
            'algorithm': job['source']['algorithm'], **job['metrics']['loading'],
            'actual_height_mm': job['metrics']['actual_height_mm'],
            'envelope_utilization': job['metrics']['envelope_utilization']}


def build_audit(jobs, snapshots, pairs):
    library = {}
    for mode, snapshot in snapshots.items():
        for i, entry in enumerate(snapshot['entries'], 1):
            library[canonical(entry['public_fragment'])] = {
                'ref': f'{mode}-{i}', 'mode': mode, 'entry': entry,
                'comparison_id': entry['provenance']['comparison_id']}
    records = []
    for job in jobs.values():
        if job['method'] not in ('jev_with_trajectory', 'jev_with_contrast_experience', 'jev_with_unrelated_E_control'):
            continue
        control = job['method'] == 'jev_with_unrelated_E_control'
        reference = next(j for j in jobs.values() if j['task_id'] == job['task_id'] and j['method'] == 'jev_no_memory')
        by_decision = {e['decision_id'].split('_')[-1]: (i, e) for i, e in enumerate(reference['events']) if e['decision_id']}
        same_version = job['source']['algorithm'] == reference['source']['algorithm'] and job['source']['source_manifest_digest'] == reference['source']['source_manifest_digest']
        pair = next((p for p in pairs if p['task_id'] == job['task_id'] and p['comparison'] == ('T/none' if job['method'] == 'jev_with_trajectory' else 'E/none')), None) if not control else None
        first_difference = None
        for step, event in enumerate(job['events']):
            fragments = (event.get('request') or {}).get('state', {}).get('memories', []) or event.get('prepared_memory_entries', [])
            if not fragments:
                continue
            receipt = event.get('retrieval') or {}
            raw = receipt.get('reference_receipt', receipt).get('raw_retrieval')
            assert raw is not None, (job['id'], event['decision_id'], 'missing retrieval')
            comparison = by_decision.get(event['decision_id'].split('_')[-1])
            reference_step, ref_event = comparison if comparison else (None, None)
            same_state = bool(ref_event and event['before'] == ref_event['before'])
            same_pool = bool(ref_event and normalized_pool(event) == normalized_pool(ref_event))
            selected = selected_action(event)
            ref_selected = selected_action(ref_event) if ref_event else None
            comparable = same_version and same_state and same_pool and selected is not None and ref_selected is not None
            changed = comparable and without_label(selected) != without_label(ref_selected)
            if changed and first_difference is None:
                first_difference = event['decision_id']
            selection = event.get('selection') or {}
            sent = selection.get('source') == 'jev' and bool(selection.get('probabilities'))
            delivery = ('SINGLETON_NOT_SENT' if selection.get('source') == 'singleton' else
                        'UNKNOWN_SEND' if event['request_state'] == 'UNKNOWN_SEND' else
                        'CONFIRMED_RESPONSE' if sent else 'PREPARED_NOT_CONFIRMED')
            matched_fragments = raw['view']['entries'] if control else fragments
            for fragment in matched_fragments:
                match = library.get(canonical(fragment))
                assert match, (job['id'], event['decision_id'], 'unregistered fragment')
                entry = match['entry']
                candidate = next(c for c in raw['candidates'] if c['public_digest'] == entry['public_digest'])
                assert candidate['qualified'] and not candidate['excluded']
                condition = fragment.get('condition', fragment.get('observable_conditions'))
                history = dimensions_summary(condition)
                before = event['before']
                current = {'placed_count': before['placed_count'], 'buffer_capacity': before['buffer_capacity'],
                           'observed_buffer': [p['item'] for p in before['pending_items']]}
                current = dimensions_summary(current)
                query = raw['query']['features']
                historical_query = next(c['query']['features'] for c in job['config']['memory_index'] if c['public_digest'] == entry['public_digest'])
                deltas = [{'feature': k, 'current': query[k], 'historical': historical_query[k],
                           'absolute_difference': abs(query[k] - historical_query[k])} for k in query]
                expected_score = 1 / (1 + sum(d['absolute_difference'] for d in deltas) / len(deltas))
                assert abs(expected_score - candidate['score']) < 1e-12
                phase_mismatch = current['placed_count'] != history['placed_count']
                stack_mismatch = query['stackable_fraction'] != historical_query['stackable_fraction']
                ratio_warnings = []
                # Explicitly post-hoc descriptive threshold; never fed back into retrieval.
                for k in ('mean_length', 'mean_width', 'mean_height', 'mean_mass', 'mean_capacity'):
                    a, b = query[k], historical_query[k]
                    ratio = a / b if b else None
                    if ratio is None or ratio < 2 / 3 or ratio > 1.5:
                        ratio_warnings.append({'feature': k, 'current_over_historical': ratio})
                observations = []
                current_intervention = ('different_box' if selected['item_id'] != ref_selected['item_id'] else 'same_box_different_pose') if changed else None
                historical_relation = (fragment.get('historical_interventions') or fragment.get('historical_attribute_geometry_contrast'))['relationship']
                family_mismatch = bool(changed and historical_relation == 'different boxes' and current_intervention != 'different_box')
                if phase_mismatch:
                    observations.append(f"历史为已放{history['placed_count']}箱的开局，当前已放{current['placed_count']}箱；已有支撑与空隙结构不在该历史案例覆盖内。")
                if stack_mismatch:
                    observations.append('可堆叠箱比例不同；不能仅按平均尺寸类比选箱条件。')
                if ratio_warnings:
                    observations.append('部分归一化均值相差超过1.5倍，或低于历史值的2/3；差异项及原值在下表。')
                if family_mismatch:
                    observations.append('历史证据比较的是换箱选择；本步与无经验的差异仅为同箱换位置/朝向。不能用历史换箱收益直接解释当前的位置变化。')
                observations.append('当前检索只比较9个汇总特征，没有验证逐箱对应、空间拓扑、承载分布及原/替代动作是否具备相同取舍。')
                verdict = 'PHASE_MISMATCH' if phase_mismatch else 'ACTION_FAMILY_MISMATCH' if family_mismatch else 'ATTRIBUTE_MISMATCH' if stack_mismatch or ratio_warnings else 'SURFACE_SIMILAR_TRANSFER_UNVERIFIED'
                assessment = ('仅为placebo参考检索，不能评为真实经验的使用效果。' if control else
                              '整单配对无效，无法用结果判断本条经验的效用。' if not pair or not pair['evaluation']['comparison_valid'] else
                              '整单结果改善，但没有隔离本次命中的贡献；它只构成有限的正向线索。' if pair['evaluation']['label_v2'] == 'improved' else
                              '整单结果退化，本次命中未获得正向整单收益支持；仍不能据此认定该条经验导致退化。' if pair['evaluation']['label_v2'] == 'degraded' else
                              '整单结果持平，未观察到净收益；不证明经验被忽略。')
                record = {'job_id': job['id'], 'task_id': job['task_id'], 'method': job['method'],
                          'step': step, 'decision_id': event['decision_id'], 'mode': 'CONTROL_REFERENCE' if control else match['mode'],
                          'entry_ref': match['ref'], 'comparison_id': match['comparison_id'],
                          'public_digest': entry['public_digest'], 'case_digest': entry['case_digest'],
                          'score': candidate['score'], 'minimum_score': raw['rule']['minimum_score'],
                          'delivery': delivery, 'evidence': event['evidence'],
                          'actual_fragment_sha256': fingerprint(fragments[0]),
                          'fragment_role': 'reference_E_only_actual_text_is_placebo' if control else 'prepared_view_only_not_sent' if delivery == 'SINGLETON_NOT_SENT' else 'actual_request_fragment',
                          'similarity': {'status': verdict, 'historical': history, 'current': current,
                                         'feature_differences': deltas, 'ratio_warnings': ratio_warnings,
                                         'historical_intervention': historical_relation,
                                         'current_intervention': current_intervention,
                                         'action_family_mismatch': family_mismatch,
                                         'observations': observations, 'suitability': 'NOT_ESTABLISHED'},
                          'choice': {'status': 'DIFFERENT_ACTION_SAME_STATE_POOL' if changed else 'SAME_ACTION_SAME_STATE_POOL' if comparable else 'NOT_COMPARABLE',
                                     'same_version': same_version, 'same_state': same_state, 'same_pool': same_pool,
                                     'reference_job': reference['id'], 'reference_step': reference_step,
                                     'reference_decision': ref_event['decision_id'] if ref_event else None,
                                     'selected': selected, 'reference_selected': ref_selected,
                                     'intervention': current_intervention,
                                     'state_sha256': fingerprint(event['before']), 'pool_sha256': fingerprint(normalized_pool(event)),
                                     'reference_state_sha256': fingerprint(ref_event['before']) if ref_event else None,
                                     'reference_pool_sha256': fingerprint(normalized_pool(ref_event)) if ref_event else None,
                                     'first_difference_in_job': first_difference,
                                     'causal_effect': 'NOT_ESTABLISHED'},
                          'outcome': {'scope': 'WHOLE_JOB_NOT_INDIVIDUAL_HIT', 'actual': job_result(job),
                                      'reference': job_result(reference), 'pair': pair,
                                      'hit_benefit': 'NOT_ESTABLISHED'},
                          'case_assessment': assessment,
                          'assessment_type': 'POST_HOC_DESCRIPTIVE_RETRIEVAL_AUDIT'}
                records.append(record)
    counts = {}
    for mode in ('T', 'E', 'CONTROL_REFERENCE'):
        hits = [r for r in records if r['mode'] == mode]
        counts[mode] = {'nonempty_views': len(hits), 'confirmed_response': sum(r['delivery'] == 'CONFIRMED_RESPONSE' for r in hits),
                        'singleton_not_sent': sum(r['delivery'] == 'SINGLETON_NOT_SENT' for r in hits),
                        'unknown_send': sum(r['delivery'] == 'UNKNOWN_SEND' for r in hits),
                        'similarity': dict(Counter(r['similarity']['status'] for r in hits)),
                        'same_state_action_differences': sum(r['choice']['status'] == 'DIFFERENT_ACTION_SAME_STATE_POOL' for r in hits)}
    assert counts['T']['nonempty_views'] == 106 and counts['T']['confirmed_response'] == 105, counts
    assert counts['E']['confirmed_response'] == 100
    assert counts['CONTROL_REFERENCE']['unknown_send'] == 1
    return {'version': 'jn4_memory_hit_review_v1', 'assessment_date': '2026-11-09',
            'scope': 'All saved T/E nonempty request views; placebo reference separate; no new execution',
            'policy': {'type': 'POST_HOC_DESCRIPTIVE_RETRIEVAL_AUDIT',
                       'attribute_ratio_warning': 'current/historical normalized mean outside [2/3, 1.5]; descriptive, not validated cutoff',
                       'phase_warning': 'historical placed_count differs from current placed_count',
                       'suitability': 'Similarity/success do not establish transfer; failure does not prove misretrieval.',
                       'outcome': 'Frozen whole-job paired evaluation only; no attribution to a hit; no retuning or new filtering',
                       'causality': 'Action differences observed without repeated matched-state interventions; causal effect NOT_ESTABLISHED'},
            'counts': counts, 'records': records}
