import base64,copy
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from semantic_pallet_planner.jev_select import packaging_source_provenance as p
from semantic_pallet_planner.jev_select.contracts import canonical,digest,JevSelectError
from semantic_pallet_planner.jev_select.ledger import write
from semantic_pallet_planner.jev_select.packaging_source_audit import sha

ASOF='2026-11-05T00:00:00+00:00'


def evidence(tmp_path,identity=None):
    key=Ed25519PrivateKey.generate()
    identity=identity or {'component':'toy','raw_keys':['toy'],'raw_manifest_sha256':'1'*64,'raw_order_digests':{'toy':'2'*64},'identities':['toy']}
    write(tmp_path/'origin.json',{'type':'CONSTRUCTED_ORIGIN','source':identity})
    write(tmp_path/'lifecycle.json',{'type':'CONSTRUCTED_CUSTODIAN_COMPLETE_LIFECYCLE','usage':'static only; fixture not real proof'})
    write(tmp_path/'review.json',{'type':'CONSTRUCTED_COMPONENT_REVIEW','identity_digest':digest(identity)})
    policy={'version':'jev_source_trust_policy_v1','fixture_only':True,'issuers':{'constructed_custodian':{'public_key_hex':key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex(),'authority_scope':'complete_source_lifecycle'}}}
    body={'version':p.VERSION,'issuer':'constructed_custodian','fixture_only':True,'source_identity':identity,
      'origin':{'created_at':'2020-01-01T00:00:00+00:00','repository_or_acquisition':'CONSTRUCTED_ONLY','evidence_file':'origin.json'},
      'coverage':{'domains':p.DOMAINS,'from':'2020-01-01T00:00:00+00:00','through':ASOF,'closed_world':True,'evidence_file':'lifecycle.json'},
      'uses':[{'id':'audit0','kind':'static_audit','at':ASOF,'evidence_file':'lifecycle.json'}],
      'unknowns':[],'evidence_files':{n:sha(tmp_path/n) for n in ['origin.json','lifecycle.json','review.json']},
      'review':{'conclusion':'COMPLETE','component_identity_digest':digest(identity),'evidence_file':'review.json'}}
    def seal(body):
        body=copy.deepcopy(body);body['body_digest']=digest({k:v for k,v in body.items() if k!='body_digest'})
        return {'body':body,'signature_b64':base64.b64encode(key.sign(canonical(body).encode())).decode()}
    return identity,seal(body),policy,seal


def test_positive_and_no_attestation_unknown(tmp_path):
    ident,s,policy,_=evidence(tmp_path)
    assert p.adjudicate(ident,s,policy,evidence_root=tmp_path,as_of=ASOF)['strict_test_eligible']
    r=p.adjudicate(ident,None,policy,evidence_root=tmp_path,as_of=ASOF)
    assert r['status']=='UNKNOWN_EXPOSURE' and 'missing_signed_provenance' in r['gaps']


@pytest.mark.parametrize('kind',['training','policy_development','model_requests','memory_build','historical_testing'])
def test_pollution_cannot_be_signed_away(tmp_path,kind):
    ident,s,policy,seal=evidence(tmp_path);b=copy.deepcopy(s['body']);b['uses'].append({'id':'contamination','kind':kind,'at':ASOF,'evidence_file':'lifecycle.json'})
    result=p.adjudicate(ident,seal(b),policy,evidence_root=tmp_path,as_of=ASOF)
    assert not result['strict_test_eligible'] and result['status']==('HISTORICAL_TEST' if kind=='historical_testing' else 'CONTAMINATED')
    assert not p.adjudicate(ident,s,policy,evidence_root=tmp_path,as_of=ASOF,observed_uses=['training'])['strict_test_eligible']


@pytest.mark.parametrize('change',['scope','dates','unknown','review','coverage_file','authority'])
def test_incomplete_remains_unknown(tmp_path,change):
    ident,s,policy,seal=evidence(tmp_path);b=s['body']
    if change=='scope':b['coverage']['domains']=p.DOMAINS[:-1]
    if change=='dates':b['coverage']['through']='2025-01-01T00:00:00+00:00'
    if change=='unknown':b['unknowns']=['external experiments not accounted']
    if change=='review':b['review']['conclusion']='INCOMPLETE'
    if change=='coverage_file':b['coverage']['evidence_file']='not_bound.json'
    if change=='authority':policy['issuers']={}
    result=p.adjudicate(ident,seal(b),policy,evidence_root=tmp_path,as_of=ASOF)
    assert result['status']=='UNKNOWN_EXPOSURE' and result['gaps']


@pytest.mark.parametrize('change',['signature','file','identity','extra','fixture_as_real'])
def test_tamper_rejected(tmp_path,change):
    ident,s,policy,seal=evidence(tmp_path)
    if change=='signature':s['signature_b64']=base64.b64encode(b'0'*64).decode()
    if change=='file':write(tmp_path/'origin.json',{'modified':True})
    if change=='identity':ident=copy.deepcopy(ident);ident['raw_keys']=['another']
    if change=='extra':s['extra']=True
    if change=='fixture_as_real':policy['fixture_only']=False
    with pytest.raises(JevSelectError):p.adjudicate(ident,s,policy,evidence_root=tmp_path,as_of=ASOF)


def test_batch_auditor_can_return_positive_count(tmp_path):
    raw={'toy':{'identity':'constructed'}}
    ident={'component':'toy','raw_keys':['toy'],'raw_manifest_sha256':'1'*64,'raw_order_digests':{'toy':digest(raw['toy'])},'identities':['toy']}
    _,s,policy,_=evidence(tmp_path,ident)
    c={'component':'toy','raw_keys':['toy'],'identities':['toy'],'exposure_status':'UNKNOWN_EXPOSURE'}
    result=p.audit_admissions([c],'1'*64,{'toy':s},policy,evidence_root=tmp_path,as_of=ASOF,raw_orders=raw)
    assert result['source_count']==1 and result['eligible_components']==['toy']
