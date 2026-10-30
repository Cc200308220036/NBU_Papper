import base64
import copy
import io
import json
import socket
import urllib.error
from unittest.mock import Mock

import pytest

from semantic_pallet_planner.jev_select.config import load_config
from semantic_pallet_planner.jev_select.contracts import JevSelectError, canonical, digest
from semantic_pallet_planner.jev_select.ledger import Ledger, exclusive, read
from semantic_pallet_planner.jev_select.selector import JevSelector, LocalSelector, bind_decision, parse_response
from semantic_pallet_planner.jev_select.testing import OfflineTransport
from semantic_pallet_planner.jev_select.transport import JevTransport, outcome, validate_transport


def attempt(context, config, mutate=None, raw=None):
    saved = OfflineTransport(config).complete(context.data['request_body'])
    if mutate:
        payload=json.loads(base64.b64decode(saved['raw_body_b64']))
        mutate(payload)
        raw=json.dumps(payload).encode()
    if raw is not None:
        saved=outcome('OK',raw,http_status=200)
    return {'attempt_id':'A000001','origin':'test_double','transport':saved}


def test_native_choice_parsed_without_explanation(pipeline):
    _,config,_,_,context=pipeline
    selected=parse_response(context,attempt(context,config),config).data
    assert selected['status']=='selected'
    assert selected['selected_candidate_id']==context.data['display_mapping'][selected['selected_display_id']]['candidate_id']
    assert selected['usage'] is None and selected['source']=='test_double'
    assert selected['local_binding_digest']==digest(context.data['local_binding'])


@pytest.mark.parametrize('mutate',[
    lambda p:p.update(model='jev-latest'),
    lambda p:p.update(model=1),
    lambda p:p.update(answers={'unknown':{}}),
    lambda p:p['answers']['next_action'].update(type='score'),
    lambda p:p['answers']['next_action'].update(choice='C99'),
    lambda p:p['answers']['next_action'].update(choice=1),
    lambda p:p['answers']['next_action'].update(probabilities={'C01':1}),
    lambda p:p['answers']['next_action']['probabilities'].update(C01=True),
    lambda p:p['answers']['next_action']['probabilities'].update(C01=-1),
    lambda p:p['answers']['next_action']['probabilities'].update(C01=float('nan')),
    lambda p:p['answers']['next_action']['probabilities'].update(C01=float('inf')),
    lambda p:p['answers']['next_action'].update(confidence=True),
    lambda p:p['answers']['next_action'].update(confidence=1.1),
    lambda p:p['answers']['next_action'].update(probabilities={f'C{i:02d}':0 for i in range(1,49)}),
    lambda p:p['answers']['next_action'].update(probabilities={f'C{i:02d}':1 for i in range(1,49)}),
    lambda p:p.update(usage={'input_tokens':True,'output_tokens':0}),
    lambda p:p.update(usage={'input_tokens':-1,'output_tokens':0}),
    lambda p:p['answers']['next_action'].update(policy_ast={}),
])
def test_invalid_native_answers_never_select(pipeline,mutate):
    _,config,_,_,context=pipeline
    selected=parse_response(context,attempt(context,config,mutate),config).data
    assert selected['status']=='invalid_response'
    assert selected['selected_candidate_id'] is None
    assert selected['selected_display_id'] is None


@pytest.mark.parametrize('raw',[b'not json',b'[]',b'null',b'\xff',b'{"model":"jev-1.14.0","model":"jev-1.14.0"}'])
def test_invalid_json_never_selects(pipeline,raw):
    _,config,_,_,context=pipeline
    assert parse_response(context,attempt(context,config,raw=raw),config).data['status']=='invalid_response'


def test_choice_must_be_maximum_but_ties_and_low_confidence_accepted(pipeline):
    _,config,_,_,context=pipeline
    def tied(p):
        a=p['answers']['next_action']; a.update(choice='C01',probabilities={k:1/48 for k in context.data['criteria']},confidence=0.)
    assert parse_response(context,attempt(context,config,tied),config).data['status']=='selected'
    def not_max(p):
        a=p['answers']['next_action']; a['choice']=next(k for k,v in a['probabilities'].items() if v==0)
    assert parse_response(context,attempt(context,config,not_max),config).data['error']=='choice_not_maximum'


