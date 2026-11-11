"""JM0-A delivery verification only. Standard library; never import project code.
Run from repository root. Reads only explicitly inventoried evidence and delivery.
"""
from pathlib import Path
import ast
import hashlib
import json
import re
import sys
from urllib.parse import unquote

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
assert (ROOT / 'AGENTS.md').is_file(), 'run from repository root'


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(p):
    return json.loads(p.read_text())


def pointer(value, path):
    if path == '':
        return value
    assert path.startswith('/')
    for part in path[1:].split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


receipt = read(OUT / 'source_and_exposure_receipt.json')
assert receipt['task'] == 'JM0-A' and receipt['plan_version'] == 'JM-plan-v2'
assert all(v == 0 for v in receipt['new_operations'].values())
for p in OUT.glob('*.json'):
    assert isinstance(read(p), dict), str(p)
for a in receipt['appendices']:
    assert sha(ROOT / a['path']) == a['sha256'], a['path']
index = read(OUT / 'evidence_index.json')
for e in index['files']:
    p = ROOT / e['path']
    assert p.is_file() == e['exists'], str(p)
    if e['exists']:
        assert sha(p) == e['sha256'], e['path']
        if p.suffix == '.json':
            value = read(p)
            for point in e['pointers']:
                pointer(value, point)
for e in read(OUT / 'interface_inventory.json')['items']:
    for ref in e['references']:
        p = ROOT / ref['path']
        assert p.is_file(), ref
        if 'symbol' in ref:
            assert any(isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                       and n.name == ref['symbol'] and n.lineno == ref['line']
                       for n in ast.walk(ast.parse(p.read_text()))), ref
source = read(OUT / 'source_task_register.json')
assert len(source['source_rows']) == 27
assert source['strict_unseen_eval_admitted'] == 0
assert source['raw_bed_identity_matches_archived']
for e in source['source_rows']:
    if 'file_sha256' in e:
        assert sha(ROOT / e['data_path']) == e['file_sha256']
    assert 'NOT_READY' in e['recommended_use']['eval']
for e in source['source_rows'][-1]['workbook_identity_checks']:
    assert e['matches_archived_review'] and sha(ROOT / e['path']) == e['sha256']
components = read(OUT / 'inherited_component_register.json')
assert len(components['rows']) == 3648 and components['strict_unseen_admitted_this_audit'] == 0
coverage = read(OUT / 'material_coverage.json')
assert len(coverage['fork_points']) == 4 and len(coverage['comparisons']) == 8
assert coverage['unique_branch_receipts'] == 12 and coverage['same_start_repeats'] == 0
assert all(e['probability_complete'] and e['mapping_pool_identity_equal'] for e in coverage['fork_points'])
assert coverage['labels_v2'] == {'improved': 2, 'neutral': 6}
for e in read(OUT / 'parent_identity_checks.json')['checks']:
    assert e['status'] == 'MATCH', e
for name in ['docs/03_阶段产出分析/Jev/Jev_JM0-A源码数据来源与暴露审查_20261110.md',
             'docs/03_阶段产出分析/Jev/README.md']:
    p = ROOT / name
    # Only the newly added README row; all report local Markdown links.
    text = p.read_text()
    if p.name == 'README.md':
        text = '\n'.join(s for s in text.splitlines() if 'JM0-A' in s)
    for target in re.findall(r'\]\(([^)]+)\)', text):
        if re.match(r'https?://', target):
            continue
        target = unquote(target.split('#')[0])
        assert (p.parent / target).resolve().is_file(), (name, target)
if (OUT / 'delivery_manifest.json').exists():
    manifest = read(OUT / 'delivery_manifest.json')
    for row in manifest['files']:
        assert sha(ROOT / row['path']) == row['sha256'], row['path']
    listed = {x['path'] for x in manifest['files']}
    assert all(str(p.relative_to(ROOT)) in listed for p in OUT.iterdir()
               if p.is_file() and p.name != 'delivery_manifest.json')
result = {'version': 'jm0_a_static_validation_v1', 'status': 'PASS_STATIC_DELIVERY_CHECKS_ONLY',
          'scope': ['JSON structure and appendix hashes', 'inventoried source symbols and line numbers',
                    'inventoried parent/evidence hashes and selected JSON pointers',
                    '27 source/task rows and 3648 inherited component rows',
                    '4 frozen points, 8 comparison records, 12 deduplicated branches',
                    'selected 6 historical manifest hashes', 'report and new README row local links',
                    'delivery manifest hashes and coverage'],
          'not_run': ['behavioral tests', 'full historical validation', 'candidate generation',
                      'monitor/LP', 'model transport', 'orders', 'forks'],
          'model_calls': 0, 'order_executions': 0, 'fork_executions': 0,
          'credential_reads': 0, 'business_module_imports': 0}
if '--write' in sys.argv:
    (OUT / 'validation_receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False))
