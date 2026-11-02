import json
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select.dataset_j4 import audit_readiness,geometry_keys,verify_seal
from semantic_pallet_planner.jev_select.ledger import write
from semantic_pallet_planner.jev_select.experiment import file_manifest


def test_seal_checks_do_not_resign_or_ignore_modification(tmp_path):
    root=tmp_path/'sealed';root.mkdir();write(root/'evidence.json',{'x':1})
    write(root/'delivery_manifest.json',file_manifest(root));original=(root/'delivery_manifest.json').read_bytes()
    assert verify_seal(root)['status']=='PASS'
    write(root/'evidence.json',{'x':2});assert verify_seal(root)['status']=='FAIL'
    assert (root/'delivery_manifest.json').read_bytes()==original


def test_readiness_exposure_and_multiset_dedup(tmp_path):
    repo=tmp_path/'repo';repo.mkdir()
    def order(mass=1):return {'item_sequence':{str(i):{'length/mm':100,'width/mm':100,'height/mm':100,'weight/kg':mass,'sequence':i} for i in range(1,15)}}
    a=order();b=order(2);raw=repo/'orders.json';write(raw,{'0001':a,'0002':a,'0003':b,'0004':b})
    write(repo/'semantic_pallet_dataset_v1/annotations/ground_truth_rules/X.json',{'scenario_id':'X','source_order_id':'0001','source_order_key':'0001','split':'train'})
    result=audit_readiness(repo,tmp_path/'out',raw_path=raw)
    assert result['data_readiness']['parsed_orders']==4
    assert result['data_readiness']['screened_candidate_sources']==1
    assert result['data_readiness']['exclusion_counts']['exposed']==2
    assert result['data_readiness']['exclusion_counts']['near_duplicate']==1
    assert result['generator_readiness']['status']=='NOT_CONFIGURED'
    assert result['model_api_calls']==0


def test_nested_exposure_and_original_identity_transitive_group(tmp_path):
    repo=tmp_path/'repo';repo.mkdir()
    def order(n,identity):
        return {'properties':{'id':identity},'item_sequence':{str(i):{'length/mm':100,'width/mm':90,'height/mm':100,'weight/kg':n} for i in range(14)}}
    raw=repo/'orders.json'
    write(raw,{'0001':order(1,'parent'),'0002':order(2,'parent'),'0003':order(2,'child'),
               '0004':order(3,'fresh')})
    write(repo/'semantic_pallet_planner/outputs/GEN_x/nested/plan/private/input_snapshot.json',
          {'tasks':[{'provenance':{'original_source_order_id':'0001'}}]})
    result=audit_readiness(repo,tmp_path/'out',raw_path=raw)
    assert result['data_readiness']['screened_candidate_sources']==1
    exposure=json.loads((tmp_path/'out/exposure_manifest.json').read_text())
    assert exposure['candidate_new_sources'][0]['source_order_id']=='0004'
    assert any('GEN_x/nested' in p for p in exposure['scanned_plan_inputs'])
