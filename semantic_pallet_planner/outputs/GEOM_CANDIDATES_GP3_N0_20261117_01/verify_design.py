"""Read-only stdlib verification of this DESIGN_ONLY delivery, no project imports."""
import argparse
import hashlib
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser()
parser.add_argument('--sealed', action='store_true')
args = parser.parse_args()
out = Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N0_20261117_01')
package = Path('semantic_pallet_planner/src/semantic_pallet_planner')
doc = Path('docs/02_阶段实施方案/几何规划模块/几何候选器GP3-N0运行时数值合同设计补充_20261117_01.md')


def read(p):
    return json.loads(p.read_bytes())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


recorded = read(out / 'source_manifest.json')['files']
actual = {p.relative_to(package).as_posix(): sha(p) for p in sorted(package.rglob('*'))
          if p.is_file() and p.suffix in ('.py', '.json')
          and not {'tests', '__pycache__'}.intersection(p.relative_to(package).parts)}
assert actual == recorded and len(actual) == 527
for name, expected in read(out / 'protected_files.json')['files'].items():
    assert sha(Path(name)) == expected, name
json_count = 0
for path in out.glob('*.json'):
    # The first run may redirect stdout to this file; the shell creates/truncates
    # it before this process starts. The sealed run checks the saved result too.
    if not args.sealed and path.name == 'verification.json':
        continue
    read(path)
    json_count += 1
links = 0
for path in (doc, doc.parent / 'README.md'):
    for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
        if '://' not in target:
            assert (path.parent / target.split('#')[0]).exists(), target
            links += 1
versions = read(out / 'interface_and_identity.json')['proposed_versions']
for name in versions.values():
    assert not any(name in (package / f).read_text() for f in actual), name
if args.sealed:
    m = read(out / 'delivery_manifest.json')
    for row in m['files']:
        assert sha(Path(row['path'])) == row['sha256'], row['path']
        assert Path(row['path']).stat().st_size == row['size_bytes'], row['path']
    expected = {p.as_posix() for p in out.iterdir() if p.is_file()
                and p.name not in ('delivery_manifest.json', 'seal_verification.log')}
    expected |= {doc.as_posix(), (doc.parent / 'README.md').as_posix()}
    assert {r['path'] for r in m['files']} == expected, 'unlisted delivery members'
print(json.dumps({'status': 'PASS_DOCUMENT_AND_IDENTITY_CHECKS_ONLY',
                  'production_files_unchanged': len(actual), 'json_files_parsed': json_count,
                  'local_links_checked': links, 'protected_history': 'UNCHANGED',
                  'proposed_names': 'NOT_REGISTERED_IN_PRODUCTION',
                  'sealed_manifest_verified': args.sealed,
                  'numeric_evidence': read(out / 'numeric_examples.json')['status'],
                  'runtime_adapters_schemas_checkpoint': 'NOT_RUN',
                  'A03': 'PARTIAL_UNCHANGED'}, ensure_ascii=False))
