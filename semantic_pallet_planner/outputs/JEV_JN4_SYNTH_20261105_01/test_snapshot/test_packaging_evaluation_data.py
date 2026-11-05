import copy
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import packaging_evaluation_data as d
from semantic_pallet_planner.jev_select import packaging_source_provenance as provenance
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.packaging_source_audit import sha
from test_packaging_source_provenance import evidence,ASOF
REPO=Path(__file__).resolve().parents[3]


def fixture_inputs(tmp_path):
    raw={}
    for i,n in enumerate([14,15,21,22,31,32]):
        key=f'C{i}';raw[key]={'properties':{'id':key,'order_nr':key},'item_sequence':{str(j+1):{
          'id':f'SKU_{i}','sequence':j+1,'length/mm':30+30*i,'width/mm':20,'height/mm':20,'weight/kg':1+i/10}
          for j in range(n)}}
    write(tmp_path/'raw.json',raw);manifest=sha(tmp_path/'raw.json');proofs={};issuers={}
    for c in raw:
        ident={'component':c,'raw_keys':[c],'raw_manifest_sha256':manifest,'raw_order_digests':{c:digest(raw[c])},'identities':[c]}
        _,statement,policy,seal=evidence(tmp_path/c,ident);body=copy.deepcopy(statement['body']);body['issuer']=c
        statement=seal(body);issuers[c]=policy['issuers']['constructed_custodian']
        proofs[c]={'root':tmp_path/c,'statement':statement}
    policy={'version':'jev_source_trust_policy_v1','fixture_only':True,'issuers':issuers}
    results=[provenance.adjudicate(p['statement']['body']['source_identity'],p['statement'],policy,evidence_root=p['root'],as_of=ASOF) for p in proofs.values()]
    return raw,proofs,policy,results


def test_positive_fixture_materialization_frozen_calibration_unknown_and_loader(tmp_path):
    raw,proofs,policy,admissions=fixture_inputs(tmp_path);selection=d.select_sources(raw,admissions)
    data=d.build(REPO,tmp_path/'raw.json',selection,proofs,policy,tmp_path/'dataset',as_of=ASOF)
    assert data['fixture_only'] and len(data['tasks'])==6 and len({t['source_group_id'] for t in data['tasks']})==6
    assert data['dataset']['calibration']['scale_kg']==9 and data['dataset']['calibration']['m_ref_kg']==8.586
    assert all(t['feasibility_status']=='UNKNOWN' and t['partition']=='test' and t['version']==d.TASK for t in data['tasks'])
    for t in data['dataset']['tasks']:
        original=list(raw[t['source_order_key']]['item_sequence'].values())
        for o,r in zip(t['items'],original):
            assert o['mass_kg']==r['weight/kg'] and o['dimensions_mm']['length']==r['length/mm']
            assert o['max_top_load_kg'] in [0,9,27,54] and o['capacity_provenance']=='controlled_synthetic_experimental'
    from semantic_pallet_planner.jev_select import packaging_evaluation_orders as orders
    plan=orders.prepare(data,tmp_path/'plan',purpose='FIXTURE_ENGINEERING')
    assert len(plan['jobs'])==36 and plan['request_budget']['global']==4*sum(len(t['items']) for t in data['tasks'])
    assert not (tmp_path/'run').exists() # No dataset order trial.
    with pytest.raises(JevSelectError):orders.prepare({**data,'dataset_root':str(tmp_path/'dataset'),'trust_policy':policy},tmp_path/'formal',purpose='FROZEN_FORMAL_TEST')
    wrong=copy.deepcopy(policy);wrong['issuers']={}
    with pytest.raises(JevSelectError):d.load_dataset(tmp_path/'dataset',repo=REPO,policy=wrong)
    payload=read(tmp_path/'dataset/dataset.json');payload['calibration']['scale_kg']=99
    payload['data_identity']=digest({k:v for k,v in payload.items() if k!='data_identity'});write(tmp_path/'dataset/dataset.json',payload)
    from semantic_pallet_planner.jev_select.experiment import file_manifest
    write(tmp_path/'dataset/delivery_manifest.json',file_manifest(tmp_path/'dataset'))
    with pytest.raises(JevSelectError):d.load_dataset(tmp_path/'dataset',repo=REPO,policy=policy)


def test_unknown_stratum_and_false_receipt_do_not_build(tmp_path):
    raw,proofs,policy,admissions=fixture_inputs(tmp_path)
    admissions[0]['strict_test_eligible']=False
    with pytest.raises(JevSelectError):d.select_sources(raw,admissions)
    proof=proofs['C0'];proof['statement']['body']['unknowns']=['unrecorded old experiment']
    with pytest.raises(JevSelectError):d.build(REPO,tmp_path/'raw.json',[{'component':'C0','raw_key':'C0'}],proofs,policy,tmp_path/'dataset',as_of=ASOF)
    assert not (tmp_path/'dataset').exists()