def test_usage_preserved_not_replaced_with_zero(pipeline):
    _,config,_,_,context=pipeline
    record=attempt(context,config,lambda p:p.update(usage={'input_tokens':1234,'output_tokens':20}))
    assert parse_response(context,record,config).data['usage']=={'input_tokens':1234,'output_tokens':20}


def test_same_decision_does_not_call_transport_twice(pipeline,tmp_path):
    _,config,_,_,context=pipeline
    context=bind_decision(context,'J0000','J0000_D0000')
    transport=OfflineTransport(config,'pick_last')
    ledger=Ledger(tmp_path,{'global_attempts':2,'per_job_attempts':1})
    selector=JevSelector(config,ledger,'J0000',transport)
    first=selector.select(context,decision_id='J0000_D0000')
    assert selector.select(context,decision_id='J0000_D0000').data==first.data
    assert first.data['selected_display_id']=='C48' and transport.calls==1
    newer=bind_decision(context,'J0000','J0000_D0001')
    assert selector.select(newer,decision_id='J0000_D0001').data['status']=='budget_exhausted'
    assert transport.calls==1


def test_no_key_no_request_and_no_secret_logs(pipeline,monkeypatch):
    _,config,_,_,context=pipeline
    opener=Mock(); monkeypatch.setattr('urllib.request.build_opener',opener)
    assert JevTransport(config).complete(context.data['request_body'])['error']=='MISSING_OR_INVALID_API_KEY'
    opener.assert_not_called()


@pytest.mark.parametrize('code',[301,302,429,529])
def test_http_failures_single_attempt_no_body_or_key_logging(pipeline,monkeypatch,code):
    _,config,_,_,context=pipeline
    monkeypatch.setenv('TYPESAFE_API_KEY','secret-test-only')
    opener=Mock(); opener.open.side_effect=urllib.error.HTTPError('https://api.typesafe.ai',code,'secret-test-only',{},io.BytesIO(b'secret-test-only'))
    monkeypatch.setattr('urllib.request.build_opener',lambda *args:opener)
    saved=JevTransport(config).complete(context.data['request_body'])
    assert saved['status']=='PROVIDER_FAILURE' and saved['error']==f'HTTP_{code}'
    assert 'secret-test-only' not in canonical(saved)
    assert opener.open.call_count==1


def test_timeout_unknown_no_retry(pipeline,monkeypatch):
    _,config,_,_,context=pipeline
    monkeypatch.setenv('TYPESAFE_API_KEY','test-key')
    opener=Mock(); opener.open.side_effect=TimeoutError()
    monkeypatch.setattr('urllib.request.build_opener',lambda *args:opener)
    assert JevTransport(config).complete(context.data['request_body'])['status']=='UNKNOWN_IN_FLIGHT'
    assert opener.open.call_count==1


def test_transport_size_limit_and_native_encoding(pipeline,monkeypatch):
    _,config,_,_,context=pipeline
    assert JevTransport(config).build_body(context)==context.data['request_body']
    monkeypatch.setenv('TYPESAFE_API_KEY','test-key')
    response=Mock(); response.status=200; response.read.return_value=b'x'*(config['response_max_bytes']+1)
    response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=False)
    opener=Mock(); opener.open.return_value=response
    monkeypatch.setattr('urllib.request.build_opener',lambda *args:opener)
    saved=JevTransport(config).complete(context.data['request_body'])
    request=opener.open.call_args.args[0]
    assert set(json.loads(request.data))=={'model','state','questions'}
    assert saved['error']=='RESPONSE_TOO_LARGE'
    assert len(validate_transport(saved))==config['response_max_bytes']


def test_exclusive_writer_lock(tmp_path):
    with exclusive(tmp_path):
        with pytest.raises(JevSelectError,match='locked'):
            with exclusive(tmp_path):pass
