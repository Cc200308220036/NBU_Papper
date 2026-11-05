import copy
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from semantic_pallet_planner.config import WORKSPACE
from semantic_pallet_planner.o4.common import O4Error,read,write,digest
from semantic_pallet_planner.o4.extensions.e2.experiment import verify_seal,seal
from semantic_pallet_planner.o4.extensions.e5.experiment import prepare,validate_plan,offline_run,online_jobs
from semantic_pallet_planner.o4.extensions.e5.online import remote_run,prepare_remote


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    root=tmp_path_factory.mktemp('e5delivery')/'plan'
    protection=WORKSPACE/'report/analysis/O4_E5_DEVELOPMENT_20261026_01/protected.before.json'
    prepare(root,protection);return root


def test_plan_full_denominators_frozen_source_and_no_overwrite(prepared):
    plan,data,cfg=validate_plan(prepared)
    assert len(plan['jobs'])==240 and len(data['tasks'])==24 and len(data['constructs'])==6
    jobs=online_jobs(data)
    assert len(jobs)==240 and sum(j['attempt_limit'] for j in jobs)==3100
    assert len({j['job_id'] for j in jobs})==240
    assert {j['task_id'] for j in jobs[:20]}=={'E5_SRC00_C0','E5_SRC01_C1'}
    env=dict(os.environ,PYTHONPATH=str(prepared/'code_snapshot/semantic_pallet_planner/src'))
    code=('from semantic_pallet_planner.o4.common import read; '
          'from semantic_pallet_planner.o4.extensions.e5.validation import run; '
          f'd=read({str(prepared/"private/input_snapshot.json")!r}); '
          'rows,bad,pairs=run(d["regression_inputs"]); '
          'assert len(rows)==180 and len(bad)==48 and all(r["passed"] for r in rows+bad); print("frozen regression PASS")')
    output=subprocess.run([sys.executable,'-P','-c',code],env=env,capture_output=True,text=True,check=True)
    assert 'frozen regression PASS' in output.stdout
    with pytest.raises(O4Error):prepare(prepared,WORKSPACE/'report/analysis/O4_E5_DEVELOPMENT_20261026_01/protected.before.json')


def test_offline_bounded_run_and_real_checkpoint_continuation(prepared,tmp_path):
    root=tmp_path/'experiment'
    a=offline_run(prepared,root,max_jobs=1)
    assert a['status']=='PARTIAL' and a['recorded_jobs']==1 and not(root/'delivery_manifest.json').exists()
    first=next((root/'episodes').glob('*.json'));before=first.read_bytes()
    b=offline_run(prepared,root,resume=True,max_jobs=1)
    assert b['status']=='PARTIAL' and b['recorded_jobs']==2 and first.read_bytes()==before
    jobs=read(root/'audit/jobs.json');assert len(jobs)==240 and sum(j['status']=='NOT_RUN' for j in jobs)==238


def test_plan_tamper_detected(prepared,tmp_path):
    import shutil
    root=tmp_path/'copy';shutil.copytree(prepared,root)
    p=read(root/'plan.json');p['jobs'].pop();write(root/'plan.json',p)
    with pytest.raises(O4Error,match='sealed_artifact_changed'):verify_seal(root)


def test_real_flag_required_before_read_or_network(tmp_path):
    with pytest.raises(O4Error,match='remote_explicit_flag_required'):remote_run(tmp_path/'absent',tmp_path/'out',3100)
    assert not(tmp_path/'out').exists()


def test_forged_pass_without_execution_evidence_is_not_sufficient(prepared,tmp_path):
    root=tmp_path/'forged';root.mkdir()
    write(root/'acceptance_report.json',{'offline_status':'PASS'})
    write(root/'manifest.json',{'plan_delivery_digest':digest(read(prepared/'delivery_manifest.json'))})
    seal(root)
    with pytest.raises((O4Error,FileNotFoundError)):
        prepare_remote(prepared,root,WORKSPACE/'semantic_pallet_planner/configs/o4_d_deepseek_flash.yaml',tmp_path/'online')
    assert not(tmp_path/'online').exists()


