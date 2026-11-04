"""A5 public-only deterministic imagery, independent pixel audit and replay. Offline."""
import argparse
import copy
import hashlib
import io
import json
import shutil
import sys
import zlib
from collections import Counter
from pathlib import Path
import yaml
import PIL
from PIL import Image
from ..config import WORKSPACE
from ..o4.common import read,write,digest,O4Error
from ..o4.visual.facts import FONT,VERSION,visual_facts
from ..o4.visual.bundle import AssetStore,audit_asset,audit_bundle
from ..o4.visual.corpus import load_corpus
from ..o4.visual.attachments import offline_transfer
from .o4 import snapshot_existing,check_protected
from .o4_online import sha,delivery_hashes,seal,offline_network_guard

DEFAULT_AB=WORKSPACE/'semantic_pallet_planner/outputs/EXP_O4_AB_OFFLINE_20261021_01'
DEFAULT_C=WORKSPACE/'semantic_pallet_planner/outputs/EXP_O4_C_ONLINE_20261021_01'
DEFAULT_F=WORKSPACE/'semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01'
DEFAULT_CONFIG=WORKSPACE/'semantic_pallet_planner/configs/o4_a5_visual.yaml'


def config():
    expected={'version':VERSION,'label_face_version':'o4_simulated_label_pos_x_v1','local_label_face':'pos_x','label_uv_rect':[.15,.25,.85,.75],
      'length_unit':'mm','mass_unit':'kg','scene':'xy_xz_yz_wireframe','label_cards_per_page':6,'font':'NotoSansCJK-Regular.ttc','real_api':False}
    if yaml.safe_load(DEFAULT_CONFIG.read_text())!=expected:raise ValueError('A5 v1 config is frozen; changes require a new version')
    return {'version':VERSION,'label_face':'pos_x','label_uv_rect':[.15,.25,.85,.75],
            'images':'orthographic_scene_plus_six_local_cards_per_page','font_sha256':sha(FONT),
            'real_api':False,'units':{'length':'mm','mass':'kg'},'label_source':'accurate_simulated_public_print_layout'}


def sources():
    pkg=WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner'
    files=list((pkg/'o4/visual').rglob('*.py'))+list((pkg/'o4/visual/schemas').glob('*.json'))+[pkg/'runners/o4_visual.py',DEFAULT_CONFIG,WORKSPACE/'semantic_pallet_planner/pyproject.toml']
    return {str(f.relative_to(WORKSPACE)):sha(f) for f in sorted(files) if '__pycache__' not in f.parts}


def verify_baselines(paths):
    records=[]
    for name,path in paths.items():
        path=Path(path).resolve();manifest=read(path/'manifest.json')
        if read(path/'delivery_manifest.json')['files']!=delivery_hashes(path):raise ValueError(name+' frozen delivery changed')
        inventory=manifest.get('source_sha256',manifest.get('sources'))
        if any(sha(WORKSPACE/f)!=h for f,h in inventory.items()):raise ValueError(name+' frozen source modified')
        acceptance=read(path/({'AB':'acceptance_report.json','C':'offline_acceptance.json','F':'buffer_acceptance.json'}[name]))
        if acceptance['status']!='PASS':raise ValueError(name+' requires accepted baseline')
        records.append({'name':name,'path':str(path),'manifest_sha256':sha(path/'manifest.json'),'delivery_sha256':sha(path/'delivery_manifest.json'),'frozen_source_files':len(inventory)})
    return records


class RecordingClient:
    fake=True
    def __init__(self):self.calls=[]
    def complete(self,prompt):
        self.calls.append({'condition':prompt['public_input']['condition'],
            'attachments':[{'path':a['path'],'sha256':hashlib.sha256(a['bytes']).hexdigest(),'bytes':len(a['bytes'])} for a in prompt['image_attachments']]})
        return {'transport':'received_public_images','binding_digest':prompt['public_input']['binding_digest']}


