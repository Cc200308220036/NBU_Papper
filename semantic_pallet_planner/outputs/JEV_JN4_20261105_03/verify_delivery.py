"""Static delivery identity review only. No planner imports or trajectory dispatch.

Run --seal once to record static checks and build a new delivery manifest.
Default operation is read-only and verifies the sealed artifact hashes as well.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
REPORT = 'docs/03_阶段产出分析/Jev/Jev_JN4-A真实来源履历核验与冻结缺口验收_20261105.md'
DOCS = [REPORT, 'docs/02_阶段实施方案/Jev/README.md', 'docs/03_阶段产出分析/Jev/README.md']


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root):
    return {str(f.relative_to(root)): sha(f) for f in sorted(root.rglob('*')) if f.is_file()}


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def check():
    inputs = read(HERE / 'review_inputs.json')['files_sha256']
    for name, expected in inputs.items():
        assert sha(REPO / name) == expected, ('input_changed', name)
    before = read(HERE / 'historical_bytes_before.json')
    for name, frozen in before.items():
        assert tree(REPO / name) == frozen, ('history_changed', name)
    production = read(HERE / 'source_manifest.json')
    for name, expected in production.items():
        assert sha(REPO / 'semantic_pallet_planner/src/semantic_pallet_planner' / name) == expected, name
    raw = read(REPO / 'raw/bed_bpp/bed-bpp_v1.json')
    parent = HERE.parent / 'JEV_JN4_20261105_02'
    admissions = read(parent / 'source_admission.json')['records']
    rows = read(HERE / 'component_evidence_gaps.json')['records']
    assert len(rows) == len(admissions) == 3648
    by_id = {a['source_identity']['component']: a for a in admissions}
    assert len(by_id) == len(rows)
    for row in rows:
        original = by_id[row['component']]
        key = min(original['source_identity']['raw_keys'])
        assert row['representative_raw_key'] == key
        assert row['representative_box_count'] == len(raw[key]['item_sequence'])
        assert row['inherited_status'] == original['status']
        assert row['inherited_gaps'] == original['gaps']
        assert row['strict_test_eligible'] is original['strict_test_eligible'] is False
    strata = read(HERE / 'stratum_readiness.json')['strata']
    for item in strata:
        lo, hi = item['length_bin']
        counts = Counter(r['inherited_status'] for r in rows if lo <= r['representative_box_count'] <= hi)
        assert dict(counts) == item['inherited_component_status_counts']
        assert item['available_verified_components'] == 0 and item['shortfall'] == 2
    receipt = read(HERE / 'evaluation_plan_receipt.json')
    handoff = read(HERE / 'handoff.json')
    matrix = read(HERE / 'formal_experiment_matrix.json')
    for doc in (receipt, handoff):
        assert doc['JN4_B_admitted'] is doc['data_ready'] is doc['formal_matrix_frozen'] is False
        assert doc['actual_model_api_calls'] == doc['actual_formal_test_jobs_executed'] == 0
    assert receipt['criteria'] == read(HERE / 'engineering_acceptance.json')['criteria']
    assert receipt['nonempty_formal_plan'] is handoff['formal_plan'] is None
    assert matrix['jobs'] == matrix['task_ids'] == [] and matrix['frozen'] is False
    assert matrix['not_a_runnable_formal_plan'] is True
    assert matrix['natural_job_slots'] == matrix['remote_job_slots'] == matrix['shared_batch_send_cap'] == 0
    links = 0
    for name in DOCS:
        path = REPO / name
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if '://' in target or target.startswith('#'):
                continue
            target = target.split('#')[0]
            assert (path.parent / target).exists(), ('broken_link', name, target)
            links += 1
    return {'status': 'PASS_STATIC_REVIEW_ONLY', 'historical_packages': len(before),
            'historical_files_unchanged': sum(len(v) for v in before.values()),
            'production_file_identities_verified': len(production), 'input_files_verified': len(inputs),
            'component_rows_checked': len(rows), 'strata_checked': len(strata), 'local_links_checked': links,
            'engineering_tests': 'NOT_RUN_THIS_REVIEW', 'real_data_loading': 'NOT_RUN_NO_ADMITTED_DATA',
            'new_fake_tests': 0, 'model_api_calls': 0, 'formal_test_jobs': 0,
            'scope': 'standard library file/hash/metadata checks; no runtime or model imports',
            'delivery_manifest': 'Sealed after static_validation.json; checked by default invocation'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seal', action='store_true')
    args = parser.parse_args()
    result = check()
    manifest_path = HERE / 'delivery_manifest.json'
    if args.seal:
        assert not manifest_path.exists(), 'refuse_to_reseal_existing_delivery'
        write(HERE / 'static_validation.json', result)
        files = tree(HERE)
        write(manifest_path, {'version': 'jev_jn4_real_source_review_delivery_v1',
              'files_sha256': files, 'exclusion': 'root delivery_manifest.json only',
              'documentation_sha256': {p: sha(REPO / p) for p in DOCS},
              'JN4_B_admitted': False})
    manifest = read(manifest_path)
    files = tree(HERE)
    files.pop('delivery_manifest.json')
    assert files == manifest['files_sha256'], 'delivery_bytes_or_file_set_changed'
    for name, expected in manifest['documentation_sha256'].items():
        assert sha(REPO / name) == expected, ('delivery_doc_changed', name)
    assert read(HERE / 'static_validation.json') == result, 'static_result_changed'
    print(json.dumps({'static_validation': result, 'delivery_manifest_check': 'PASS',
                      'delivery_files': len(files)}, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