def test_offline_initialization_failure_has_error_and_unexecuted_denominator(prepared,tmp_path,monkeypatch):
    from semantic_pallet_planner.o4.extensions.e5 import experiment
    def fail_initialize(*args,**kwargs):raise O4Error('injected_snapshot_copy_failure')
    monkeypatch.setattr(experiment,'initialize',fail_initialize)
    output=tmp_path/'failed_initialization'
    with pytest.raises(O4Error,match='injected_snapshot_copy_failure'):
        offline_run(prepared,output)
    report=read(output/'acceptance_report.json')
    assert report['operation']=='offline-run' and report['status']=='FAIL'
    assert report['not_run_jobs']==240 and report['recorded_episodes']==0 and report['new_api_attempts']==0
    assert read(output/'audit/initialization_error.json')['error_code']=='injected_snapshot_copy_failure'


def test_fake_online_scheduler_budget_resume_and_raw_http_verifier(prepared,tmp_path,monkeypatch):
    """Explicitly marked test-only plan; no claim of offline acceptance/real API."""
    import hashlib
    import io
    from semantic_pallet_planner.o4.remote.transport import ModelConfig,ChatTransport
    from semantic_pallet_planner.o4.extensions.e2.visual import FONT
    from semantic_pallet_planner.o4.extensions.e2.remote import prompt
    from semantic_pallet_planner.o4.extensions.e2.compiler import compile_policy
    from semantic_pallet_planner.o4.extensions.e2.experiment import files
    from semantic_pallet_planner.o4.extensions.e5.experiment import PACKAGE
    from semantic_pallet_planner.o4.extensions.e5.online import ONLINE_VERSION,verify_online
    _,data,config=validate_plan(prepared)
    planroot=tmp_path/'online_fixture';planroot.mkdir();model=ModelConfig(endpoint='https://offline.invalid/chat/completions',model='test-double',api_key_env='E5_SCHEDULER_TEST_KEY')
    write(planroot/'private/input_snapshot.json',data);write(planroot/'config.snapshot.json',config);write(planroot/'model.snapshot.json',model.snapshot());(planroot/'prompt.txt').write_text(prompt())
    jobs=online_jobs(data)
    write(planroot/'plan.json',{'version':ONLINE_VERSION,'test_fixture_only':True,'jobs':jobs,'maximum_api_attempts':3100,
          'data_digest':digest(data),'config_digest':digest(config),'model_digest':digest(model.snapshot()),
          'source_files':files(PACKAGE),'font_sha256':hashlib.sha256(Path(FONT).read_bytes()).hexdigest()})
    seal(planroot)
    with pytest.raises(O4Error,match='test_fixture_requires'):remote_run(planroot,tmp_path/'forbidden',3100,remote=True)
    monkeypatch.setenv('E5_SCHEDULER_TEST_KEY','offline-test-only');bodies=[]
    def opener(req,timeout):
        b=json.loads(req.data);bodies.append(b)
        q=json.loads(b['messages'][1]['content'][0]['text'])['public_input']['public_request']
        payload={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(compile_policy(q))}}],'usage':{'total_tokens':1}}
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        return Response(json.dumps(payload).encode())
    transport=ChatTransport(model,opener=opener,test_double=True);output=tmp_path/'real_encoding_test'
    a=remote_run(planroot,output,3100,remote=True,max_jobs=2,transport=transport)
    assert a['status']=='PARTIAL' and a['recorded_episodes']==2 and a['real_api_attempts']==0 and a['test_double']
    first_count=len(bodies)
    b=remote_run(planroot,output,3100,remote=True,resume=True,max_jobs=1,transport=transport)
    assert b['recorded_episodes']==3 and len(bodies)>first_count and b['real_online_status']=='NOT_RUN'
    verified=verify_online(output)
    assert verified['episode_records_recomputed']==3 and verified['http_attempts_verified']==len(bodies)
    ledger=read(output/'audit/ledger.json');assert ledger['budget']==3100 and len(ledger['attempts'])==len(bodies)
