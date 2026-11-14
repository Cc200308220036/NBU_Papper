"""P0 read-only evidence collector. Run from the repository root."""
import ast
import hashlib
import importlib.metadata
import itertools
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).parent
BASE = Path('semantic_pallet_planner/src/semantic_pallet_planner')
UP = Path('Online-3D-BPP-PCT')
ARCHIVE = Path('semantic_pallet_planner/outputs')
PACK = ARCHIVE / 'DATA_JEV_PACKAGING_LOAD_20261102_02'
SYN = ARCHIVE / 'JEV_JN4_SYNTH_20261105_01/data'
SUPPORT = ARCHIVE / 'JEV_JM1_C2_REAL_SUFFIXES_20261113_01'
GROUP = ARCHIVE / 'JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/materials/source_exposure_audit.json'
PLAN, = Path('PCT/docs').glob('*实施方案*')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text())

def digest(value):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()

def write(name, value):
    (OUT / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def main():
    commands = []
    def git(*args):
        cmd = ['git', *args]
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
        commands.append(dict(argv=cmd, exit_code=result.returncode, stdout=result.stdout, scope='read-only Git'))
        return result.stdout.strip()

    primary = dict(branch=git('branch','--show-current'), status=git('status','--short'),
                   log=git('log','-5','--oneline'), head=git('rev-parse','HEAD'))
    upstream = dict(head=git('-C',str(UP),'rev-parse','HEAD'), status=git('-C',str(UP),'status','--short'),
                    log=git('-C',str(UP),'log','-5','--oneline'), root_tracking=git('ls-files','--stage',str(UP)))
    assert primary['branch'] == 'dev/PCT'
    expected_hashes = dict(re.findall(r'\| `([^\x60]+)` \| `([a-f0-9]{64})` \|', PLAN.read_text()))
    assert len(expected_hashes) == 8
    assert all(sha(UP / p) == h for p, h in expected_hashes.items())
    upstream['plan_hash_matches'] = expected_hashes
    sources = 'contracts config packaging_versions packaging_runtime candidates context selector episode execution packaging_remote packaging_jev_v13 packaging_exact_protocol packaging_protocol packaging_metrics experiment dataset dataset_packaging packaging_synthetic_data ledger stability/monitor stability/exact_adapter stability/exact_contracts stability/balance_contracts stability/runtime'.split()
    source_paths = [BASE / 'jev_select' / (name + '.py') for name in sources]
    source_paths.extend(BASE / p for p in ['o4/buffer/buffer_state.py','o4/extensions/e2/protocol.py','o4/extensions/e2/candidates.py','evaluation/geometry_oracle.py'])
    schema_dir = BASE / 'jev_select/schemas'
    schemas = [p for p in sorted(schema_dir.glob('*.schema.json'))
               if re.match(r'(config|candidate_bundle|decision_context|selection_result|checkpoint)_v1[23]\.|(packaging_load_task_v1|evaluation_packaging_task_v1|jm_v13_execution|jm_v13_journal|synthetic_dataset_v1)\.', p.name)]
    for path in schemas:
        assert 'properties' in read(path)
    pyfiles = sorted(UP.rglob('*.py'))
    errors = []
    for path in pyfiles + source_paths:
        try:
            ast.parse(path.read_bytes(), filename=str(path))
        except SyntaxError as exc:
            errors.append(dict(path=str(path), line=exc.lineno, error=exc.msg))
    assert any(row['path'] == str(UP/'evaluation.py') for row in errors), errors
    upstream['ast'] = dict(python_files=len(pyfiles), errors=errors)
    manifest_paths = [PACK / n for n in ['manifest.json','handoff.json','source_manifest.json','split_manifest.json','config.snapshot.json','delivery_manifest.json']]
    manifest_paths += [SYN / n for n in ['dataset.json','registration.json','relations.json','samples.json','historical_inputs.json','delivery_manifest.json']]
    manifest_paths += [SUPPORT/'source_and_start_support.json', GROUP]
    packaging = read(PACK/'manifest.json')
    synthetic = read(SYN/'dataset.json')
    assert packaging['data_identity'] == '9cf6d039543df402d04d406f45cd8cff00ee0a5ab49540190662e7f0d18f21de'
    assert synthetic['data_identity'] == 'b13d9c6ea93b24e6f76032284560913cd26ed4e09315650552ceefd8c20d86e6'
    assert digest({k:v for k,v in synthetic.items() if k!='data_identity'}) == synthetic['data_identity']
    group_rows = read(GROUP)['grouping']['material_components']
    groups = {tid:digest(row) for row in group_rows for tid in row['tasks']}
    rows = []
    inventories = {}
    for root in (PACK, SYN):
        inventory = read(root/'delivery_manifest.json')
        actual = {str(path.relative_to(root)):sha(path) for path in root.rglob('*') if path.is_file() and path.name != 'delivery_manifest.json'}
        inventories[str(root)] = dict(registered=len(inventory), missing=sorted(inventory.keys()-actual.keys()),
                                      extra=sorted(actual.keys()-inventory.keys()),
                                      changed=sorted(k for k in inventory.keys() & actual.keys() if inventory[k]!=actual[k]))
        for path in sorted((root/'tasks').glob('*.json')):
            t = read(path)
            ids = [i['item_id'] for i in t['items']]
            assert ids and len(ids)==len(set(ids)) and ids==t['arrival_order']
            assert t['buffer_capacity']==3 and t['candidate_limits']=={'joint':48,'per_box':16}
            assert t['container']['coordinate_frame']=='container_bottom_center'
            assert t['regions']==t['rules']==[]
            for item in t['items']:
                assert all(v>0 for v in item['dimensions_mm'].values()) and item['mass_kg']>0
                assert type(item['stackable']) is bool
                cap = item['top_load_limit_kg_synthetic']
                assert cap==item['max_top_load_kg'] and cap>=0
                assert item['effective_top_permission_kg']==(cap if item['stackable'] else 0)
            if root==SYN:
                assert t in synthetic['tasks']
            rows.append(dict(path=str(path), sha256=sha(path), digest=digest(t), task_id=t['task_id'],
                             count=len(ids), parent_version=t['version'], parent_layer=t['layer'], partition=t['partition'],
                             original_order=t['source_order_key'] if root==PACK else None, source_group=t['source_group_id'],
                             conservative_component=groups[t['task_id']], container=t['container'],
                             mass_kg=sum(i['mass_kg'] for i in t['items']),
                             volume_mm3=sum(i['dimensions_mm']['length']*i['dimensions_mm']['width']*i['dimensions_mm']['height'] for i in t['items']),
                             purpose='TRAIN_AND_IN_SAMPLE_RETEST' if root==PACK else 'EXPOSED_FAMILIAR_PROTOTYPE_DIAGNOSTIC'))
    assert len(rows)==22 and sum(row['count'] for row in rows[:16])==264 and sum(row['count'] for row in rows[16:])==164
    pack_tasks = [read(Path(row['path'])) for row in rows[:16]]
    spec, split = read(PACK/'config.snapshot.json'), read(PACK/'split_manifest.json')
    # Recover source/layer iteration order from archived registries.
    source_orders = list(dict.fromkeys(t['source_order_key'] for t in pack_tasks))
    layers = list(dict.fromkeys(t['layer'] for t in pack_tasks))
    lookup = {(t['source_order_key'],t['layer']):t for t in pack_tasks}
    matched_order = None
    for orders in itertools.permutations(source_orders):
        for layer_order in itertools.permutations(layers):
            tasks = [lookup[order,layer] for order in orders for layer in layer_order]
            if digest(dict(config=spec,tasks=tasks,split=split))==packaging['data_identity']:
                matched_order = [t['task_id'] for t in tasks]
                break
        if matched_order:
            break
    write('data_audit',dict(tasks=rows, inventories=inventories, packaging_identity_recomputed=bool(matched_order),
                            packaging_archive_order=matched_order, synthetic_identity_recomputed=True,
                            component_groups=group_rows, independent_admitted=0))
    checked = source_paths + schemas + manifest_paths + [PLAN, Path('AGENTS.md'),Path('PCT/README.md')]
    checked += [UP / n for n in ['README.md','LICENSE','model.py','attention_model.py','graph_encoder.py','distributions.py','tools.py','train_tools.py','storage.py','evaluation.py','evaluation_tools.py']]
    checked += [UP / 'pct_envs' / env / f for env in ['PctContinuous0','PctDiscrete0'] for f in ['bin3D.py','space.py','binCreator.py']]
    write('identity',dict(primary=primary, upstream=upstream, files={str(p):sha(p) for p in checked},
                          parent_data=[packaging['data_identity'],synthetic['data_identity']]))
    packages = {}
    for name in ['torch','gym','gymnasium','numpy','scipy','jsonschema','pytest','matplotlib','Pillow','PyYAML','setuptools','semantic-pallet-planner']:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = 'NOT_FOUND_IN_THIS_INTERPRETER'
    write('environment_evidence',dict(executable=sys.executable, python=platform.python_version(), platform=platform.platform(),
                                     machine=platform.machine(), executable_sha256=sha(Path(sys.executable)), packages=packages,
                                     historical_identity=read(SUPPORT/'presend_identity_receipt.json')['identity']))
    commands.append(dict(argv=['python3',str(Path(__file__).relative_to(Path.cwd()))] if Path(__file__).is_absolute() else ['python3',str(Path(__file__))],
                         exit_code=0, scope='AST/JSON/SHA256/package metadata only',
                         results=['identity.json','data_audit.json','environment_evidence.json']))
    write('commands_and_results',dict(interpreter=sys.executable, commands=commands, credential_reads=0))

if __name__ == '__main__':
    main()
