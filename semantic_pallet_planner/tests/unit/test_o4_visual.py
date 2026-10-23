import copy
import hashlib
import io
from pathlib import Path
import pytest
from PIL import Image,PngImagePlugin
from semantic_pallet_planner.o4.common import O4Error,digest
from semantic_pallet_planner.o4.fixtures import item,policy,fixture_request,CONTAINER
from semantic_pallet_planner.o4.observation import rebind
from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive,place,public_state
from semantic_pallet_planner.o4.visual.facts import visual_facts,card_facts
from semantic_pallet_planner.o4.visual.bundle import AssetStore,audit_bundle,audit_asset
from semantic_pallet_planner.o4.visual.verify import audit_facts,audit_card,audit_scene,audit_pixels
from semantic_pallet_planner.o4.visual.rendering import card_plan,scene_plan,png_bytes
from semantic_pallet_planner.o4.visual.attachments import offline_transfer,safe_asset
from semantic_pallet_planner.runners.o4_visual import RecordingClient


def request(yaw=0,category='food',no_top=True,reinforced=True,identifier='base'):
    base=item(identifier,category=category,no_top=no_top,reinforced=reinforced,size=(100,200,300),label=2.5)
    base['pose']['yaw_deg']=yaw;base['oriented_size_mm']=[100,200,300] if yaw==0 else [200,100,300]
    return fixture_request([base],item('pending',category='glassware'),policy([]))

@pytest.mark.parametrize('category',['food','glassware','electronics','household_cleaner','general'])
@pytest.mark.parametrize('yaw',[0,90])
def test_category_yaw_facts_primitives_and_real_pixels(category,yaw):
    r=request(yaw,category);f=visual_facts(r);audit_facts(r,f)
    base=f['objects'][0];face=next(x for x in base['faces'] if x['face_id']=='pos_x')
    assert face['world_normal']==([1,0,0] if yaw==0 else [0,1,0])
    assert sorted(face['local_vertices_mm'])==sorted([[50,-100,0],[50,100,0],[50,100,300],[50,-100,300]])
    pending=f['objects'][1];assert all(x['world_vertices_mm'] is None for x in pending['faces'])
    p=scene_plan(f);audit_scene(f,p);b,_=png_bytes(p,f['facts_digest']);audit_pixels(b,p,f['facts_digest'])
    c=card_facts(base);p=card_plan(c);audit_card(c,p);b,_=png_bytes(p,digest(c));audit_pixels(b,p,digest(c))

@pytest.mark.parametrize('capacity',[1,2,3])
def test_real_slots_empty_queue_and_eos(tmp_path,capacity):
    s=initial(CONTAINER,capacity)
    pub=public_state(s,'无额外业务硬约束。');f=visual_facts(pub);assert not f['objects']
    store=AssetStore(tmp_path);b=store.build(pub);audit_bundle(tmp_path,b,store.assets)
    for i in range(capacity):
        box=item('pending_'+str(i));attr=box.pop('_attributes');s=receive(s,box,attr)
    f=visual_facts(public_state(s,'无额外业务硬约束。'))
    assert [o['slot'] for o in f['objects']]==list(range(capacity))
    assert all(o['location']=='pending' and 'pose' not in o['facts'] for o in f['objects'])


def test_instruction_and_storage_order_do_not_color_images():
    r=request();f=visual_facts(r);changed=copy.deepcopy(r)
    changed['instruction_text']='带禁压标记的箱体禁止顶部加载。';changed=rebind(changed)
    other=visual_facts(changed)
    assert f==other
    assert png_bytes(scene_plan(f),f['facts_digest'])[0]==png_bytes(scene_plan(other),other['facts_digest'])[0]
    # Request IDs, storage order and image-free source method identity are not pixel inputs.
    r['request_id']='different_public_request';r['placed_objects'].reverse();r=rebind(r)
    assert visual_facts(r)==f


def test_same_text_facts_actual_png_bytes_and_binding(tmp_path):
    store=AssetStore(tmp_path);b=store.build(request());audit_bundle(tmp_path,b,store.assets)
    assert b['text_input']['visual_facts']==b['image_input']['visual_facts']
    assert b['text_input']['images']==[]
    client=RecordingClient();r=offline_transfer(b['image_input'],tmp_path,client)
    assert r['fake'] and r['image_count']==2 and r['byte_count']>1000
    assert offline_transfer(b['text_input'],tmp_path,client)['image_count']==0
    for asset in store.assets.values():audit_asset(tmp_path,asset,store.assets,repeat=True)
    malformed=copy.deepcopy(b['image_input']);malformed['reference_policy']={'answer':True};malformed['binding_digest']=digest({k:v for k,v in malformed.items() if k!='binding_digest'})
    with pytest.raises(O4Error):offline_transfer(malformed,tmp_path,client)


