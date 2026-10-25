import copy
import io
import json
import urllib.request
from pathlib import Path
import pytest
from PIL import Image

from semantic_pallet_planner.o4.common import O4Error,write,read,digest
from semantic_pallet_planner.o4.extensions.data import request,policy,spatial,gold_cases
from semantic_pallet_planner.o4.extensions.protocol import response_for
from semantic_pallet_planner.o4.extensions.visual import render
from semantic_pallet_planner.o4.extensions.visual_verify import verify
from semantic_pallet_planner.o4.extensions.remote import RemoteCompiler,parse_response,prompt,run_remote
from semantic_pallet_planner.o4.extensions.experiment import prepare,validate_plan,verify_seal,new_output
from semantic_pallet_planner.o4.remote.transport import ModelConfig,ChatTransport


def test_new_top_label_png_and_actual_text_tamper(tmp_path):
    q,_=request();asset=render(q,tmp_path,'scene.png')
    assert verify(q,tmp_path,asset)['top_face_labels']
    image=Image.open(tmp_path/'scene.png').convert('RGB');image.putpixel((761,82),(255,0,0));image.save(tmp_path/'scene.png')
    import hashlib
    asset['sha256']=hashlib.sha256((tmp_path/'scene.png').read_bytes()).hexdigest()
    with pytest.raises(O4Error,match='card_text'):verify(q,tmp_path,asset)


def test_visual_source_facts_tamper_detected(tmp_path):
    q=gold_cases()[21]['request'];asset=render(q,tmp_path,'s.png');verify(q,tmp_path,asset)
    p=tmp_path/'s.facts.json';f=read(p);f['objects'][0]['label_face']='pos_x';write(p,f)
    with pytest.raises(O4Error):verify(q,tmp_path,asset)


def test_actual_region_pixel_tamper_detected_with_recomputed_hash(tmp_path):
    import hashlib
    q,_=request();asset=render(q,tmp_path,'s.png')
    image=Image.open(tmp_path/'s.png').convert('RGB')
    image.putpixel((274,400),(255,0,0));image.save(tmp_path/'s.png')
    asset['sha256']=hashlib.sha256((tmp_path/'s.png').read_bytes()).hexdigest()
    with pytest.raises(O4Error,match='scene_geometry'):verify(q,tmp_path,asset)


def transport(tmp_path,monkeypatch,reply):
    bodies=[]
    monkeypatch.setenv('E1_FAKE_KEY','offline-test-only')
    def opener(req,timeout):
        body=json.loads(req.data);bodies.append(body)
        envelope=json.loads(body['messages'][1]['content'][0]['text'])['public_input']
        payload=reply(envelope,len(bodies))
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        return Response(json.dumps(payload).encode())
    cfg=ModelConfig(endpoint='https://offline.invalid/chat/completions',model='offline-test-double',api_key_env='E1_FAKE_KEY')
    return ChatTransport(cfg,opener=opener,test_double=True),bodies


def payload(response):
    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(response)}}],'usage':{'total_tokens':10}}


def test_real_encoding_path_attaches_png_and_one_repair(tmp_path,monkeypatch):
    q,_=request();p=policy([spatial()])
    def reply(envelope,index):
        if index==1:return payload({'bad':'format'})
        return payload(response_for(envelope['public_request'],p))
    t,bodies=transport(tmp_path,monkeypatch,reply)
    compiler=RemoteCompiler(tmp_path,t,2);r=compiler.compile(q,'image')
    assert r['repaired_valid'] and not r['first_valid'] and len(r['attempts'])==2
    content=bodies[0]['messages'][1]['content'];assert content[1]['image_url']['url'].startswith('data:image/png;base64,')
    envelope=json.loads(content[0]['text'])['public_input']
    assert 'reference_policy' not in json.dumps(envelope) and 'allowed_ids' not in json.dumps(envelope)
    assert envelope['visual_facts']['objects'][0]['label_face']=='pos_z'
    assert compiler.compile(q,'text')['status']=='budget_exhausted'
    assert len(bodies)==2 and len(compiler.ledger.rows)==2