def verify_delivery(root,*,repeat=False,protection=True):
    root=Path(root).resolve()
    try:
        if read(root/'delivery_manifest.json')['files']!=delivery_hashes(root):raise ValueError('delivery file set/hash changed')
        manifest=read(root/'manifest.json')
        if manifest['sources']!=sources():raise ValueError('A5 source drift')
        for name,h in manifest['sources'].items():
            if sha(root/'code_snapshot'/name)!=h:raise ValueError('code snapshot drift')
        if read(root/'config.snapshot.json')!=config() or sha(root/'environment/font.ttc')!=config()['font_sha256']:raise ValueError('font/config changed')
        if verify_baselines(manifest['baseline_paths'])!=manifest['baselines']:raise ValueError('baseline changed')
        if protection and check_protected(read(root/'audit/protected.before.json'))['status']!='PASS':raise ValueError('protected inputs changed')
        assets=read(root/'public/assets.json');reports=[]
        for i,a in enumerate(assets.values()):
            reports.append(audit_asset(root,a,assets,root/'environment/font.ttc',repeat=repeat))
            if (i+1)%200==0:print('A5 checked assets',i+1,'/',len(assets),flush=True)
        bundles=read(root/'public/bundles.json');checked=0
        for key,path in bundles.items():
            b=read(root/path);audit_bundle(root,b,assets);checked+=1
            if digest(b['source'])!=key:raise ValueError('source alias digest')
        references=read(root/'private/source_references.json')
        if any(r['public_source_digest'] not in bundles for r in references):raise ValueError('reference coverage')
        return {'status':'PASS','read_only':True,'asset_count':len(assets),'bundle_count':checked,
                'source_references':len(references),'asset_kinds':dict(Counter(a['kind'] for a in assets.values())),
                'independent_pixel_checks':len(reports),'repeat_all_assets':repeat,'real_api_calls':0}
    except (ValueError,KeyError,TypeError,OSError) as exc:
        return {'status':'FAIL','read_only':True,'failures':[str(exc)]}


def tamper_checks(root,assets):
    results=[]
    # Test semantics even after an attacker updates PNG and manifest hashes.
    asset=next((a for a in assets.values() if a['kind']=='card'),None)
    if asset is None:return [{'case':'object_specific_tamper','detected':None,'applicable':False}]
    from ..o4.visual.verify import audit_card,audit_pixels,audit_facts
    wrong=copy.deepcopy(asset['plan']);next(o for o in wrong['ops'] if o['id']=='field_no_top')['text']='禁压标记: corrupted'
    try:audit_card(asset['public_facts'],wrong);detected=False
    except O4Error:detected=True
    results.append({'case':'wrong_label_text_with_valid_structure','detected':detected})
    png=(root/asset['path']).read_bytes();im=Image.open(io.BytesIO(png)).copy();im.putpixel((0,0),(1,2,3))
    out=io.BytesIO();from PIL import PngImagePlugin
    info=PngImagePlugin.PngInfo();info.add_text('rendering_version',VERSION);info.add_text('facts_digest',asset['content_digest']);im.save(out,format='PNG',pnginfo=info)
    try:audit_pixels(out.getvalue(),asset['plan'],asset['content_digest']);detected=False
    except O4Error:detected=True
    results.append({'case':'pixel_modified_even_with_new_file_hash','detected':detected})
    bundles=read(root/'public/bundles.json');b=read(root/next(iter(bundles.values())));wrong=copy.deepcopy(b['visual_facts']);wrong['objects'][0]['faces'][0]['world_normal']=[0,0,1];wrong['facts_digest']=digest({k:v for k,v in wrong.items() if k!='facts_digest'})
    try:audit_facts(b['source'],wrong);detected=False
    except O4Error:detected=True
    results.append({'case':'face_normal_changed_and_rehashed','detected':detected})
    return results


