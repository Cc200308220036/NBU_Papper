"""Export immutable JN0 records for an offline viewer; no simulator or solver imports."""
import json, hashlib, math
from pathlib import Path
from collections import Counter
ROOT=Path('semantic_pallet_planner/outputs/JEV_JN0_VISUAL_20261103_01')
SOURCE=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_02')
DATA=Path('semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text())
manifest=read(SOURCE/'delivery_manifest.json')['files_sha256']
assert all(sha(SOURCE/n)==h for n,h in manifest.items())
plan=read(SOURCE/'plan/plan.json');jobs=[];counts=Counter();audits=[];hashes={}
for j in plan['jobs']:
    base=SOURCE/'run/jobs'/j['job_id'];cp=read(base/'checkpoint.json');task=read(base/'task.snapshot.json');frozen=read(DATA/'tasks'/f"{j['task_id']}.json")
    cfg=read(base/'config.snapshot.json');events=[]
    for idx,e in enumerate(cp['events']):
        chosen=next((c for c in (e.get('bundle') or {}).get('physical_candidates',[]) if c['candidate_id']==(e.get('selection') or {}).get('selected_candidate_id')),None)
        monitor=e.get('monitor');result=monitor['result'] if monitor else None
        if result:
            counts[result['status']]+=1
            if result['status']=='STABLE':
                d=result['diagnostics'];reactions=d['reactions'];cfgd=d['config'];rows=[]
                for n in d['nodes']:
                    incoming=[r for r in reactions if r['lower']==n['item_id']];outgoing=[r for r in reactions if r['upper']==n['item_id']]
                    own=n['own_mass_kg'];load=math.fsum(r['mass_kg'] for r in incoming)
                    mass=math.fsum(r['mass_kg'] for r in outgoing)-own-load
                    moments=[math.fsum(r['mass_kg']*(r['point_mm'][i]-n['own_center_mm'][i]) for r in outgoing)-math.fsum(r['mass_kg']*(r['point_mm'][i]-n['own_center_mm'][i]) for r in incoming) for i in (0,1)]
                    assert abs(mass)<=n['mass_tolerance_kg'] and max(map(abs,moments))<=n['moment_tolerance_kg_mm']
                    assert math.isclose(mass,n['mass_residual_kg'],abs_tol=1e-12)
                    assert all(math.isclose(x,y,abs_tol=1e-10) for x,y in zip(moments,n['moment_residual_kg_mm']))
                    rows.append({'item_id':n['item_id'],'mass_residual_kg':mass,'moments_kg_mm':moments})
                ground=[r for r in reactions if r['lower'] is None];T=d['input_total_mass_kg']
                assert math.isclose(math.fsum(r['mass_kg'] for r in ground),T,abs_tol=cfgd['mass_atol_kg']+cfgd['mass_rtol']*T)
                assert all(r['mass_kg']>=0 for r in reactions)
                audits.append({'job':j['job_id'],'event':idx,'nodes':len(rows),'reactions':len(reactions),'independent_saved_arithmetic':'PASS'})
        source_path=base/'actions'/f"{e['decision_id']}.json" if e.get('decision_id') else base/'checkpoint.json'
        hashes[str(source_path)]=sha(source_path)
        stages={}
        if e.get('decision_id'):
            for p in (base/'stages'/e['decision_id']).glob('*.json'):stages[p.stem]={'path':str(p),'sha256':sha(p)}
        events.append({'kind':e['event'],'decision':e.get('decision_id'),'before':e['before'],'after':e['after'],
            'candidate':chosen,'candidateCount':len((e.get('bundle') or {}).get('physical_candidates',[])),
            'generation':(e.get('bundle') or {}).get('generation_counts',[]),'selection':e.get('selection'),
            'monitor':monitor,'reason':e.get('reason'),'error':e.get('error'),'timings':e.get('timings',{}),
            'stages':stages,'source':str(source_path),'sha256':sha(source_path),
            'publicContext':({k:e['context'][k] for k in ('model_state','criteria','request_body','display_mapping')} if e.get('context') else None)})
    jobs.append({'id':j['job_id'],'source':task['source_order_key'],'taskId':task['task_id'],'method':j['method_id'],
        'methodName':'几何基线' if 'geometry' in j['method_id'] else '固定顺序基线',
        'container':task['container'],'items':frozen['items'],'events':events,'metrics':read(base/'metrics.json'),
        'status':read(base/'status.json'),'config':cfg,'checkpointSource':str(base/'checkpoint.json'),
        'checkpointSha256':sha(base/'checkpoint.json')})
assert len(jobs)==8 and counts=={'STABLE':59,'UNASSESSABLE':2}
export={'version':'jev_jn0_interactive_review_v1','sourceRoot':str(SOURCE),'sourceManifestSha256':sha(SOURCE/'delivery_manifest.json'),
    'summary':read(SOURCE/'run/summary.json'),'scope':read(SOURCE/'monitor_scope_review.json'),
    'pairs':read(SOURCE/'run/paired_differences.json'),'jobs':jobs,
    'notes':['只读复盘；没有重新选择、物理提交或LP求解。','8次补验收运行，历史技术失败另存原包；累计实际尝试9次。','箱体整单表包含未到货项，仅供事后审计，原选择器不能看到未来箱体。']}
text=json.dumps(export,ensure_ascii=False,separators=(',',':'))
(ROOT/'web/data.js').write_text('window.JN0_DATA = '+text+';\n')
(ROOT/'web/data.json').write_text(text+'\n')
(ROOT/'computation_audit.json').write_text(json.dumps({'status':'PASS','selected_actions':61,'stable':59,'unassessable':2,
    'checked_node_balances':sum(a['nodes'] for a in audits),'actual_order_runs':0,'solver_calls':0,
    'scope':'Independent arithmetic from saved corner reactions; no LP or order execution', 'audits':audits},ensure_ascii=False,indent=2)+'\n')
(ROOT/'source_manifest.json').write_text(json.dumps({'source_manifest_sha256':export['sourceManifestSha256'],'files_sha256':hashes},indent=2)+'\n')
print('exported',len(jobs),'jobs',sum(len(j['events']) for j in jobs),'events;',len(text.encode()),'bytes;',sum(a['nodes'] for a in audits),'node balances independently checked')
