"""Cross-check 12 critical V2 cases from public instructions and physical states."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from ..evaluation.attribute_metrics_v2 import reconstruct, public_relations
from ..evaluation.policy_v2 import evaluate
from ..evaluation.replay_values_v2 import replay_values_equal
from ..selectors.instruction_parser_v2 import parse_instruction
from ..vlm.pilot_protocol_v2 import parse_choice as parse_old
from .attribute_pilot_v2 import read_json, write_json, sha


def crosscheck(root: Path):
    root=root.resolve();m=read_json(root/'manifest.json')
    parent=Path(m['parent_v2_directory'])
    dataset={d['public_request']['request_id']:d for d in read_json(parent/'data/pilot_dataset.private.json')}
    oldrows={r['request_id']:r for r in read_json(parent/'metrics/per_decision.json') if r['method']=='flash_direct_text'}
    critical=[x for x in read_json(root/'audit/old_60_classification.json') if
              'protocol_error' in x['tags'] or 'avoidable_hard_wrong_selection' in x['tags']]
    results=[]
    for case in critical:
        rid=case['request_id'];item=dataset[rid];req=item['public_request'];row=oldrows[rid]
        failures=[]
        public_policy=parse_instruction(req['instruction_text'])
        if public_policy!=item['hidden_policy']:failures.append('public_instruction_policy_disagrees_with_private_annotation')
        state={'placed_items':reconstruct(req['placed_items']),'available_items':req['available_items'],
               'container':req['container']}
        evaluations=[]
        for i,candidate in enumerate(item['physical_candidates']):
            ev=evaluate(state,candidate,public_policy,req['container'])
            evaluations.append(ev)
            if not replay_values_equal(public_relations(req,candidate),req['candidates'][i]['public_relations']):
                failures.append('public_candidate_relation_mismatch:'+req['candidates'][i]['display_label'])
        chosen=next((i for i,c in enumerate(req['candidates']) if c['display_label']==row['display_label']),None)
        witness=next((i for i,e in enumerate(evaluations) if not e['after_violation_instances']),None)
        if chosen is not None:
            ev=evaluations[chosen]
            if not replay_values_equal(ev['after_violation_instances'],row.get('after_violation_instances')):
                failures.append('selected_violation_mismatch')
            if not replay_values_equal(ev['new_business_violation_count'],row['new_business_violation_count']):
                failures.append('selected_new_count_mismatch')
        if 'avoidable_hard_wrong_selection' in case['tags']:
            if chosen is None or witness is None or not evaluations[chosen]['after_violation_instances']:
                failures.append('hard_mistake_not_reproduced')
        rawfile=parent/'selector_inputs/flash_direct_text'/rid/'response.raw.json'
        protocol_error=None
        if 'protocol_error' in case['tags']:
            if not rawfile.is_file(): failures.append('missing_raw_response')
            else:
                try:parse_old(read_json(rawfile)['raw_text'],req)
                except Exception as exc:
                    protocol_error='malformed_json' if isinstance(exc,json.JSONDecodeError) else str(exc)
                else:failures.append('protocol_error_not_reproduced')
        results.append({'request_id':rid,'tags':case['tags'],
                        'public_instruction_policy_match':public_policy==item['hidden_policy'],
                        'selected_label':row['display_label'],
                        'selected_violation_instances':evaluations[chosen]['after_violation_instances'] if chosen is not None else None,
                        'feasible_witness_label':req['candidates'][witness]['display_label'] if witness is not None else None,
                        'protocol_error':protocol_error,
                        'raw_response_sha256':sha(rawfile) if rawfile.is_file() else None,
                        'failures':failures})
    failures=[{'request_id':x['request_id'],'failures':x['failures']} for x in results if x['failures']]
    report={'status':'PASS' if len(results)==12 and not failures else 'FAIL',
            'critical_cases_checked':len(results),'failures':failures,
            'human_double_review':'PENDING','cases':results,
            'scope':'independent public instruction parsing and relation recomputation; not human signoff'}
    write_json(root/'checks/old_critical_crosscheck.json',report)
    return report


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',required=True)
    a=ap.parse_args(argv);r=crosscheck(Path(a.output))
    print(json.dumps({'status':r['status'],'critical_cases_checked':r['critical_cases_checked'],
                      'failures':r['failures']},ensure_ascii=False))
    if r['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
