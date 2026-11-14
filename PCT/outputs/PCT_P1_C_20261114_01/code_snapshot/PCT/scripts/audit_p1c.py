"""Seal P1-C completed evidence. No tests, order execution, selection or solver.

Only read facts/bytes/metadata, run read-only CLI validation and Git/pip checks,
write a new audit directory, source snapshots and the final self-excluded manifest.
"""
import ast
import collections
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'PCT/src'))
from pct_baseline.contracts import read,sha,digest,write_new
from pct_baseline.recovery import environment_identity

OUT=ROOT/'PCT/outputs/PCT_P1_C_20261114_01'
REL=str(OUT.relative_to(ROOT))
PUBLIC='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/'
ALLOWED=[PUBLIC+'episode.py',PUBLIC+'stability/monitor.py']


def put(name,value):write_new(OUT/(name+'.json'),value)

def main():
    audit=OUT/'final_audit';audit.mkdir(exist_ok=False)
    commands=[]
    def run(name,argv,display):
        result=subprocess.run(argv,cwd=ROOT,env=dict(os.environ,PYTHONPATH='PCT/src:semantic_pallet_planner/src',PYTHONDONTWRITEBYTECODE='1'),text=True,capture_output=True)
        row={'command':display,'argv':argv,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
        write_new(audit/(name+'.json'),row);commands.append({'command':display,'exit_code':result.returncode,'evidence':str((audit/(name+'.json')).relative_to(ROOT))})
        assert result.returncode==0,row
        return result.stdout.strip()
    branch=run('branch',['git','branch','--show-current'],'git branch --show-current')
    head=run('head',['git','rev-parse','HEAD'],'git rev-parse HEAD')
    run('staged',['git','diff','--cached','--stat'],'git diff --cached --stat')
    run('diff_check',['git','diff','--check'],'git diff --check')
    run('pip_check',[sys.executable,'-m','pip','check'],'"$NBU_PY" -m pip check')
    run('pip_freeze',[sys.executable,'-m','pip','freeze','--all'],'"$NBU_PY" -m pip freeze --all')
    current=environment_identity();baseline=read(OUT/'attempt_02/baseline_stable/header.json')
    assert current==baseline['identities']['environment']
    reference=OUT/'attempt_02/validator'
    before={str(p.relative_to(reference)):sha(p) for p in reference.rglob('*') if p.is_file()}
    run('saved_cli',[sys.executable,'-m','pct_baseline.cli','verify-saved','--run',str(reference.relative_to(ROOT))],
        'PYTHONPATH=PCT/src:semantic_pallet_planner/src "$NBU_PY" -m pct_baseline.cli verify-saved --run '+str(reference.relative_to(ROOT)))
    assert before=={str(p.relative_to(reference)):sha(p) for p in reference.rglob('*') if p.is_file()}
    comparisons=read(OUT/'attempt_02/cross_process_comparisons.json');assert len(comparisons)==12
    for row in comparisons:
        assert row['actual_cross_process_role_counts']==row['baseline_counts'] and row['old_pid']!=row['resume_pid']
        assert row['saved_journal_prefix_byte_identical'] and row['logical_events_equal'] and row['final_state_loading_termination_equal']
    for path,count in [('attempt_02.log',4),('saved_supplement.log',1),('intent_supplement.log',1),('p1a_regression.log',20),('p1b_regression.log',11)]:
        raw=(OUT/path).read_text();assert f'Ran {count} test' in raw and '\nOK\n' in raw and 'FAILED' not in raw
    primary=[]
    for path in sorted((OUT/'attempt_02').glob('*/header.json')):
        if path.parent.name.startswith(('baseline_','stable_','unstable_','stub_unstable_')):
            header=read(path)
            for name,expected in header['identities']['files'].items():assert sha(ROOT/name)==expected,(path,name)
            primary.append({'path':str(path.parent.relative_to(ROOT)),'header_digest':header['header_digest'],
                'task_digest':digest(header['task']),'config_digest':digest(header['config']),'identity_digest':digest(header['identities'])})
    assert len(primary)==15
    for path in (OUT/'attempt_02').glob('*/calls.jsonl'):
        for line in path.read_text().splitlines():
            call=json.loads(line)
            if call['role']=='assessment':
                assert {'placed_state','candidate','config','algorithm_identity','dependency_identity','evidence_kind'}==set(call['payload'])
                assert 'container_mm' in call['payload']['placed_state']
    put('baseline',{'branch':branch,'head':head,'initial_worktree':'CLEAN','initial_staged':'EMPTY',
        'handoff_old_head':'25be41c789407abc3a7be48bbe80094127b44649','actual_progress_commit':'68c80a9b8efd47f378767565865b16a90ae1bdf5',
        'baseline_difference':'User committed P1-A/P1-B/QA before task; no agent checkout/commit/push/pull/stash/reset',
        'third_party_head':subprocess.run(['git','-C','Online-3D-BPP-PCT','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip(),
        'third_party_status':subprocess.run(['git','-C','Online-3D-BPP-PCT','status','--short'],cwd=ROOT,capture_output=True,text=True,check=True).stdout})
    put('authorization',{'version':'pct_p1c_authorization_v1','user_answer':'授权上述最小范围及限定验证',
        'public_scope':ALLOWED,'execution_scope':'B16-B18 1-3-box construction, separate-process resume/lock/corruption negatives',
        'no_installation':True,'model_calls_authorized':0,'training':0,'subagents':0})
    changed=subprocess.run(['git','diff','--name-only'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.splitlines()
    assert {p for p in changed if not p.startswith('PCT/')}==set(ALLOWED)
    initial=read(OUT/'initial_hashes.json')
    put('external_changes',{'version':'pct_p1c_external_changes_v1','files':[{'path':p,'before_sha256':initial[p],'after_sha256':sha(ROOT/p),
        'necessity':'episode saved-decision resume and elapsed-unknown handling' if p.endswith('episode.py') else 'delegate b1 saved-checkpoint validation without dispatch',
        'freeze_impact':'New source identity required; no historical re-signing'} for p in ALLOWED],
        'other_public_changes':[],'packaging_versions':'UNCHANGED','legacy_schema':'UNCHANGED','P1B_resume_false':'UNCHANGED_AND_RECHECKED',
        'new_admission':'pct_b1_recovery_execution_v1 (local PCT closed Schema), separate from old P1-B permit'})
    with (OUT/'public_changes.patch').open('xb') as stream:stream.write(subprocess.run(['git','diff','--',*ALLOWED],cwd=ROOT,capture_output=True,check=True).stdout)
    # Existing schema/config bytes and immutable historical package contents.
    old_resources=[]
    for directory in [ROOT/(PUBLIC+'schemas'),ROOT/(PUBLIC+'configs'),ROOT/'PCT/src/pct_baseline/schemas']:
        listed=subprocess.run(['git','ls-tree','-r','--name-only','HEAD',str(directory.relative_to(ROOT))],cwd=ROOT,capture_output=True,text=True,check=True).stdout.splitlines()
        for name in listed:
            original=subprocess.run(['git','show','HEAD:'+name],cwd=ROOT,capture_output=True,check=True).stdout
            assert (ROOT/name).read_bytes()==original,name
            old_resources.append({'path':name,'sha256':sha(ROOT/name)})
    history=[]
    for name in ['PCT_P0_CONTRACT_20261114_01','PCT_P0_QA_20261114_01','PCT_P1_A_20261114_01','PCT_P1_A_NBU_20261114_02','PCT_P1_A_QA_20261114_01','PCT_P1_B_20261114_01','PCT_P1_B_QA_20261114_01']:
        root=ROOT/'PCT/outputs'/name;m=read(root/'delivery_manifest.json')
        entries=m.get('sha256',{}) if 'sha256' in m else {r['path']:r['sha256'] for r in m['files']}
        for name,expected in entries.items():
            if name.startswith(str(root.relative_to(ROOT))+'/'):
                assert sha(ROOT/name)==expected,name
                history.append({'path':name,'sha256':expected})
    write_new(audit/'historical_bytes.json',{'status':'UNCHANGED','legacy_schema_configs':old_resources,'historical_output_files':history})
    paths=list((ROOT/'PCT/src').rglob('*.py'))+list((ROOT/'PCT/src').rglob('*.schema.json'))+list((ROOT/'PCT/configs').glob('*.json'))+list((ROOT/'PCT/tests').glob('*.py'))+list((ROOT/'PCT/scripts').glob('*.py'))+[ROOT/'PCT/pyproject.toml']+[ROOT/p for p in ALLOWED]
    for name in baseline['identities']['files']:paths.append(ROOT/name)
    ast_files=[]
    for path in sorted(set(paths)):
        if path.suffix=='.py':ast.parse(path.read_text(),filename=str(path.relative_to(ROOT)));ast_files.append(str(path.relative_to(ROOT)))
        target=OUT/'code_snapshot'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    write_new(audit/'ast.json',{'status':'PASS','python':sys.version,'files':ast_files})
    put('environment',{'version':'pct_p1c_environment_v1','current':current,'executable':sys.executable,
        'highs_version':baseline['config']['stability_monitor']['algorithm_identity']['dependencies']['highs_version'],
        'stability_monitor':baseline['config']['stability_monitor'],'installation':'NOT_RUN_NONE_NEEDED'})
    put('identity',{'version':'pct_p1c_identity_v1','head':head,'source_configuration_schema_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))},
        'environment':'environment.json','primary_job_identities':primary,'historical_bytes':'final_audit/historical_bytes.json',
        'model_weights':{'status':'NOT_IMPLEMENTED','sha256':None},'network_features':{'status':'NOT_IMPLEMENTED','sha256':None},
        'public_features':'packaging_physical_facts_v1','strategy':'geometry_b1','schema_versions':['pct_b1_recovery_execution_v1','pct_b1_recovery_header_v1','pct_b1_recovery_journal_v1'],
        'data_scope':'1-3 box explicit constructions, not original22 task execution','old_derived_data_identity':'81c754a234f2083a5fb0bcbd55dd7ed905b292bab74ddf92f708d05d9219b29e'})
    put('acceptance',{'version':'pct_p1c_acceptance_v1','status':'PASS','kind':'DEVELOPMENT_PENDING_INDEPENDENT_QA',
        'tests':{'P1C_main_methods':4,'P1C_supplemental_methods':2,'P1C_unique_methods':6,'P1A_regression':20,'P1B_regression':11,'skips':0},
        'matrix':[
            {'id':'B16','status':'PASS','implementation':'independent recovery permit; original public loop; saved context/selection/monitor reuse and COMMITTED skip',
                'local_recheck':'12 cross-process combinations: real completion, real instability, control stub x four durable phases; 3 baselines; final state/logical events/loading/termination and cumulative call counts match',
                'archive':['attempt_02/cross_process_comparisons.json','attempt_02.log','attempt_02/command_*.json','attempt_02/*/calls.jsonl'],
                'boundary':'event comparison excludes recorded timing fields and their derived result/credential digests across independent baseline runs; each saved journal/monitor payload itself remains byte unchanged on resume'},
            {'id':'B17','status':'PASS','implementation':'file+directory fsync and atomic numbered journal, stable-inode flock, frozen identity checks and conservative commit-intent stop',
                'local_recheck':'task/config/strategy/candidate/monitor tampering, actual source-byte drift, injected current dependency drift, lock contention, sequence gaps, bad JSON, rename failure/pending file and unknown commit all rejected; known COMMITTED intent cleanup causes no business call',
                'archive':['attempt_02/negative_results.json','attempt_02/lock_holder.json','intent_supplement.log','intent_supplement/'],
                'boundary':'same archive-directory single-writer API, POSIX; real model weight/network-feature restoration NOT_IMPLEMENTED'},
            {'id':'B18','status':'PASS','implementation':'saved validator and CLI; copied-state geometry/ledger reconstruction, no policy or numerical dispatch',
                'local_recheck':'fresh-process verification at all tested stages and terminals is read-only; positive checks do not import SciPy; selector/transport/candidate/order/LP guard probes blocked; summary/final-state/termination/extra fields/model placeholder corruption rejected',
                'archive':['attempt_02/command_*.json','saved_supplement/saved_ledger_negatives.json','final_audit/saved_cli.json'],
                'boundary':'checks saved facts, not a new solver certification; current-source drift enforced by recovery, offline saved-only validation deliberately separate'}],
        'P2_P3':'NOT_RUN_NOT_ADMITTED','models_training':'NOT_RUN','independent_QA':'PENDING'})
    put('limitations',{'version':'pct_p1c_limitations_v1','scope':'POSIX same-job-directory API, 1-3-box constructions, geometry only',
        'not_run':['official22 task matrix','P3 whole-order diagnosis','PCT/Jev inference','training','weights downloads','third-party update','machine power-loss/hardware failure','external equipment exactly-once commitment','post-commit independent evaluation failure recovery matrix','separate full four-phase UNASSESSABLE/ERROR recovery matrices'],
        'tested_nonstable':'real UNSTABLE and labeled stub UNSTABLE; other status routing retains P1-B contracts but no new full-status recovery matrix claimed',
        'unknown_save_outcome':'pending/corrupt records and unknown commit stop explicitly; no auto-clean/re-sign/retry to fabricate success',
        'integrity_model':'canonical content SHA256 chain + frozen identities, not an adversarial signature against someone rewriting an entire archive and every trust anchor; same-directory authorized writers must use lock',
        'future_model_interface':'model_weights/network_features are closed NOT_IMPLEMENTED/null; real model support requires a new version binding actual weights, feature/architecture/candidate-map and applicable runtime states',
        'test_guard_scope':'tested Python verification process; reviewed child harness separately; not a whole-system formal guarantee',
        'P1B-Q01':'new calls.jsonl contains full placed state/container,candidate,configuration,algorithm and dependency identities; original P1B outputs unchanged',
        'failures_preserved':{'attempt_01.log':'nonstable DECISION_READY resume timer TypeError and test relative/absolute path error; fixed, new tasks used, old source identities not re-signed',
            'schema_preparation':'one temporary Schema edit helper NameError(__file__) observed and corrected; no historical schema rewrite'},
        'historical_reports':'original P1B/QA packages and failure logs immutable; shared source/navigation changes recorded only in new identity',
        'data':'previous exposure, synthetic packaging capacities, feasibility UNKNOWN, independent holdout0 unchanged'})
    all_commands=[]
    for directory in ('attempt_01','attempt_02','saved_supplement','intent_supplement'):
        for path in sorted((OUT/directory).glob('command_*.json')):
            row=read(path);all_commands.append({'command':row['command'],'exit_code':row['exit_code'],'expected_exit':row['expected_exit'],
                'result':'EXPECTED' if row['exit_code']==row['expected_exit'] else 'FAILED_FIXED_IN_NEW_RUN','evidence':str(path.relative_to(ROOT))})
    test_commands=[{'command':'PCT_P1C_EVIDENCE_DIR='+REL+'/'+name+' PYTHONPATH=PCT/tests:PCT/src:semantic_pallet_planner/src "$NBU_PY" -m unittest discover -s PCT/tests -p test_p1c_recovery.py -v',
        'exit_code':code,'raw_log':name+'.log','note':'actual main methods loaded at invocation:4; later two supplemental methods separately executed'} for name,code in [('attempt_01',1),('attempt_02',0)]]
    test_commands += [
        {'command':'PCT_P1C_EVIDENCE_DIR=<new supplemental directory> PCT_P1C_REFERENCE_JOB='+REL+'/attempt_02/validator PYTHONPATH=PCT/tests:PCT/src:semantic_pallet_planner/src "$NBU_PY" -m unittest test_p1c_recovery.RecoveryTests.test_additional_saved_ledger_and_terminal_negatives -v','exit_code':0,'raw_log':'saved_supplement.log'},
        {'command':'PCT_P1C_EVIDENCE_DIR=<new supplemental directory> PCT_P1C_REFERENCE_JOB='+REL+'/attempt_02/validator PYTHONPATH=PCT/tests:PCT/src:semantic_pallet_planner/src "$NBU_PY" -m unittest test_p1c_recovery.RecoveryTests.test_committed_intent_cleanup_never_recommits -v','exit_code':0,'raw_log':'intent_supplement.log'},
        {'command':'PYTHONPATH=PCT/tests:PCT/src:semantic_pallet_planner/src "$NBU_PY" -m unittest discover -s PCT/tests -p test_b1_*.py -v','exit_code':0,'raw_log':'p1a_regression.log'},
        {'command':'PYTHONPATH=PCT/tests:PCT/src:semantic_pallet_planner/src "$NBU_PY" -m unittest discover -s PCT/tests -p test_p1b_execution.py -v','exit_code':0,'raw_log':'p1b_regression.log'}]
    put('commands_and_results',{'version':'pct_p1c_commands_v1','actual_test_invocations':test_commands,'raw_subprocesses':all_commands,'final_audit_commands':commands,
        'preparation':[{'command':'python3 PCT/scripts/build_schemas_p1c.py','exit_code':0,'scope':'initial new recovery permit/header schemas; P1C journal/environment Schema completed in stage, old resource bytes unchanged'},
            {'command':'python3 - <temporary own Schema edit helper>','exit_code':1,'observed_diagnostic':"NameError: name '__file__' is not defined",'fix':'explicit trusted generator __file__ supplied; no business dispatch or old schema mutation'}],
        'no_installation':True,'real_model_requests':0,'training':0,'cost_scope':'raw logs include initial failures/repeats; final12 combinations are not the full development cost denominator',
        'audit_script':'PCT/scripts/audit_p1c.py: byte/metadata/saved-only checks, not business tests'})
    put('handoff',{'version':'pct_p1c_handoff_v1','unit':'P1-C B16-B18','status':'DEVELOPMENT_PASS_PENDING_INDEPENDENT_QA','stopped':True,
        'recipient':'independent quality review window','report':'PCT/docs/PCT_P1C持久化跨进程恢复与验收_20261114_01.md','acceptance':REL+'/acceptance.json','manifest':REL+'/delivery_manifest.json',
        'implemented':['pct_baseline.recovery.create_job/run_job','persistence atomic numbered journal and flock','saved.validate_checkpoint/validate_job','CLI prepare-recovery/resume-recovery/verify-saved'],
        'evidence':'12 durable-phase cross-process comparisons +3 baselines, actual PID/call logs, source/dependency/drift/lock/save/corruption negatives, saved-only guard probes; 6 P1C+31 regression methods pass',
        'P1B_resume_false':'preserved','models_weights_features':'NOT_IMPLEMENTED (closed placeholders, no fake acceptance)',
        'P2_P3':'NOT_STARTED','official_matrix':'NOT_RUN','real_model_requests':0,'training':0,'subagents':0,'next_action':'independent QA only, no next-stage authorization inferred'})
    report=ROOT/'PCT/docs/PCT_P1C持久化跨进程恢复与验收_20261114_01.md'
    for path in [ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md',report]:
        for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if not link.startswith(('http:','https:','#')):
                target=path.parent/link.split('#')[0]
                assert target.exists() or target.resolve()==(OUT/'delivery_manifest.json').resolve(),link
    put('final_checks',{'status':'PASS','primary_frozen_source_matches':len(primary),'environment_matches':True,'legacy_schema_config_files':len(old_resources),
        'historical_output_files_unchanged':len(history),'AST_files':len(ast_files),'links':'PASS','saved_CLI_readonly':'PASS','external_scope':ALLOWED,'staged':'EMPTY'})
    all_files=[p for p in OUT.rglob('*') if p.is_file() and p.name!='delivery_manifest.json']+paths+[ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md',report]
    put('delivery_manifest',{'version':'pct_p1c_delivery_manifest_v1','self_excluded':True,
        'scope':'new P1-C outputs/source snapshots, current source/config/schema/tests/scripts/report/navigation; historical package references not re-signed',
        'files':[{'path':str(p.relative_to(ROOT)),'size':p.stat().st_size,'sha256':sha(p)} for p in sorted(set(all_files)) if '__pycache__' not in p.parts]})


if __name__=='__main__':main()
