"""Preset/handoff checks, never real API calls."""
import copy
import json
import pytest
from semantic_pallet_planner.o5.common import read,offline_guard,O5Error
from semantic_pallet_planner.o5.remote_config import require_cost,gaps
from semantic_pallet_planner.o5.remote_transport import prepare_body
from semantic_pallet_planner.o5.remote_authorized import visual_body,authorization
from semantic_pallet_planner.o5.remote_experiment import prepare
from semantic_pallet_planner.runners import o5_deepseek as helper
from test_o5_s2_remote import decision


def test_preset_is_existing_model_no_monetary_gaps():
    p=require_cost(read(helper.PROFILE))
    assert not gaps(p)
    assert p['model']=='deepseek-flash' and p['credential_env']=='DEEPSEEK_API_KEY'
    assert p['limits']['preflight_attempts']==4 and p['limits']['pilot_attempts']==290
    assert p['amount_policy']=='unlimited' and p['pricing']['currency'] is None


def test_both_decision_and_probe_disable_thinking(decision,tmp_path):
    req,step,cfg=decision;p=read(helper.PROFILE)
    body,bound=prepare_body(req,step,cfg,p)
    assert body['thinking']=={'type':'disabled'} and body['response_format']=={'type':'json_object'}
    assert 'seed' not in body and body['max_tokens']==256 and bound['maximum_amount'] is None
    prepare(None,tmp_path/'plan',p,fixture=True,stage='preflight')
    task=read(tmp_path/'plan/plan.json')['preflight_tasks'][0]
    probe,b=visual_body(task,tmp_path/'plan',p)
    assert probe['thinking']==body['thinking'] and probe['response_format']==body['response_format']
    assert b['input_upper']==len(task['prompt'].encode())+512+2048


def test_handoff_prepares_and_derives_auth_without_credentials(tmp_path,monkeypatch):
    from semantic_pallet_planner.o5 import remote_experiment as ex
    from semantic_pallet_planner.o5.testing import fixture_task
    from semantic_pallet_planner.o5.common import atomic
    data=tmp_path/'data';(data/'private').mkdir(parents=True)
    tasks=[]
    for i in range(8):
        t=fixture_task();t['task_id']=f'development_{i+1:03d}';tasks.append(t)
    atomic(data/'private/development.json',tasks)
    monkeypatch.setattr(helper,'DATASET',data)
    monkeypatch.setattr(ex,'validate_dataset',lambda root:{'scope':'OFFLINE_HANDOFF_TEST'})
    paths={k:tmp_path/k for k in helper.paths('TEST')}
    monkeypatch.setattr(helper,'paths',lambda run_id:paths)
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    with offline_guard():result=helper.prepare_handoff('TEST')
    assert result['real_api_attempts']==0 and not paths['preflight_run'].exists()
    assert not paths['campaign'].exists()
    auth=authorization(read(paths['preflight_plan']/'plan.json'),paths['handoff']/'preflight_authorization.json','preflight')
    assert auth['amount_policy']=='unlimited' and 'stage_amount' not in auth
    with offline_guard(),pytest.raises(FileNotFoundError):helper.operate('prepare-pilot','TEST')
    with pytest.raises(O5Error,match='HANDOFF_ID_ALREADY_USED'):helper.prepare_handoff('TEST')


def test_ids_and_provider_cannot_silently_change():
    with pytest.raises(O5Error,match='INVALID_HANDOFF_ID'):helper.paths('../bad')
    p=read(helper.PROFILE);p['model']='other'
    with pytest.raises(O5Error,match='INVALID_DEEPSEEK_FLASH_PROFILE'):require_cost(p)


def test_existing_commands_require_id_and_accept_equals_syntax(monkeypatch,capsys):
    with pytest.raises(SystemExit) as e:helper.main(['verify-preflight'])
    assert e.value.code==2
    monkeypatch.setattr(helper,'operate',lambda command,run_id,resume:{'status':'PASS','id':run_id})
    helper.main(['verify-preflight','--id=TEST'])
    assert json.loads(capsys.readouterr().out)['id']=='TEST'
