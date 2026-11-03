"""Independent O1b release audit: public-only parser, JSON Schema, leakage and candidate replay."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

from ..config import WORKSPACE, load_config, generator_config
from ..evaluation.attribute_metrics_v2 import public_relations
from ..evaluation.policy_v2 import evaluate, optimal_set
from ..protocol import state_hash
from ..repository import ALL_SPLITS, DatasetRepository
from ..selectors.instruction_parser_o1b import resolved_public_policy
from ..vlm.pilot_protocol_v2 import digest, scan_public
from .attribute_pilot_v2 import read_json, write_json, enumerate_physical, sha


def verify(folder):
    schema=read_json(WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner/schemas/o1b_request.schema.json')
    validator=Draft202012Validator(schema)
    data=read_json(folder/'data/tasks.private.json')
    manifest=read_json(folder/'data/source_manifest.json')
    split=read_json(folder/'data/split_audit.json')
    pairs=defaultdict(list); failures=[]; covered=Counter(); public_hashes={}
    full_cache={}
    cfg=generator_config(load_config(top_k=16))
    for row in data:
        rid=row['request_id']; req=read_json(folder/row['public_request_path'])
        physical=read_json(folder/'data/physical_groups'/f"{row['physical_group_id']}.private.json")
        if row['physical_group_id'] not in full_cache:
            full_cache[row['physical_group_id']]=enumerate_physical(physical['state'],cfg)
        full=full_cache[row['physical_group_id']]
        errors=list(validator.iter_errors(req))
        if errors: failures.append([rid,'schema',errors[0].message])
        if req['request_id']!=rid: failures.append([rid,'request_id'])
        if req['state_hash']!=state_hash(req['container'],req): failures.append([rid,'state_hash'])
        if req['policy_digest']!=digest({'grammar':'o1b_instruction_1','instruction_text':req['instruction_text']}):
            failures.append([rid,'policy_digest'])
        if req['candidates']!=physical['public_candidates']: failures.append([rid,'candidate_mapping'])
        if req['placed_items']!=physical['state']['placed_items'] or req['available_items']!=physical['state']['available_items']:
            failures.append([rid,'physical_state'])
        scan=scan_public(req,physical['mapping'].values())
        if scan['status']!='PASS': failures.append([rid,'leakage',scan['hits']])
        try:
            parsed=resolved_public_policy(req['instruction_text'],req)
            if parsed!=row['resolved_policy']: failures.append([rid,'public_policy_mismatch'])
        except Exception as exc:
            failures.append([rid,'public_parser',type(exc).__name__])
        for c,public in zip(physical['physical_candidates'],req['candidates']):
            if public['public_relations']!=public_relations(physical['state'],c):
                failures.append([rid,'public_relation_replay'])
        evals=[evaluate(req,c,row['resolved_policy'],req['container']) for c in physical['physical_candidates']]
        if evals!=row['evaluations']: failures.append([rid,'evaluation_replay'])
        optimum=optimal_set(evals)
        if optimum!=row['optimum']: failures.append([rid,'optimal_set_replay'])
        if [req['candidates'][i]['display_label'] for i in optimum['equivalent_indices']]!=row['coverage']['equivalent_labels']:
            failures.append([rid,'equivalence_label'])
        full_feasible=sum(not e['after_violation_instances'] for e in
                          (evaluate(req,c,row['resolved_policy'],req['container']) for c in full))
        if full_feasible!=row['coverage']['full_feasible_count']:
            failures.append([rid,'full_enumeration_coverage'])
        category='topk_covered' if optimum['feasible_indices'] else ('topk_lost' if full_feasible else 'enumeration_no_feasible')
        if category!=row['coverage']['coverage_category']:
            failures.append([rid,'coverage_category'])
        covered[row['coverage']['coverage_category']]+=1
        pairs[row['physical_group_id'],row['track']].append(row)
        public_hashes[rid]=scan['sha256']
    for (gid,track),records in pairs.items():
        if len(records)!=2 or {r['variant'] for r in records}!={0,1}:
            failures.append([gid,track,'missing_variant'])
        reqs=[read_json(folder/r['public_request_path']) for r in records]
        for field in ('state_hash','container','placed_items','available_items','candidates'):
            if reqs[0][field]!=reqs[1][field]: failures.append([gid,track,'paired_'+field])
    for gid in {m['physical_group_id'] for m in manifest}:
        a=sorted(pairs[gid,'A'],key=lambda r:r['variant'])
        b=sorted(pairs[gid,'B'],key=lambda r:r['variant'])
        c=sorted(pairs[gid,'C'],key=lambda r:r['variant'])
        if len(a)==len(b)==len(c)==2:
            for v in (0,1):
                if a[v]['resolved_policy']!=b[v]['resolved_policy'] or a[v]['optimum']!=b[v]['optimum']:
                    failures.append([gid,'paraphrase_invariance'])
                if c[v]['resolved_policy']!=a[1-v]['resolved_policy'] and c[v]['resolved_policy']!=a[v]['resolved_policy']:
                    failures.append([gid,'conditional_branch'])
    sources={m['source_order_key'] for m in manifest}
    if len(sources)!=30 or len(data)!=180 or len(pairs)!=90: failures.append(['release_scale'])
    if sources!=set(split['source_keys']): failures.append(['source_manifest'])
    repo=DatasetRepository(load_config()['dataset'])
    for m in manifest:
        case=repo.get_decision_case(m['source_case_id'])
        if repo.split_for(m['source_case_id'])!='train' or case['base_scenario_id']!=m['source_scenario_id']:
            failures.append([m['physical_group_id'],'source_identity'])
    for name in ALL_SPLITS:
        if not name.startswith('test') and name!='validation': continue
        other=set()
        for sid in repo.list_scenarios(name):
            a=read_json(repo.root/'annotations/ground_truth_rules'/f'{sid}.json')
            other.add(str(a.get('source_order_key',a.get('source_order_id',sid))))
        if sources&other: failures.append(['cross_split_overlap',name,sorted(sources&other)])
    report={'status':'PASS' if not failures else 'FAIL','tasks_checked':len(data),
            'source_orders_checked':len(sources),'paired_tracks_checked':len(pairs),
            'schema_and_public_leakage_checked':True,'public_policy_reparsed':True,
            'candidate_relations_recomputed':True,'evaluation_and_optimum_recomputed':True,
            'full_physical_enumeration_recomputed':True,
            'verifier_source_sha256':sha(Path(__file__)),
            'coverage_categories':dict(covered),'failures':failures,
            'human_review':'PENDING','scope':'independent program audit, not double human signoff'}
    write_json(folder/'checks/independent_verification.json',report)
    pair_rows=[]
    import csv
    with (folder/'metrics/policy_pairs.csv').open(encoding='utf-8-sig',newline='') as f:
        pair_rows=list(csv.DictReader(f))
    opportunity_sources={r['source_order_key'] for r in pair_rows if r['classification']=='opportunity'}
    matrix={
        'source_orders_and_split':'PASS' if len(sources)==30 and not failures else 'FAIL',
        'three_language_tracks_and_shared_physics':'PASS' if len(data)==180 and len(pairs)==90 and not failures else 'FAIL',
        'policy_switch_difference_or_control':'PASS' if len(pair_rows)==90 and len(opportunity_sources)==10 else 'FAIL',
        'candidate_coverage_and_old_no_feasible_regression':'PASS' if not failures and
            read_json(folder/'audit/old_no_feasible_regression.json')['count']==10 else 'FAIL',
        'public_parser_and_cross_reference':'PASS' if not failures else 'FAIL',
        'source_template_policy_holdout_audit':'PASS' if not failures and not split['overlap_all_test_splits'] else 'FAIL',
        'two_independent_human_ast_reviews':'PENDING',
        'measured_human_maintenance_cost':'PENDING',
        'overall_o1b_acceptance':'PENDING_HUMAN_ITEMS' if not failures else 'FAIL',
        'opportunity_independent_source_orders':len(opportunity_sources),
        'original_validation_source_orders_unchanged':split['original_validation_source_count'],
        'derived_development_validation_source_orders':len(sources),
        'not_unseen_test_evidence':True}
    write_json(folder/'checks/o1b_acceptance_matrix.json',matrix)
    return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    result=verify(args.output.resolve())
    print(json.dumps(result,ensure_ascii=False))
    if result['status']!='PASS': raise SystemExit(1)


if __name__=='__main__':main()
