"""Read-only identity/readiness check; --seal only creates a new manifest once."""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DOCS = ['docs/03_阶段产出分析/Jev/Jev_JN4-A路线B交接材料核验与准备阻断_20261105.md',
        'docs/03_阶段产出分析/Jev/README.md', 'docs/02_阶段实施方案/Jev/README.md']


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree(p):
    return {str(f.relative_to(p)): sha(f) for f in sorted(p.rglob('*')) if f.is_file()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seal', action='store_true')
    args = ap.parse_args()
    history = read(HERE / 'historical_identity_check.json')
    assert history['after_identical'] is True
    for p, expected in history['before'].items():
        assert tree(ROOT / p) == expected, ('historical_bytes_changed', p)
    sources = read(HERE / 'source_manifest.json')
    for p, h in sources.items():
        assert sha(ROOT / 'semantic_pallet_planner/src/semantic_pallet_planner' / p) == h, p
    raw = read(HERE / 'available_raw_inventory.json')['files']
    for p, v in raw.items():
        assert sha(ROOT / p) == v['sha256'], p
        assert (ROOT / p).stat().st_size == v['bytes'], p
    receipt = read(HERE / 'evaluation_plan_receipt.json')
    handoff = read(HERE / 'handoff.json')
    assert receipt['status'] == handoff['status'] == 'PREPARATION_BLOCKED'
    assert receipt['source_handoff_status'] == 'SOURCE_HANDOFF_INCOMPLETE'
    assert receipt['formal_plan'] is handoff['formal_plan'] is None
    assert receipt['JN4_B_admitted'] is handoff['JN4_B_admitted'] is False
    assert receipt['data_ready'] is receipt['formal_matrix_frozen'] is False
    for field in ['formal_task_count', 'natural_job_slots', 'remote_job_slots', 'formal_shared_send_cap',
                  'actual_model_api_calls', 'credential_reads', 'actual_formal_test_jobs_executed', 'new_fake_tests']:
        assert receipt[field] == 0, field
    review = read(HERE / 'candidate_source_review.json')
    books = review['workbook_reviews']
    assert len(books) == 11
    assert sum(b['status'] == 'INVALID_XLSX_CONTAINER' for b in books) == 1
    report = ROOT / DOCS[0]
    for link in re.findall(r'\]\(([^)]+)\)', report.read_text()):
        if '://' not in link:
            assert (report.parent / link.split('#')[0]).exists(), link
    mp = HERE / 'delivery_manifest.json'
    if args.seal:
        assert not mp.exists(), 'existing_manifest_must_not_be_resealed'
        manifest = {'version': 'jev_jn4_route_b_review_manifest_v1', 'files_sha256': tree(HERE),
                    'exclusion': 'root delivery_manifest.json only',
                    'documentation_sha256': {p: sha(ROOT / p) for p in DOCS}, 'JN4_B_admitted': False}
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    manifest = read(mp)
    actual = tree(HERE)
    actual.pop('delivery_manifest.json')
    assert actual == manifest['files_sha256'], 'delivery_changed'
    for p, h in manifest['documentation_sha256'].items():
        assert sha(ROOT / p) == h, ('documentation_changed', p)
    print(json.dumps({'status': 'STATIC_IDENTITY_CHECK_PASS', 'preparation_status': receipt['status'],
                      'raw_files': len(raw), 'production_files': len(sources),
                      'historical_files_unchanged': sum(len(v) for v in history['before'].values()),
                      'workbook_like_files': len(books), 'formal_jobs': 0, 'model_calls': 0,
                      'engineering_tests': 'NOT_RUN'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