def test_valid_semantic_error_is_never_repaired(tmp_path,monkeypatch):
    q,_=request()
    t,bodies=transport(tmp_path,monkeypatch,lambda e,n:payload(response_for(e['public_request'],policy([]))))
    record=RemoteCompiler(tmp_path,t,2).compile(q,'text')
    assert record['status']=='valid' and record['response']['policy_ast']['rules']==[] and len(bodies)==1
    assert len(bodies[0]['messages'][1]['content'])==1


def test_stale_binding_still_fails_after_single_repair(tmp_path,monkeypatch):
    q,_=request()
    def reply(e,n):
        r=response_for(e['public_request'],policy([spatial()]));r['state_hash']='0'*64
        return payload(r)
    t,b=transport(tmp_path,monkeypatch,reply);record=RemoteCompiler(tmp_path,t,5).compile(q,'text')
    assert record['response'] is None and len(b)==2 and record['status']=='invalid_binding'


def test_prepare_seals_source_inputs_and_refuses_overwrite(tmp_path,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('offline plan contacted network')
    monkeypatch.setattr(urllib.request.OpenerDirector,'open',forbidden)
    root=tmp_path/'plan';prepare(root);plan,data,cfg=validate_plan(root)
    assert len(plan['jobs'])==96 and len(data['gold'])==24
    with pytest.raises(O4Error):prepare(root)
    with pytest.raises(O4Error):new_output(root/'inside',(root,))
    p=root/'private/data.json';d=read(p);d['gold'][0]['expected_allowed_ids']=[];write(p,d)
    with pytest.raises(O4Error,match='sealed_artifact_changed'):verify_seal(root)


def test_remote_requires_explicit_flag_before_any_read(tmp_path):
    with pytest.raises(O4Error,match='remote_explicit'):run_remote(tmp_path/'absent',tmp_path/'out',48)


def test_provider_failure_is_recorded_without_fallback(tmp_path,monkeypatch):
    from urllib.error import URLError
    monkeypatch.setenv('E1_FAKE_KEY','offline-test-only')
    def unavailable(req,timeout):raise URLError('injected network outage')
    cfg=ModelConfig(endpoint='https://offline.invalid/chat/completions',model='offline-test-double',api_key_env='E1_FAKE_KEY')
    compiler=RemoteCompiler(tmp_path,ChatTransport(cfg,opener=unavailable,test_double=True),4)
    q,_=request();r=compiler.compile(q,'text')
    assert r['status']=='provider_error' and r['response'] is None and len(r['attempts'])==1
    assert compiler.ledger.rows[0]['status']=='provider_error'


def test_repair_budget_exhaustion_keeps_original_failure(tmp_path,monkeypatch):
    q,_=request();t,bodies=transport(tmp_path,monkeypatch,lambda e,n:payload({'invalid':'response'}))
    r=RemoteCompiler(tmp_path,t,1).compile(q,'text')
    assert r['status']=='budget_exhausted' and r['response'] is None and len(bodies)==1
    assert r['attempts'][0]['status']=='invalid_ast'


def test_same_model_facts_and_bindings_except_image_attachment(tmp_path,monkeypatch):
    q,_=request();p=policy([spatial()])
    t,bodies=transport(tmp_path,monkeypatch,lambda e,n:payload(response_for(e['public_request'],p)))
    compiler=RemoteCompiler(tmp_path,t,2)
    a=compiler.compile(q,'text');b=compiler.compile(q,'image')
    assert a['envelope']['visual_facts']==b['envelope']['visual_facts']
    assert a['response']['state_hash']==b['response']['state_hash']
    assert a['response']['instruction_digest']==b['response']['instruction_digest']
    assert a['response']['observation_digest']!=b['response']['observation_digest']
    for field in ('model','temperature','thinking','max_tokens'):
        assert bodies[0][field]==bodies[1][field]
