"""Seal only this P2-A development delivery. Does not run business/network work."""
from pathlib import Path
import ast
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'PCT/outputs/PCT_P2_A_20261114_01'
REPORT = ROOT/'PCT/docs/PCT_P2A网络副本与数值验收_20261114_01.md'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name, value):
    (OUT/name).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def main():
    summary=json.loads((OUT/'numerical_summary.json').read_text())
    assert summary['status']=='PASS'
    checks=json.loads((OUT/'environment_install_check.json').read_text())
    assert checks['existing_versions_unchanged']
    reg=json.loads((OUT/'compatibility_register.json').read_text())
    for row in reg['items']:
        if row['status'] in ['NUMERICAL_CHECK_PENDING','IMPLEMENTED_PENDING_RUNTIME']:
            row['status']='PASS_LIMITED_FIXTURES'
            row['evidence']=['numerical_summary.json','numerical_comparisons.json','padding_differences.json','compatibility_negatives.json','key_diagnostics.json']
    save('compatibility_register.json',reg)
    save('acceptance.json',{
        'version':'pct_p2a_acceptance_v1','status':'DEVELOPMENT_PASS_PENDING_INDEPENDENT_QA',
        'matrix':[
            {'id':'B20','status':'PASS','scope':'fixed-source MIT minimal copy; source/destination SHA; per-patch reason, behavior and test evidence',
             'evidence':['PCT/src/pct_baseline/vendor/pct/upstream_manifest.json','PCT/src/pct_baseline/vendor/pct/LICENSE','patch_register.json','reference_python312.patch','static_checks.json']},
            {'id':'B21','status':'PASS','scope':'CPU float32 frozen single-layer structure; all-valid B1/B3; identical weights/input; probability/value/fixed-action logprob and every parameter gradient; 4 flag combinations; process-isolated native reference',
             'evidence':['numerical_summary.json','numerical_comparisons.json','key_diagnostics.json','weight_identity.json','weight_tensors.json','commands_and_results.json','*_input.json','*_results.json'],
             'compat_all_valid_max_absolute_error':0.0,'atol':1e-6,'rtol':1e-5},
            {'id':'B22','status':'PASS','scope':'enumerated compatibility issues patched/tested or explicitly registered; environment execution and paper performance NOT_RUN',
             'evidence':['compatibility_register.json','compatibility_negatives.json','padding_differences.json','evaluation_syntax.patch','attempt_01/']}],
        'independent_QA':'PENDING','remote_requests':0,'training_updates':0,'P2B_P2C_P3':'NOT_RUN_NOT_AUTHORIZED'})
    save('limitations.json',{
        'scope':'pure-network fixtures only; CPU float32 Torch2.15.0 Python3.12.16; single graph layer and head',
        'native_reference':'minimal Python3.12 tuple compatibility patch; exact tools AST extraction; original raw bytes preserved; not full native environment',
        'weights':'RANDOM_INITIALIZATION_ENGINEERING_ONLY; no optimizer or training',
        'native_paper_performance':'NOT_RUN','orders_candidates_LP':'NOT_RUN','candidate_encoding_model_selection_and_recovery':'NOT_IMPLEMENTED_IN_P2A',
        'P2B_P2C_P3':'NOT_RUN_NOT_AUTHORIZED','weight_download':'NOT_RUN','remote_requests_authorized':0,'remote_requests':0,
        'environment':'new dependencies change future frozen identity; no old identity or seal re-signed',
        'global_mutation':'native reference mutates distribution classes only within subprocess; compat/safe unchanged',
        'padding':'safe behavior differs from native; separately archived; no new glimpse aggregation',
        'multiple_graph_layers':'upstream loses evaluate field; outside frozen one-layer scope, not patched',
        'P1C_Q01':'OPEN; clarify session reuse before P3 costs; no historical event modification',
        'data':'existing exposed sources, synthetic packaging, satisfiability UNKNOWN, independent holdout sources 0',
        'git_binary_ignore':'Existing rules ignore .pt. Binary copies kept locally; complete JSON inputs, weights and outputs/gradients are included without changing ignore rules.',
        'interim_static':'retained mid-stage declarations; old interim manifest describes then-current shared paths and is not re-certified against final paths'})
    save('operations.json',{
        'scope':'P2-A only','interpreter_alias':'NBU_PY; exact identity environment.json',
        'operations':[
            {'command':'<NBU_PY> -m pip install --dry-run --report <P2A>/torch_install_plan.json torch','exit_code':1,'reason':'sandbox proxy network denied; pip default connection retries; no installation'},
            {'command':'<NBU_PY> -m pip install --dry-run --retries 0 --report <P2A>/torch_install_plan.json torch','exit_code':0,'sandbox':'escalated','evidence':'torch_install_plan.json'},
            {'command':'<NBU_PY> -m pip install --retries 0 --report <P2A>/torch_install_actual.json -r <P2A>/torch_install_requirements.txt','exit_code':0,'evidence':'torch_install.log'},
            {'command':'PYTHONPATH=PCT/src PYTHONDONTWRITEBYTECODE=1 <NBU_PY> PCT/scripts/verify_p2a.py','exit_code':1,'evidence':'attempt_01/numerical_run.log','reason':'NamedTuple Python3.12 class construction; no weights generated'},
            {'command':'PYTHONPATH=PCT/src PYTHONDONTWRITEBYTECODE=1 <NBU_PY> PCT/scripts/verify_p2a.py','exit_code':0,'evidence':['numerical_run.log','commands_and_results.json'],'result':'22 successful fresh processes; original import failure remains separate'},
            {'command':'PYTHONDONTWRITEBYTECODE=1 python3 PCT/scripts/verify_p2a.py --static-only','exit_code':0,'evidence':'static_checks.json'},
            {'command':'PYTHONPATH=PCT/src PYTHONDONTWRITEBYTECODE=1 <NBU_PY> PCT/scripts/verify_p2a.py --output PCT/outputs/PCT_P2_A_20261114_01/harness_static_probe --static-only','exit_code':0,'result':'new-directory source preparation and static checks'},
            {'command':'PYTHONPATH=PCT/src PYTHONDONTWRITEBYTECODE=1 <NBU_PY> PCT/scripts/verify_p2a.py','exit_code':1,'expected':True,'reason':'archive overwrite rejected before numerical work','evidence':'archive_overwrite_rejection.log'},
            {'command':'<NBU_PY> complete JSON weight export and float32 round-trip equality check','exit_code':0,'evidence':'weight_tensors.json'},
            {'command':'git diff --check','exit_code':0}],
        'no_remote_models':True,'no_order_or_solver_execution':True,
        'executed_vs_delivered_verifier':'numerical_source_snapshot restores executed source by removing later guard/source-prepare block. Final source additionally exports full JSON weights. Later changes only archive preparation/export; AST and guard/source-prepare checks performed, numerical arithmetic unchanged.'})
    save('handoff.json',{
        'version':'pct_p2a_handoff_v1','status':'B20_B21_B22_DEVELOPMENT_PASS','independent_QA':'PENDING',
        'report':str(REPORT.relative_to(ROOT)),'manifest':'PCT/outputs/PCT_P2_A_20261114_01/delivery_manifest.json',
        'interfaces':{'compat':'pct_baseline.vendor.pct.model.DRL_GAT','explicit_padding_extension':'pct_baseline.network_safety.PaddingSafeDRLGAT','pure_network_verifier':'PCT/scripts/verify_p2a.py; use fresh output directory'},
        'evidence':'complete JSON and binary packed fixtures, random weights, outputs/gradients; separated native-compatible and safe-padding paths',
        'weights':'RANDOM_INITIALIZATION_ENGINEERING_ONLY','model_order_integration':'NOT_IMPLEMENTED',
        'P1C_Q01':'OPEN_NON_BLOCKING_FOR_P2A; clarify before P3 costs; preserve historical events/seals',
        'next_action':'independent P2-A quality review','next_stage_authorized':False,
        'stop':True,'next_task_prompt':'NOT_CREATED'})
    sources=[p for p in (ROOT/'PCT/src/pct_baseline/vendor').rglob('*') if p.is_file()]
    sources += [ROOT/p for p in ['PCT/src/pct_baseline/network_safety.py','PCT/tests/p2a_worker.py','PCT/scripts/verify_p2a.py','PCT/scripts/seal_p2a.py','PCT/configs/network_p2a_v1.json']]
    for p in sources:
        if p.suffix=='.py': ast.parse(p.read_text())
    source_map={str(p.relative_to(ROOT)):sha(p) for p in sources}
    save('identity.json',{
        'version':'pct_p2a_identity_v1','branch':'dev/PCT','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'upstream_commit':'5e7b4238b18310af4529e0f85157d17de605850c','source_sha256':source_map,
        'upstream_manifest':'PCT/src/pct_baseline/vendor/pct/upstream_manifest.json',
        'environment':'environment.json','compiled_dependency_and_RECORD_identity':'dependency_identity.json',
        'weights':'weight_identity.json','complete_weight_json_sha256':sha(OUT/'weight_tensors.json'),
        'runtime_reference_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (OUT/'reference_runtime').iterdir() if p.is_file()},
        'executed_numerical_source_snapshot':{str(p.relative_to(ROOT)):sha(p) for p in (OUT/'numerical_source_snapshot').iterdir() if p.is_file()},
        'no_data_or_monitor_changes':True})
    snapshot=OUT/'final_source_snapshot'
    for p in sources+[REPORT,ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md']:
        target=snapshot/p.relative_to(ROOT); target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(p.read_bytes())
    missing=[]
    for p in [REPORT,ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md']:
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if link.startswith(('http:','https:','#')): continue
            q=(p.parent/link.split('#')[0]).resolve()
            if not q.exists() and q!=OUT/'delivery_manifest.json': missing.append({'document':str(p.relative_to(ROOT)),'target':link})
    assert not missing,missing
    assert subprocess.run(['git','diff','--check'],cwd=ROOT).returncode==0
    assert not subprocess.check_output(['git','-C','Online-3D-BPP-PCT','status','--short'],cwd=ROOT,text=True)
    assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=ROOT,text=True)
    save('final_delivery_checks.json',{'local_links':'PASS','missing':missing,'source_ast':'PASS','git_diff_check':'PASS','upstream_worktree':'CLEAN','staging_area':'EMPTY','numerical_matrix_rerun_after_success':False,'full_weight_json_float32_roundtrip':'PASS'})
    all_files=[p for p in OUT.rglob('*') if p.is_file() and p!=OUT/'delivery_manifest.json']+sources+[REPORT,ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md']
    # No self hash, no manifest hash in any covered document/identity/handoff.
    save('delivery_manifest.json',{'version':'pct_p2a_manifest_v1','status':'FINAL_DEVELOPMENT_PENDING_QA','self_excluded':True,
        'scope':'Only new P2-A artifacts and current own source/report/navigation; prior P0/P1 archives not re-signed. Interim manifest is historical data only.',
        'files':[{'path':str(p.relative_to(ROOT)),'size':p.stat().st_size,'sha256':sha(p)} for p in sorted(set(all_files))]})
    m=json.loads((OUT/'delivery_manifest.json').read_text())
    for f in m['files']: assert sha(ROOT/f['path'])==f['sha256'],f['path']
    print(f"Final P2-A delivery sealed and verified: {len(m['files'])} files; B20-B22 development PASS, QA pending")


if __name__=='__main__': main()