@pytest.mark.parametrize('key',['reference_policy','future_items','candidates','allowed_ids'])
def test_private_or_answer_fields_rejected(key):
    r=request();r[key]=[]
    with pytest.raises(O4Error):visual_facts(r)


def test_faces_label_geometry_and_pixel_tamper_are_independent(tmp_path):
    r=request(90);f=visual_facts(r);bad=copy.deepcopy(f);bad['objects'][0]['faces'][0]['world_normal']=[1,0,0];bad['facts_digest']=digest({k:v for k,v in bad.items() if k!='facts_digest'})
    with pytest.raises(O4Error):audit_facts(r,bad)
    card=card_facts(f['objects'][0]);p=card_plan(card);next(o for o in p['ops'] if o['id']=='field_limit')['text']='标签累计顶部限载 kg: 999'
    with pytest.raises(O4Error):audit_card(card,p)
    p=card_plan(card);raw,_=png_bytes(p,digest(card));im=Image.open(io.BytesIO(raw)).copy();im.putpixel((1,1),(0,0,0));out=io.BytesIO()
    info=PngImagePlugin.PngInfo();info.add_text('rendering_version','o4_public_render_v1');info.add_text('facts_digest',digest(card));im.save(out,format='PNG',pnginfo=info)
    with pytest.raises(O4Error):audit_pixels(out.getvalue(),p,digest(card))


def test_long_unicode_id_and_no_silent_numeric_rounding():
    r=request(identifier='箱'*128);f=visual_facts(r);c=card_facts(f['objects'][0]);p=card_plan(c);audit_card(c,p)
    headers=[o for o in p['ops'] if o['id'].startswith('id_')]
    assert ''.join(o['text'] for o in headers)=='对象 '+'箱'*128
    assert len(headers)==3
    assert next(o['text'] for o in p['ops'] if o['id']=='field_limit').endswith('2.5')
    assert all(o['xy'][0]>=0 and o['xy'][1]>=0 for o in p['ops'] if o['kind']=='text')


def test_path_escape_corrupt_bytes_and_nonfake_client_rejected(tmp_path):
    with pytest.raises(O4Error):safe_asset(tmp_path,'../escape.png')
    with pytest.raises(O4Error):safe_asset(tmp_path,'/tmp/escape.png')
    store=AssetStore(tmp_path);b=store.build(request());path=tmp_path/b['image_input']['images'][0]['path'];path.write_bytes(b'corrupt')
    with pytest.raises(O4Error):offline_transfer(b['image_input'],tmp_path,RecordingClient())
    class Real:fake=False
    with pytest.raises(O4Error):offline_transfer(b['image_input'],tmp_path,Real())


def test_multibox_storage_reorder_does_not_change_pixels():
    r=fixture_request([item('z',x=-200,no_top=True),item('a',x=200,category='glassware')],item('pending'),policy([]))
    other=copy.deepcopy(r);other['placed_objects'].reverse();other['request_id']='different';other=rebind(other)
    f=visual_facts(r);g=visual_facts(other)
    assert [o['object_id'] for o in f['objects']]==['a','z','pending']
    assert f==g and png_bytes(scene_plan(f),f['facts_digest'])[0]==png_bytes(scene_plan(g),g['facts_digest'])[0]


def test_observed_eos_empty_state_is_renderable_without_phantom_objects(tmp_path):
    s=receive(initial(CONTAINER,3),eos=True);pub=public_state(s,'无额外业务硬约束。')
    store=AssetStore(tmp_path);b=store.build(pub);audit_bundle(tmp_path,b,store.assets)
    assert b['visual_facts']['end_of_stream'] is True and b['visual_facts']['objects']==[]
    assert len(b['image_paths'])==1
    for asset in store.assets.values():audit_asset(tmp_path,asset,store.assets,repeat=True)


def test_mutating_exported_facts_does_not_change_later_requests_or_original():
    source=request();original=copy.deepcopy(source);first=visual_facts(source)
    first['objects'][0]['faces'][0]['local_normal'][0]=99
    first['objects'][0]['label']['uv_rect'][0]=0.99
    fresh=visual_facts(source)
    assert fresh['objects'][0]['faces'][0]['local_normal']==[1,0,0]
    assert fresh['objects'][0]['label']['uv_rect']==[.15,.25,.85,.75]
    card=card_facts(fresh['objects'][0]);card['facts']['labels']['no_top_load']=False
    assert fresh['objects'][0]['facts']['labels']['no_top_load'] is True
    assert source==original
