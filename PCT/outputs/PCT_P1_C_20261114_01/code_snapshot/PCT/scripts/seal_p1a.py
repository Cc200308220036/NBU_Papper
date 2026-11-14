"""Seal this development delivery once; does not mark unrun integration PASS."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'PCT/src'))
from pct_baseline.contracts import read,sha,write_new,digest

OUT=ROOT/'PCT/outputs/PCT_P1_A_20261114_01'
REL='PCT/outputs/PCT_P1_A_20261114_01'
PUBLIC='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/'


def put(name,value):write_new(OUT/(name+'.json'),value)


def main():
    modified=subprocess.run(['git','diff','--name-only'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.splitlines()
    allowed={PUBLIC+n for n in ['packaging_versions.py','contracts.py','config.py','packaging_runtime.py','candidates.py','context.py']}
    assert set(modified)<=allowed
    patch=subprocess.run(['git','diff','--',*modified],cwd=ROOT,capture_output=True,check=True).stdout
    with (OUT/'public_changes.patch').open('xb') as stream:stream.write(patch)
    external=[]
    for path in modified:
        old=subprocess.run(['git','show','HEAD:'+path],cwd=ROOT,capture_output=True,check=True).stdout
        external.append({'path':path,'before_sha256':hashlib.sha256(old).hexdigest(),'after_sha256':sha(ROOT/path),
                         'status':'APPLIED_P1_A_ONLY','impact':'Source bytes changed; retain historical frozen source for old recovery; never re-sign historical runtime identities'})
    put('external_changes',{'version':'pct_p1a_external_changes_v1','authorization':'User explicitly authorized full P1-A and six named public files in this task; supersedes old QA authorization gap, not its historical conclusion',
        'actual':external,'candidates_py':{'modified':False,'equivalent_protection':'validate_bundle -> validate_schema -> pct_baseline.protocol.validate_value(candidate_bundle_b1_v1): unfiltered empty/null; filtered physical_feasible exact pool equality and independently recalculated digests',
        'local_evidence':'test_b1_dispatch.test_unfiltered_and_filtered_pool_invariants PASS','public_integration':'NOT_RUN: jsonschema missing'},
        'excluded':['selector.py','episode.py','stability/monitor.py','execution.py','all legacy schemas/config resources','third party']})
    put('contract_notes',{'version':'pct_p1a_contract_notes_v1','parent':'PCT/outputs/PCT_P0_CONTRACT_20261114_01/p0_contract.json',
        'P0-Q01':{'status':'DEFERRED_TO_TRAINING_VALIDATION','consumption':'P0 actual segment length and detach(G)/bootstrap clarification governs future versioned training implementation over fixed-n shorthand in original plan; original plan/package unchanged; numeric/gradient cases NOT_RUN'},
        'P0-Q02':{'status':'DEFERRED_TO_P2_A','consumption':'Preserve upstream dot-product pointer; no independent glimpse softmax/value aggregation is introduced by wording. Actual graph attention, pooling and leaf-logit masks require later numerical validation; NOT_RUN'},
        'P0-Q03':{'status':'LIMITED_EVIDENCE_ADDED','evidence':'verification_final/environment.json, ast.json, public_import.json; interpreter located in existing runtime cache; search is not exhaustive'}})
    rows=[
        {'id':'B10','status':'PARTIAL','implemented':['dual exact parent authentication','capacity1 projection','field-by-field expected derivation equality','parent byte/content/derived identities','closed task Schema'],
         'local_pass':['22 tasks / 428 items, two parent identities and inventories','seven runtime physical fields, container, full item set, order','empty/duplicate/order/identity/content/byte/physical alias/derived resealing drift rejection'],
         'not_run':['actual parent JSON Schema validation under runtime','derived full JSON Schema validation','existing runtime_task projection equivalence'],
         'evidence':['data/dataset.json','verification_final/data.json','verification_final/tests.json','verification_final/full_schema.json']},
        {'id':'B11','status':'PARTIAL','implemented':['shared public_facts explicit capacity1, old capacity3','observed pending/ID/slot/EOS checks','original candidate mapping and deterministic reconstruction','public whitelist and local null request_body'],
         'local_pass':['construct-only current/last box and EOS','capacity/future/duplicate/identity/slot rejection','empty order and arrival-order mismatch rejection'],
         'not_run':['actual public ContextBuilder and request whitelist','exact mapping/pose tampering against public bundle','EOS public context and capacity3 baseline behavior'],
         'evidence':['verification_final/tests.json','PCT/tests/test_b1_context.py','PCT/tests/test_b1_integration.py']},
        {'id':'B12','status':'PARTIAL','implemented':['five exact closed schemas and version/name routing','lazy extension loader and genuine internal dependency diagnosis','unfiltered versus physical-feasible invariants','legacy branches/resources protected'],
         'local_pass':['exact descriptor names and mismatches','loader absence and internal missing dependency (mocked import boundary)','filtered physical pool equality rejection','172 old schemas/config resources byte-identical to HEAD','related source AST on Python3.12'],
         'not_run':['public jsonschema validation, extra fields, unknown/forged object versions','actual public old-protocol import with extension absent','actual capacity3 context byte equivalence','public mapping tamper reconstruction'],
         'evidence':['verification_final/tests.json','verification_final/legacy_resources.json','verification_final/ast.json','verification_final/public_import.json']}]
    put('acceptance',{'version':'pct_p1a_acceptance_v1','status':'PARTIAL','matrix':rows,'implementation_status':'SOURCE_INTEGRATED_NOT_RUNTIME_ACCEPTED',
        'local_tests':{'discovered':18,'passed':13,'skipped_NOT_RUN':5,'failed':0},'formal_execution_admitted':False,
        'four_facts':'P0 reports design only; source implemented this turn; archives supplied; local recheck limited as listed. No overall PASS.'})
    put('limitations',{'version':'pct_p1a_limitations_v1','status':'PARTIAL','blocking':['existing CPython3.12.14 lacks jsonschema and dependencies; public contracts import exits1'],
        'preparation_authorization_required':{'scope':'PCT isolated Python3.12 environment, jsonschema==4.23.0 and necessary transitive dependencies; preserve existing NumPy2.3.5 source path or report inability before expanding install',
            'not_authorized_here':'No dependency installation performed; no Torch/Gym/SciPy/pytest needed for this unit'},
        'unverified':['full Schema validity','public imports/routing','capacity1/legacy context behavior','candidate mapping tampering public integration'],
        'forbidden_NOT_RUN':['order execution','candidate generation/rebuild','LP','monitor/commit/recovery','model/transport requests','training','weights downloads','third-party update'],
        'research':'No learned policy, results or gains. Data exposed; independent holdout admitted=0; synthetic packaging capacities and feasibility UNKNOWN preserved through parent identities',
        'P0-Q01':'Retained; later training numeric/gradient validation NOT_RUN','P0-Q02':'Retained; later network equivalence NOT_RUN','P0-Q03':'Limited interpreter/AST/import evidence added; no exhaustive machine search',
        'historical_identity':'Five public source changes affect frozen source identity. Historical outputs not re-signed; old restores require their original source.'})
    commands=read(OUT/'verification_final/commands_and_results.json')
    commands['additional_actual_commands']=[{'command':'python3 PCT/scripts/build_schemas.py','exit_code':0,'scope':'writes new PCT schema resources only'},
        {'command':'PYTHONPATH=PCT/src python3 -m pct_baseline.cli prepare-data --spec PCT/configs/data_b1_v1.json --output PCT/outputs/PCT_P1_A_20261114_01/data','exit_code':0,'scope':'stdlib Python3.9; 22 tasks/428 items, full_schema NOT_RUN; exclusive new directory'},
        {'command':'which -a python3 python3.12 python3.13','exit_code':0,'stdout':'/usr/bin/python3\n'},
        {'command':'rg --files -g pyvenv.cfg -g "python3*" . "$USER_LOCAL" "$USER_CACHE"','scope':'limited discovery; located existing codex runtime Python3.12; initial nonexistent glob / zsh command error retained in notes, no machine-wide claim'},
        {'command':'"$PCT_PY" PCT/scripts/verify_p1a.py --output PCT/outputs/PCT_P1_A_20261114_01/verification_final','exit_code':0,'scope':'logs include two expected missing-dependency exits and five NOT_RUN integration skips; no aggregate acceptance PASS'}]
    put('commands_and_results',commands)
    parent_files={}
    protected=[]
    for package in ['PCT_P0_CONTRACT_20261114_01','PCT_P0_QA_20261114_01']:
        root=ROOT/'PCT/outputs'/package;manifest=read(root/'delivery_manifest.json')
        entries=manifest.get('sha256',{}) if 'sha256' in manifest else {row['path']:row['sha256'] for row in manifest['files']}
        for path,expected in entries.items():
            if path.startswith('PCT/outputs/'):
                protected.append({'path':path,'unchanged':sha(ROOT/path)==expected})
        parent_files[str((root/'delivery_manifest.json').relative_to(ROOT))]=sha(root/'delivery_manifest.json')
    assert all(row['unchanged'] for row in protected)
    ast_rows=[]
    for path in list((ROOT/'PCT/src').rglob('*.py'))+list((ROOT/'PCT/tests').glob('*.py'))+list((ROOT/'PCT/scripts').glob('*.py'))+[ROOT/p for p in modified]:
        ast.parse(path.read_text(),filename=str(path.relative_to(ROOT)));ast_rows.append(str(path.relative_to(ROOT)))
    put('final_checks',{'ast':'PASS','python':sys.version,'paths':ast_rows,'frozen_p0_qa_outputs':protected,
        'p0_qa_original_conclusion':'CONDITIONAL unchanged','integration':'NOT_RUN','side_effects':'No business dispatch; seal only writes new delivery files'})
    source_paths=list((ROOT/'PCT/src').rglob('*.py'))+list((ROOT/'PCT/src').rglob('*.schema.json'))+list((ROOT/'PCT/tests').glob('*.py'))+list((ROOT/'PCT/scripts').glob('*.py'))+list((ROOT/'PCT/configs').glob('*.json'))+[ROOT/'PCT/pyproject.toml']+[ROOT/p for p in modified]
    put('identity',{'version':'pct_p1a_identity_v1','branch':'dev/PCT','head':'2e4edb3215100f862a9e5c46fc03324ed1f41cb8','initial_worktree':'?? PCT/','initial_staged':'EMPTY',
        'third_party_head':'5e7b4238b18310af4529e0f85157d17de605850c','third_party_worktree':'EMPTY',
        'source_configuration_schema_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(source_paths))},
        'parent_delivery_manifest_sha256':parent_files,'derived_dataset_identity':read(OUT/'data/dataset.json')['data_identity'],
        'parent_data_identities':[p['data_identity'] for p in read(OUT/'data/dataset.json')['parents']],
        'environment':read(OUT/'verification_final/environment.json'),'algorithm':'Existing pct_exact_pose_network_v3 only named in execution spec; no LP/import/run','model':'NOT_IMPLEMENTED_NOT_RUN',
        'formal_runtime_identity':'NOT_FROZEN: dependencies absent; this source delivery identity does not admit execution or historical restore'})
    put('handoff',{'version':'pct_p1a_handoff_v1','unit':'P1-A B10-B12','status':'PARTIAL','stopped':True,'recipient':'independent quality review window',
        'authorization':'User appended full P1-A integration and exact public file scope; old P0 QA CONDITIONAL is retained',
        'report':'PCT/docs/PCT_P1A集成与验收_20261114_01.md','acceptance':REL+'/acceptance.json','manifest':REL+'/delivery_manifest.json',
        'implemented_entrypoints':['pct_baseline.cli prepare-data','pct_baseline.cli validate-data [--full-schema]','pct_baseline.protocol','five independent schemas','public shared facts/context routes'],
        'evidence':'13 local tests PASS / 5 integration NOT_RUN; 22 tasks 428 items derived; legacy resource byte protection PASS',
        'next_action':'Independent QA of this delivery. Full B10-B12 cannot close until explicitly authorized minimal environment preparation and the five constructed integration tests/full-schema complete.',
        'no_next_stage_admission':True,'P1_B':'NOT_STARTED','requests_authorized':0,'credential_reads':0})
    paths=[p for p in OUT.rglob('*') if p.is_file() and p.name!='delivery_manifest.json']
    paths+=source_paths+[ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md',ROOT/'PCT/docs/PCT_P1A集成与验收_20261114_01.md']
    put('delivery_manifest',{'version':'pct_p1a_delivery_manifest_v1','self_excluded':True,'scope':'New P1-A package/source/tests/config/schema/report/navigation and five authorized public sources. Excludes __pycache__; no self-hash cycle; original P0/QA outputs unchanged',
        'files':[{'path':str(p.relative_to(ROOT)),'size':p.stat().st_size,'sha256':sha(p)} for p in sorted(set(paths)) if '__pycache__' not in p.parts]})


if __name__=='__main__':main()
