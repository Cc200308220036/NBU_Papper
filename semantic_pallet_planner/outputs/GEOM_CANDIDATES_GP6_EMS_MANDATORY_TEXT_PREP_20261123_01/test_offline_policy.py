"""Synthetic post-hoc tests plus saved prefix smoke; no model/solver/credential access."""
import copy
import importlib.util
import json
from pathlib import Path
import pytest
HERE=Path(__file__).parent

def module(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
A=module('audit_rules_v1');P=module('prompt_policy')

def box(x,y,z=0,l=10,w=10,h=10,id='item'):
    return {'pick_item_id':id,'pose':{'x_mm':x,'y_mm':y,'z_base_mm':z,'yaw_deg':0},'oriented_size_mm':[l,w,h]}

def event(choices,chosen,placed=()):
    pool=[];mapping={}
    for label,b in choices.items():
        c={**copy.deepcopy(b),'candidate_id':'SYNTHETIC_'+label}
        pool.append(c);mapping[label]={'candidate_id':c['candidate_id'],'candidate_digest':A.digest(c),'pick_item_id':c['pick_item_id']}
    return {'decision_id':'SYNTHETIC_ONLY','before':{'container':{'coordinate_frame':'container_bottom_center','length_mm':100,'width_mm':100},'placed_items':list(placed)},
      'bundle':{'physical_candidates':pool},'context':{'route':'CHOICE_REQUIRED','request_body':{'questions':{'next_action':{'criteria':{k:'synthetic' for k in choices}}}},'display_mapping':mapping},
      'selection':{'status':'selected','selected_display_id':chosen,'selected_candidate_id':'SYNTHETIC_'+chosen}}

def test_lowest_bottom_beats_lower_top_and_better_corner():
    e=event({'C01':box(0,0,0,h=100),'C02':box(-45,-45,1,h=1)},'C02')
    r=A.audit_published_choice(e)
    assert r['violation_rule']==1 and r['hard_rule_finalists_Cxx']==['C01']

def test_corner_distance_before_contact_and_no_mutation():
    # C02 touches an existing side but C01 wins the earlier corner-distance rule.
    e=event({'C01':box(-45,-45),'C02':box(-35,-45)},'C02',[box(-25,-45)])
    original=copy.deepcopy(e);r=A.audit_published_choice(e)
    assert r['violation_rule']==2 and r['hard_rule_finalists_Cxx']==['C01']
    assert e==original

def test_contact_breaks_tie_after_height_and_distance():
    # Both clearances sum to10. Only C01 touches placed side at x=-30.
    e=event({'C01':box(-35,-45),'C02':box(-45,-35)},'C02',[box(-25,-45)])
    r=A.audit_published_choice(e)
    assert r['violation_rule']==3 and r['hard_rule_finalists_Cxx']==['C01']
    e['selection'].update(selected_display_id='C01',selected_candidate_id='SYNTHETIC_C01')
    assert A.audit_published_choice(e)['status']=='COMPLIANT_UNIQUE_HARD_RULE_WINNER'

def test_empty_skips_contact_and_keeps_final_tie_unassessable():
    r=A.audit_published_choice(event({'C01':box(-45,-45),'C02':box(-45,-45,l=10,w=10,h=20)},'C02'))
    assert r['stages'][2]['status']=='SKIPPED_EMPTY_PALLET'
    assert r['status']=='NO_HARD_RULE_VIOLATION_FINAL_TIE_UNASSESSABLE'
    assert r['hard_rule_finalists_Cxx']==['C01','C02']

def test_side_bottom_union_no_double_count_and_no_pallet_contact():
    c=box(0,0,z=10);support=box(0,0,z=0)
    side=box(10,0,z=10)
    result=A.face_contact_area_mm2(c,[support,support,side,side])
    assert result['total_mm2']==200
    assert result['by_face_mm2']['bottom']==100 and result['by_face_mm2']['x_max']==100
    assert A.face_contact_area_mm2(box(0,0),[])['total_mm2']==0
    assert A.face_contact_area_mm2(c,[box(10.01,0,z=10)])['total_mm2']==0

def test_only_published_candidates_not_hidden_physical_candidates():
    e=event({'C01':box(0,0),'C02':box(-45,-45,z=1)},'C01')
    e['bundle']['physical_candidates'].append({**box(-45,-45),'candidate_id':'HIDDEN_NOT_PUBLISHED'})
    r=A.audit_published_choice(e)
    assert r['hard_rule_finalists_Cxx']==['C01'] and len(r['scores_in_original_order'])==2

def test_length_tolerance_keeps_near_tie():
    e=event({'C01':box(-45,-45),'C02':box(-45,-45,z=0.5e-6)},'C02')
    assert A.audit_published_choice(e)['violation_rule'] is None

def test_binding_drift_and_invalid_label_rejected():
    e=event({'C01':box(0,0),'C02':box(-45,-45)},'C01')
    e['bundle']['physical_candidates'][0]['pose']['x_mm']=1
    with pytest.raises(ValueError,match='CANDIDATE_DIGEST_MISMATCH'):A.audit_published_choice(e)
    e=event({'C01':box(0,0),'C02':box(-45,-45)},'C01')
    e['selection']['selected_display_id']='C99'
    with pytest.raises(ValueError,match='ORIGINAL_SELECTION_MAPPING_MISMATCH'):A.audit_published_choice(e)

def test_replacement_text_preserves_base_and_all_options():
    body={'model':'jev-1.14.0','state':{'observed':'synthetic only'},'questions':{'next_action':{'type':'choice','instructions':(HERE/'base_selection_instructions.txt').read_text(),'criteria':{'C01':'a','C02':'b'}}}}
    before=copy.deepcopy(body);wire=P.prepare_wire_body(body)
    assert body==before
    assert wire['questions']['next_action']['instructions']==P.full_instruction()
    wire['questions']['next_action']['instructions']=before['questions']['next_action']['instructions']
    assert wire==before
    with pytest.raises(ValueError,match='EXPECTED_UNMODIFIED_BASE_INSTRUCTION'):
        P.prepare_wire_body({**body,'questions':{'next_action':{**body['questions']['next_action'],'instructions':'already appended legacy preference'}}})

def test_saved_first_choice_would_violate_new_rule_two_not_new_run():
    p=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_EMS_CORNER_20261123_01/run/jobs/G01/checkpoint.json')
    e=next(e for e in json.loads(p.read_text())['events'] if e.get('event')=='PLACE')
    before=copy.deepcopy(e);r=A.audit_published_choice(e)
    assert r['original_selected_Cxx']=='C17' and r['violation_rule']==2
    assert len(r['hard_rule_finalists_Cxx'])==6 and e==before


def test_original_choice_verified_against_raw_response_and_ledger():
    import base64,hashlib
    e=event({'C01':box(0,0),'C02':box(-45,-45)},'C01')
    raw=json.dumps({'answers':{'next_action':{'choice':'C01'}}}).encode()
    t={'status':'OK','raw_body_b64':base64.b64encode(raw).decode(),'raw_sha256':hashlib.sha256(raw).hexdigest()}
    row={'decision_id':e['decision_id'],'selection':copy.deepcopy(e['selection']),'selection_digest':A.digest(e['selection']),
         'body_digest':A.digest(e['context']['request_body']),'transport':t,'transport_digest':A.digest(t)}
    ledger={'requests':[row]}
    assert A.verify_raw_choice(e,ledger)=='C01'
    # A coherent-looking substituted saved selection must still fail raw-response check.
    e['selection'].update(selected_display_id='C02',selected_candidate_id='SYNTHETIC_C02')
    row.update(selection=copy.deepcopy(e['selection']),selection_digest=A.digest(e['selection']))
    with pytest.raises(ValueError,match='RAW_JEV_CHOICE_MISMATCH'):A.verify_raw_choice(e,ledger)
