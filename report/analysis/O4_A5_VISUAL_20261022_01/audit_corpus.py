"""Independent raw-public-record coverage and environment/legacy protection audit."""
import sys
sys.path.insert(0,'semantic_pallet_planner/src')
import json,hashlib
from pathlib import Path
from collections import Counter
from semantic_pallet_planner.o4.common import read,write,digest
ROOT=Path('semantic_pallet_planner/outputs/EXP_O4_A5_VISUAL_20261022_02')
OUT=Path('report/analysis/O4_A5_VISUAL_20261022_01')

def main():
    manifest=read(ROOT/'manifest.json');original=manifest['baseline_paths'];references=[];actual_sources={}
    data=read(Path(original['AB'])/'private/data.json')
    for group in ('gold','pairs'):
        for c in data[group]:
            public=c['request'];key=digest(public);references.append({'origin':f'AB/{group}/{c["case_id"]}','public_source_digest':key});actual_sources[key]=public
    counts={'AB':len(references),'C':0,'F':0}
    for file in sorted((Path(original['C'])/'episodes').glob('*/*/steps.jsonl')):
        for n,line in enumerate(file.open()):
            event=json.loads(line);pub=event['request'];key=digest(pub);actual_sources[key]=pub
            references.append({'origin':f'C/{file.parent.parent.name}/{file.parent.name}/{n}','public_source_digest':key});counts['C']+=1
    for file in sorted((Path(original['F'])/'episodes').glob('*/*/events.jsonl')):
        for n,line in enumerate(file.open()):
            event=json.loads(line)
            for name in ('public_state','after_public_state'):
                pub=event[name];key=digest(pub);actual_sources[key]=pub
                references.append({'origin':f'F/{file.parent.parent.name}/{file.parent.name}/{n}/{name}','public_source_digest':key});counts['F']+=1
    failures=[]
    if counts!={'AB':180,'C':1604,'F':18246}:failures.append('raw corpus counts')
    stored=read(ROOT/'private/source_references.json')
    if references!=stored or digest(references)!=manifest['corpus_digest']:failures.append('exact public source references')
    exported=read(ROOT/'public/bundles.json');assets=read(ROOT/'public/assets.json');categories=set();yaw=set();eos=set();pending=Counter();caps=set();faces=0
    if set(exported)!=set(actual_sources):failures.append('bound public corpus coverage')
    for i,(key,path) in enumerate(exported.items()):
        bundle=read(ROOT/path);source=bundle['source'];facts=bundle['visual_facts']
        if source!=actual_sources[key] or digest(source)!=key:failures.append('public source identity')
        obs=source.get('observation',source)
        current_ids={o['object_id'] for o in obs['placed_objects']+obs['available_objects']}
        if {o['object_id'] for o in facts['objects']}!=current_ids:failures.append('future or missing objects')
        if bundle['text_input']['visual_facts']!=bundle['image_input']['visual_facts']:failures.append('text/image fact parity')
        pending[len(obs['available_objects'])]+=1;caps.add(facts['buffer_capacity']);eos.add(str(facts['end_of_stream']))
        for o in facts['objects']:
            categories.add(o['facts']['cargo_category']);faces+=len(o['faces'])
            if o['location']=='pending' and any(f['world_normal'] is not None or f['world_vertices_mm'] is not None for f in o['faces']):failures.append('phantom pending pose')
            if o['location']=='placed':yaw.add(o['facts']['pose']['yaw_deg'])
        if (i+1)%1000==0:print('independent public corpus checked',i+1,flush=True)
    if categories!={'food','glassware','electronics','household_cleaner','general'} or yaw!={0,90}:failures.append('attribute/yaw coverage')
    if not {0,1,2,3}<=set(pending) or not {'True','False','None'}<=eos or not {1,3}<=caps:failures.append('mode/tail/EOS coverage')
    consistency=read(ROOT/'image_consistency.json');acceptance=read(ROOT/'visual_acceptance.json')
    if consistency['status']!='PASS' or consistency['independent_pixel_checks']!=len(assets) or not consistency['repeat_all_assets']:failures.append('full pixel and repeat audit')
    if acceptance['status']!='PASS' or not acceptance['A5']:failures.append('formal gate')
    if read(ROOT/'audit/network.json')!={'network_attempts':0,'remote_calls':0}:failures.append('network')
    protected=read(ROOT/'audit/protected.after.json')
    if protected['status']!='PASS' or protected['changed']:failures.append('legacy protection')
    results={'status':'PASS' if not failures else 'FAIL','failures':sorted(set(failures)),
      'raw_references':len(references),'raw_by_stage':counts,'unique_bound_inputs':len(exported),'unique_assets':len(assets),
      'asset_kinds':dict(Counter(a['kind'] for a in assets.values())),'categories':sorted(categories),'yaw_degrees':sorted(yaw),
      'pending_count_coverage':dict(pending),'capacities':sorted(caps),'EOS_coverage':sorted(eos),
      'public_face_records_checked':faces,'protected_original_files':protected['files_checked'],'real_api_calls':0}
    write(OUT/'corpus_audit.json',results);print(results)
    if failures:raise SystemExit(1)
if __name__=='__main__':main()
