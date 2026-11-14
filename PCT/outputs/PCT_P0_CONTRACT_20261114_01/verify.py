"""Validate the P0 delivery from the repository root without importing runtime code."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

directory = Path(__file__).resolve().relative_to(Path.cwd()).parent
report, = Path('PCT/docs').glob('*P0*20261114_01.md')
manifest_path = directory / 'delivery_manifest.json'

def load(path):
    return json.loads(path.read_text())

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    manifest = load(manifest_path)
    expected = {p for p in directory.iterdir() if p.is_file() and p != manifest_path}
    expected.update([report, Path('PCT/README.md')])
    assert set(manifest['sha256']) == {str(p) for p in expected}
    assert all(sha(p) == manifest['sha256'][str(p)] for p in expected)
    for path in directory.glob('*.json'):
        load(path)
    for path in (report, Path('PCT/README.md')):
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if '://' not in target:
                assert (path.parent / target.split('#')[0]).exists(), target
    identity = load(directory/'identity.json')
    assert all(sha(Path(p)) == digest for p,digest in identity['files'].items())
    data = load(directory/'data_audit.json')
    assert data['packaging_identity_recomputed'] and data['synthetic_identity_recomputed']
    assert all(not row[k] for row in data['inventories'].values() for k in ['missing','extra','changed'])
    assert all(sha(Path(t['path'])) == t['sha256'] for t in data['tasks'])
    contract = load(directory/'p0_contract.json')
    assert len(data['tasks']) == 22 and sum(t['count'] for t in data['tasks']) == 428
    counts = {t['task_id']: t['count'] for t in data['tasks']}
    p3 = contract['p3']
    assert sum(counts[t] for t in p3['tasks']) == p3['boxes'] == 33
    assert (p3['local_jobs'],p3['monitor_cap'],p3['network_choice_cap']) == (6,33*3,33*2)
    assert p3['training_actions'] == 33*8 and p3['training_attempts']//8 == p3['training_updates']
    evaluation = contract['evaluation']
    assert evaluation['slots'] == 22*(1+3+3+3)
    assert evaluation['jev_send_cap'] == 428*3 and evaluation['pct_choice_cap'] == 428*6
    train = contract['training']
    assert train['attempts_per_model'] == 16*125 and train['updates_per_model'] == 2000//8
    assert train['action_cap_per_model'] == 264*125 and train['total_action_cap'] == 33000*6
    for name, fields in contract['features'].items():
        dims = [len(fields[key]) for key in ('placed','leaf','current')]
        assert dims == contract['model']['geo_dims' if '_geo_' in name else 'load_dims']
        assert all([f['index'] for f in group] == list(range(len(group))) for group in fields.values())
    changes = load(directory/'external_changes.json')
    assert all(Path(e['file']).exists() and e['application_status']=='NOT_APPLIED' for e in changes['entries'])
    assert set(load(directory/'handoff.json')['external_review']) == {e['file'] for e in changes['entries'] if e['phase']=='P1-A'}
    assert set(load(directory/'acceptance.json')) == {'B00','B01','B02','B03'}
    assert subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],text=True).splitlines() == ['?? PCT/']
    assert subprocess.check_output(['git','-C','Online-3D-BPP-PCT','status','--porcelain'],text=True) == ''
    print('PASS: delivery, source and task digests, links, JSON, feature dimensions, matrix, Git scope')

if __name__ == '__main__':
    main()