def run(output,*,ab=DEFAULT_AB,c=DEFAULT_C,f=DEFAULT_F,limit=None,protection_before=None,source=None):
    root=Path(output).resolve();paths={'AB':str(Path(ab).resolve()),'C':str(Path(c).resolve()),'F':str(Path(f).resolve())}
    if root.exists():raise FileExistsError('choose a new output directory; never overwrite')
    forbidden=[WORKSPACE/'semantic_pallet_dataset_v1',WORKSPACE/'semantic_pallet_planner/src',*[Path(p) for p in paths.values()]]
    if any(root==p or p in root.parents for p in forbidden):raise ValueError('protected output path')
    if limit is not None and limit<1:raise ValueError('positive smoke limit required')
    before=read(protection_before) if protection_before else snapshot_existing()
    if check_protected(before)['status']!='PASS':raise ValueError('pre-existing protection mismatch')
    if not FONT.is_file():raise ValueError('pinned Noto CJK font is required')
    baselines=verify_baselines(paths)
    corpus,refs=({digest(source):source},[{'origin':'explicit_public_input','public_source_digest':digest(source)}]) if source else load_corpus(ab,c,f,limit)
    root.mkdir(parents=True);write(root/'audit/protected.before.json',before);write(root/'config.snapshot.json',config())
    (root/'environment').mkdir();shutil.copyfile(FONT,root/'environment/font.ttc')
    write(root/'environment/versions.json',{'python':sys.version,'pillow':PIL.__version__,'zlib':zlib.ZLIB_VERSION,'font_sha256':sha(FONT)})
    write(root/'private/source_references.json',refs)
    inventory=sources()
    for name in inventory:
        dest=root/'code_snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(WORKSPACE/name,dest)
    write(root/'manifest.json',{'version':VERSION,'sources':inventory,'baselines':baselines,'baseline_paths':paths,'corpus_digest':digest(refs),'full_corpus':limit is None and source is None})
    with offline_network_guard() as ledger:
        store=AssetStore(root);bundles={};coverage=Counter()
        for i,(key,pub) in enumerate(corpus.items(),1):
            bundle=store.build(pub);path=f'public/requests/{key}.json';write(root/path,bundle);bundles[key]=path
            for obj in bundle['visual_facts']['objects']:
                coverage['category_'+obj['facts']['cargo_category']]+=1
                coverage['yaw_'+str(obj['facts'].get('pose',{}).get('yaw_deg','pending'))]+=1
            coverage['capacity_'+str(bundle['visual_facts']['buffer_capacity'])]+=1
            if i%100==0:print('A5 built public states',i,'/',len(corpus),flush=True)
        write(root/'public/assets.json',store.assets);write(root/'public/bundles.json',bundles)
        client=RecordingClient();first=read(root/next(iter(bundles.values())))
        image_transport=offline_transfer(first['image_input'],root,client);text_transport=offline_transfer(first['text_input'],root,client)
        write(root/'audit/transport.json',{'image':image_transport,'text':text_transport,'calls':client.calls,'fake':True})
        tampered=tamper_checks(root,store.assets);write(root/'audit/tamper.json',tampered)
        protected=check_protected(before);write(root/'audit/protected.after.json',protected);write(root/'audit/network.json',ledger)
        write(root/'coverage.json',{'raw_public_state_references':len(refs),'unique_bound_public_inputs':len(corpus),'unique_assets':len(store.assets),'attributes':dict(coverage),'full_corpus':limit is None and source is None})
        seal(root);audit=verify_delivery(root,repeat=True);write(root/'image_consistency.json',audit)
        passed=audit['status']=='PASS' and protected['status']=='PASS' and ledger['network_attempts']==0 and all(t['detected'] for t in tampered if t.get('applicable',True)) and image_transport['image_count']>0 and text_transport['image_count']==0
        status='PASS' if passed and limit is None and source is None else ('PARTIAL' if passed else 'FAIL')
        acceptance={'status':status,'scope':'O4_A5_FORMAL_PUBLIC_IMAGES' if limit is None and source is None else 'O4_A5_SMOKE_OR_EXPLICIT_INPUT',
            'A5':passed and limit is None and source is None,'coverage':read(root/'coverage.json'),
            'image_consistency':audit,'fake_transport_only':True,'real_api_calls':0,
            'deferred':{'A6':'ACTUAL_HUMAN_REVIEW','D':'REAL_MODEL_EVALUATION','E':'REGION_ORIENTATION_CONSTRAINTS'},'full_o4_status':'INCOMPLETE'}
        write(root/'visual_acceptance.json',acceptance);seal(root)
    return acceptance


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['acceptance','smoke','render','replay'])
    p.add_argument('--output',required=True);p.add_argument('--source',help='render: image-free public request or full public buffer state JSON')
    p.add_argument('--ab',default=str(DEFAULT_AB));p.add_argument('--c',default=str(DEFAULT_C));p.add_argument('--f',default=str(DEFAULT_F))
    p.add_argument('--limit',type=int,default=4);p.add_argument('--protection-before');p.add_argument('--repeat',action='store_true')
    a=p.parse_args(argv)
    if a.command=='replay':
        with offline_network_guard():r=verify_delivery(a.output,repeat=a.repeat)
    else:
        if a.command=='render' and not a.source:p.error('render requires --source')
        r=run(a.output,ab=a.ab,c=a.c,f=a.f,limit=a.limit if a.command=='smoke' else None,protection_before=a.protection_before,source=read(a.source) if a.source else None)
    print(json.dumps(r,ensure_ascii=False,sort_keys=True))
    if r['status'] not in ('PASS','PARTIAL'):raise SystemExit(1)

if __name__=='__main__':main()
